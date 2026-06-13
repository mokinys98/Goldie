import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

import requests

from .models import Candle, Instrument, Quote
from .settings import CollectorSettings

logger = logging.getLogger(__name__)


class OandaApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class OandaConfigurationError(RuntimeError):
    pass


class MarketDataProvider(Protocol):
    def validate_instrument(self) -> Instrument: ...
    def start(self) -> None: ...
    def close(self) -> None: ...
    def latest_quote(self) -> Quote | None: ...
    def candles(self, start: datetime, end: datetime) -> list[Candle]: ...
    def market_is_closed(self, now: datetime | None = None) -> bool: ...


class OandaProvider:
    def __init__(self, settings: CollectorSettings) -> None:
        self.settings = settings
        self.headers = {"Authorization": f"Bearer {settings.oanda_api_token}"}
        self._latest_quote: Quote | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream_response: requests.Response | None = None
        self.stream_error: Exception | None = None

    def _get(self, path: str, **params) -> dict:
        response = requests.get(
            f"{self.settings.oanda_rest_url.rstrip('/')}{path}",
            params=params,
            headers=self.headers,
            timeout=self.settings.request_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            message = payload.get("errorMessage")
            if not message:
                message = " ".join(response.text.split())
                if len(message) > 500:
                    message = f"{message[:500]}..."
            request_id = response.headers.get("RequestID")
            detail = f": {message}" if message else ""
            request_detail = f" (RequestID: {request_id})" if request_id else ""
            hint = ""
            if response.status_code == 403:
                hint = (
                    " Verify that the token can access this account and that "
                    "practice/live URLs match the account environment."
                )
            raise OandaApiError(
                f"OANDA returned HTTP {response.status_code} for {path}"
                f"{detail}{request_detail}.{hint}",
                status_code=response.status_code,
            ) from exc
        return response.json()

    def validate_account_access(self) -> None:
        payload = self._get("/v3/accounts")
        authorized_ids = {
            str(account.get("id"))
            for account in payload.get("accounts", [])
            if account.get("id")
        }
        if self.settings.oanda_account_id not in authorized_ids:
            visible = ", ".join(sorted(authorized_ids)) or "none"
            raise OandaConfigurationError(
                "GOLDIE_OANDA_ACCOUNT_ID is not authorized by the configured "
                f"token/environment. Authorized account IDs: {visible}"
            )

    def validate_instrument(self) -> Instrument:
        self.validate_account_access()
        try:
            payload = self._get(
                f"/v3/accounts/{self.settings.oanda_account_id}/instruments",
            )
        except OandaApiError as exc:
            if exc.status_code == 403:
                raise OandaConfigurationError(
                    "The token can see GOLDIE_OANDA_ACCOUNT_ID, but OANDA does "
                    "not permit account-scoped instrument/pricing access. The "
                    "account may not be API-tradable. Verify the account status "
                    "with OANDA support and provide the RequestID from the "
                    "preceding error."
                ) from exc
            raise
        rows = payload.get("instruments", [])
        item = next(
            (
                instrument
                for instrument in rows
                if instrument.get("name") == self.settings.provider_symbol
            ),
            None,
        )
        if item is None:
            available = sorted(
                str(instrument["name"])
                for instrument in rows
                if instrument.get("name")
            )
            available_text = ", ".join(available[:50]) if available else "none"
            raise OandaConfigurationError(
                f"{self.settings.provider_symbol} is not tradeable for this OANDA "
                f"account. Available instruments (first 50): {available_text}"
            )
        return Instrument(
            canonical_symbol=self.settings.canonical_symbol,
            provider_symbol=item["name"],
            display_precision=int(item["displayPrecision"]),
            pip_location=int(item["pipLocation"]),
            minimum_trade_size=Decimal(item["minimumTradeSize"])
            if item.get("minimumTradeSize")
            else None,
            trade_units_precision=int(item["tradeUnitsPrecision"])
            if item.get("tradeUnitsPrecision") is not None
            else None,
            margin_rate=Decimal(item["marginRate"]) if item.get("marginRate") else None,
            provider_metadata={
                "type": item.get("type"),
                "maximum_order_units": item.get("maximumOrderUnits"),
                "maximum_position_size": item.get("maximumPositionSize"),
            },
        )

    @staticmethod
    def parse_price_message(message: dict) -> Quote | None:
        if message.get("type") != "PRICE" or message.get("status") != "tradeable":
            return None
        bids = message.get("bids") or []
        asks = message.get("asks") or []
        if not bids or not asks:
            return None
        return Quote(
            observed_at=datetime.fromisoformat(message["time"].replace("Z", "+00:00")),
            bid=Decimal(bids[0]["price"]),
            ask=Decimal(asks[0]["price"]),
        )

    @staticmethod
    def parse_candle(item: dict) -> Candle | None:
        midpoint = item.get("mid")
        if not item.get("complete") or midpoint is None:
            return None
        return Candle(
            opened_at=datetime.fromisoformat(item["time"].replace("Z", "+00:00")),
            open=Decimal(midpoint["o"]),
            high=Decimal(midpoint["h"]),
            low=Decimal(midpoint["l"]),
            close=Decimal(midpoint["c"]),
            volume=int(item.get("volume", 0)),
            complete=True,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.stream_error = None
        self._thread = threading.Thread(target=self._stream, daemon=True)
        self._thread.start()

    def _stream(self) -> None:
        try:
            with requests.get(
                (
                    f"{self.settings.oanda_stream_url.rstrip('/')}/v3/accounts/"
                    f"{self.settings.oanda_account_id}/pricing/stream"
                ),
                params={"instruments": self.settings.provider_symbol, "snapshot": "true"},
                headers=self.headers,
                timeout=(self.settings.request_timeout_seconds, 90),
                stream=True,
            ) as response:
                self._stream_response = response
                response.raise_for_status()
                for line in response.iter_lines():
                    if self._stop.is_set():
                        return
                    if not line:
                        continue
                    message = json.loads(line)
                    quote = self.parse_price_message(message)
                    if quote is not None:
                        with self._lock:
                            self._latest_quote = quote
        except Exception as exc:
            if not self._stop.is_set():
                logger.exception("OANDA pricing stream failed")
                self.stream_error = exc
        finally:
            self._stream_response = None

    def close(self) -> None:
        self._stop.set()
        if self._stream_response is not None:
            self._stream_response.close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def latest_quote(self) -> Quote | None:
        with self._lock:
            return self._latest_quote.model_copy() if self._latest_quote else None

    def candles(self, start: datetime, end: datetime) -> list[Candle]:
        current = start.astimezone(UTC).replace(second=0, microsecond=0)
        boundary = end.astimezone(UTC).replace(second=0, microsecond=0)
        result: list[Candle] = []
        while current < boundary:
            payload = self._get(
                f"/v3/instruments/{self.settings.provider_symbol}/candles",
                price="M",
                granularity="M1",
                **{
                    "from": current.isoformat().replace("+00:00", "Z"),
                    "count": 5000,
                    "includeFirst": "true",
                },
            )
            batch = [
                candle
                for item in payload.get("candles", [])
                if (candle := self.parse_candle(item)) is not None
                and candle.opened_at < boundary
            ]
            if not batch:
                break
            result.extend(batch)
            next_start = batch[-1].opened_at + timedelta(minutes=1)
            if next_start <= current:
                break
            current = next_start
            if len(batch) < 5000:
                break
        return result

    def market_is_closed(self, now: datetime | None = None) -> bool:
        value = (now or datetime.now(UTC)).astimezone(UTC)
        weekday = value.weekday()
        return weekday == 5 or (weekday == 4 and value.hour >= 22) or (
            weekday == 6 and value.hour < 22
        )
