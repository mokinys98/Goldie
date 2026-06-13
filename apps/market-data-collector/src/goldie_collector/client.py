import uuid
from datetime import UTC, datetime
from typing import Any

import requests

from .models import Candle, Instrument, Quote
from .settings import CollectorSettings


class GoldieApiClient:
    def __init__(self, settings: CollectorSettings) -> None:
        self.base_url = settings.api_url.rstrip("/")
        self.headers = {"X-Agent-Token": settings.agent_token}
        self.timeout = settings.request_timeout_seconds
        self.feed_id: uuid.UUID | None = None
        self.agent_id: uuid.UUID | None = None

    def post(self, path: str, payload: dict[str, Any]) -> dict:
        response = requests.post(
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
                "details": {"read_only": True, "runtime": "railway"},
            },
        )
        self.feed_id = uuid.UUID(result["feed"]["id"])
        self.agent_id = uuid.UUID(result["agent"]["id"])
        value = result.get("latest_candle_at")
        if not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

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
        feed_id, agent_id = self._identity()
        self.post(
            f"/api/v1/market-feeds/{feed_id}/quotes/batch",
            {
                "agent_id": agent_id,
                "quotes": [quote.model_dump(mode="json") for quote in quotes],
            },
        )

    def candles(self, candles: list[Candle]) -> dict:
        if not candles:
            return {"accepted": True, "count": 0, "duplicates": 0}
        feed_id, agent_id = self._identity()
        return self.post(
            f"/api/v1/market-feeds/{feed_id}/candles/batch",
            {
                "agent_id": agent_id,
                "candles": [candle.model_dump(mode="json") for candle in candles],
            },
        )
