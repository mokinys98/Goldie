import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import requests
from redis import Redis
from redis.exceptions import RedisError

from .models import Candle, Instrument, Quote
from .settings import CollectorSettings

MAX_HTTP_CANDLE_BATCH_SIZE = 50


class GoldieApiClient:
    def __init__(self, settings: CollectorSettings) -> None:
        self.base_url = settings.api_url.rstrip("/")
        self.headers = {"X-Agent-Token": settings.agent_token}
        self.timeout = settings.request_timeout_seconds
        self.settings = settings
        self.ingestion_transport = getattr(settings, "ingestion_transport", "http")
        self.quote_batch_seconds = getattr(settings, "quote_batch_seconds", 1.0)
        self.quote_batch_size = getattr(settings, "quote_batch_size", 250)
        self.candle_batch_size = getattr(settings, "candle_batch_size", 500)
        self.feed_id: uuid.UUID | None = None
        self.agent_id: uuid.UUID | None = None
        self.collector_id: uuid.UUID | None = None
        self.resume_from_at: datetime | None = None
        self.redis = Redis.from_url(
            getattr(settings, "redis_url", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        self.quote_buffer: list[Quote] = []
        self.quote_buffer_started_at: float | None = None

    def set_collector_id(self, collector_id: str | uuid.UUID | None) -> None:
        self.collector_id = uuid.UUID(str(collector_id)) if collector_id else None

    def post(self, path: str, payload: dict[str, Any]) -> dict:
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise TimeoutError(
                f"Goldie API request timed out after {self.timeout}s for {path}"
            ) from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Goldie API request failed for {path}: {exc}") from exc
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            hint = ""
            if response.status_code == 404 and path == "/api/v1/market-feeds/register":
                hint = (
                    " GOLDIE_API_URL must point to the Goldie API service, "
                    "not the Web service."
                )
            raise RuntimeError(
                f"Goldie API request failed with HTTP {response.status_code} "
                f"for {response.url}.{hint}"
            ) from exc
        return response.json()

    def patch(self, path: str, payload: dict[str, Any]) -> dict:
        response = requests.patch(
            f"{self.base_url}{path}",
            json=payload,
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def register(self, settings: CollectorSettings) -> datetime | None:
        result = self.post(
            "/api/v1/market-feeds/register",
            {
                "provider": settings.provider,
                "environment": settings.provider_environment,
                "canonical_symbol": settings.canonical_symbol,
                "provider_symbol": settings.provider_symbol,
                "agent_name": settings.agent_name,
                "details": {
                    "read_only": True,
                    "runtime": "railway",
                    "provider": settings.provider,
                },
            },
        )
        self.feed_id = uuid.UUID(result["feed"]["id"])
        self.agent_id = uuid.UUID(result["agent"]["id"])
        resume_from = result["feed"].get("resume_from_at")
        self.resume_from_at = (
            datetime.fromisoformat(resume_from.replace("Z", "+00:00"))
            if resume_from
            else None
        )
        value = result.get("latest_candle_at")
        if not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    def register_instance(self, settings: CollectorSettings) -> dict:
        result = self.post(
            "/api/v1/collector/instances/register",
            {
                "name": settings.agent_name,
                "defaults": {
                    "quote_interval_seconds": settings.quote_interval_seconds,
                    "candle_poll_seconds": settings.candle_poll_seconds,
                    "heartbeat_seconds": settings.heartbeat_seconds,
                    "backfill_days": settings.backfill_days,
                    "backfill_batch_size": settings.backfill_batch_size,
                    "configuration_retry_seconds": settings.configuration_retry_seconds,
                },
                "instruments": settings.instrument_specs,
            },
        )
        self.set_collector_id(result["instance"]["id"])
        return result

    def poll_control(self, instance_id: str) -> dict:
        return self.post(f"/api/v1/collector/instances/{instance_id}/poll", {})

    def instance_heartbeat(
        self,
        instance_id: str,
        status: str,
        applied_config_version: int | None,
        details: dict[str, Any],
    ) -> None:
        self.post(
            f"/api/v1/collector/instances/{instance_id}/heartbeat",
            {
                "status": status,
                "applied_config_version": applied_config_version,
                "details": details,
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )

    def update_command(
        self,
        command_id: str,
        status: str,
        *,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.patch(
            f"/api/v1/collector/commands/{command_id}",
            {
                "status": status,
                "progress": progress or {},
                "result": result or {},
                "error": error,
            },
        )

    def _identity(self) -> tuple[str, str]:
        if self.feed_id is None or self.agent_id is None:
            raise RuntimeError("Collector is not registered")
        return str(self.feed_id), str(self.agent_id)

    def heartbeat(self, status: str, details: dict[str, Any]) -> None:
        feed_id, agent_id = self._identity()
        self.post(
            f"/api/v1/market-feeds/{feed_id}/heartbeat",
            {
                "agent_id": agent_id,
                "status": status,
                "details": details,
                "observed_at": datetime.now().astimezone().isoformat(),
            },
        )

    def instrument(self, instrument: Instrument) -> None:
        feed_id, agent_id = self._identity()
        self.post(
            f"/api/v1/market-feeds/{feed_id}/instrument-specification",
            {
                "agent_id": agent_id,
                **instrument.model_dump(mode="json"),
            },
        )

    def quotes(self, quotes: list[Quote]) -> None:
        if not quotes:
            return
        if self.ingestion_transport == "http":
            self._send_batch("quote_batch", quotes)
            return
        if not self.quote_buffer:
            self.quote_buffer_started_at = time.monotonic()
        self.quote_buffer.extend(quotes)
        if len(self.quote_buffer) >= self.quote_batch_size:
            self.flush_quotes()

    def flush_due(self) -> None:
        if (
            self.quote_buffer
            and self.quote_buffer_started_at is not None
            and time.monotonic() - self.quote_buffer_started_at
            >= self.quote_batch_seconds
        ):
            self.flush_quotes()

    def flush_quotes(self) -> None:
        if not self.quote_buffer:
            return
        batch = self.quote_buffer[: self.quote_batch_size]
        del self.quote_buffer[: len(batch)]
        self.quote_buffer_started_at = time.monotonic() if self.quote_buffer else None
        self._send_batch("quote_batch", batch)

    def candles(self, candles: list[Candle]) -> dict:
        if not candles:
            return {"accepted": True, "count": 0, "duplicates": 0}
        accepted = 0
        duplicates = 0
        batch_size = self.candle_batch_size
        if self.ingestion_transport == "http":
            batch_size = min(batch_size, MAX_HTTP_CANDLE_BATCH_SIZE)
        for index in range(0, len(candles), batch_size):
            batch = candles[index : index + batch_size]
            result = self._send_batch("candle_batch", batch)
            accepted += int(result.get("count", len(batch)))
            duplicates += int(result.get("duplicates", 0))
        return {
            "accepted": True,
            "count": accepted,
            "duplicates": duplicates or max(0, len(candles) - accepted),
        }

    def _send_batch(self, event_type: str, items: list[Quote] | list[Candle]) -> dict:
        feed_id, agent_id = self._identity()
        event_id = uuid.uuid4()
        sent_at = datetime.now(UTC).isoformat()
        item_key = "quotes" if event_type == "quote_batch" else "candles"
        payload = {
            "event_id": str(event_id),
            "collector_id": str(self.collector_id) if self.collector_id else None,
            "sent_at": sent_at,
            "agent_id": agent_id,
            item_key: [item.model_dump(mode="json") for item in items],
        }
        if self.ingestion_transport == "redis":
            try:
                stream = (
                    "goldie:ingestion:quotes:v2"
                    if event_type == "quote_batch"
                    else "goldie:ingestion:candles:v2"
                )
                self.redis.xadd(
                    stream,
                    {
                        "schema_version": "1",
                        "event_id": str(event_id),
                        "event_type": event_type,
                        "collector_id": str(self.collector_id or ""),
                        "market_feed_id": feed_id,
                        "agent_id": agent_id,
                        "sent_at": sent_at,
                        "payload": json.dumps(payload),
                    },
                )
                return {"accepted": True, "count": len(items), "queued": True}
            except (RedisError, OSError):
                logging.getLogger(__name__).warning(
                    "Redis ingestion unavailable; falling back to HTTP",
                    exc_info=True,
                )
        path = "quotes" if event_type == "quote_batch" else "candles"
        try:
            return self.post(f"/api/v1/market-feeds/{feed_id}/{path}/batch", payload)
        except Exception:
            logging.getLogger(__name__).warning(
                "HTTP ingestion failed for %s batch of %s items via %s transport",
                path,
                len(items),
                self.ingestion_transport,
            )
            raise
