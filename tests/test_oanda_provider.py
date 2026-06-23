from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from goldie_collector.__main__ import CollectorSupervisor, InstrumentWorker
from goldie_collector.client import GoldieApiClient
from goldie_collector.provider import (
    OandaApiError,
    OandaConfigurationError,
    OandaProvider,
)
from goldie_collector.settings import CollectorSettings


def test_oanda_price_message_is_normalized() -> None:
    quote = OandaProvider.parse_price_message(
        {
            "type": "PRICE",
            "status": "tradeable",
            "time": "2026-06-12T10:15:30.123456789Z",
            "bids": [{"price": "4321.100"}],
            "asks": [{"price": "4321.250"}],
        }
    )
    assert quote is not None
    assert quote.bid == Decimal("4321.100")
    assert quote.ask == Decimal("4321.250")
    assert quote.observed_at.tzinfo is not None


def test_non_tradeable_oanda_price_is_ignored() -> None:
    assert (
        OandaProvider.parse_price_message(
            {
                "type": "PRICE",
                "status": "non-tradeable",
                "time": "2026-06-12T10:15:30Z",
                "bids": [{"price": "4321.100"}],
                "asks": [{"price": "4321.250"}],
            }
        )
        is None
    )


def test_only_complete_midpoint_candles_are_normalized() -> None:
    candle = OandaProvider.parse_candle(
        {
            "complete": True,
            "time": "2026-06-12T10:15:00Z",
            "volume": 42,
            "mid": {
                "o": "4321.10",
                "h": "4321.50",
                "l": "4320.90",
                "c": "4321.40",
            },
        }
    )
    assert candle is not None
    assert candle.close == Decimal("4321.40")
    assert OandaProvider.parse_candle({"complete": False}) is None


def test_weekend_is_reported_as_market_closed() -> None:
    provider = object.__new__(OandaProvider)
    assert provider.market_is_closed(datetime(2026, 6, 13, 12, tzinfo=UTC))
    assert not provider.market_is_closed(datetime(2026, 6, 12, 12, tzinfo=UTC))


def test_registration_404_explains_wrong_service_url(monkeypatch) -> None:
    response = SimpleNamespace(
        status_code=404,
        url="https://goldie-web.example/api/v1/market-feeds/register",
    )

    def raise_for_status() -> None:
        import requests

        raise requests.HTTPError("404")

    response.raise_for_status = raise_for_status
    monkeypatch.setattr(
        "goldie_collector.client.requests.post",
        lambda *args, **kwargs: response,
    )
    settings = SimpleNamespace(
        api_url="https://goldie-web.example",
        agent_token="test-token",
        request_timeout_seconds=20,
    )
    client = GoldieApiClient(settings)

    with pytest.raises(RuntimeError, match="not the Web service"):
        client.post("/api/v1/market-feeds/register", {})


def test_oanda_error_includes_response_message(monkeypatch) -> None:
    response = SimpleNamespace(
        status_code=403,
        text='{"errorMessage":"Insufficient authorization to perform request."}',
        headers={"RequestID": "request-123"},
        json=lambda: {
            "errorMessage": "Insufficient authorization to perform request."
        },
    )

    def raise_for_status() -> None:
        import requests

        raise requests.HTTPError("403")

    response.raise_for_status = raise_for_status
    monkeypatch.setattr(
        "goldie_collector.provider.requests.get",
        lambda *args, **kwargs: response,
    )
    provider = object.__new__(OandaProvider)
    provider.settings = SimpleNamespace(
        oanda_rest_url="https://api-fxpractice.oanda.com",
        request_timeout_seconds=20,
    )
    provider.headers = {"Authorization": "Bearer hidden"}

    with pytest.raises(
        OandaApiError,
        match="Insufficient authorization.*practice/live",
    ):
        provider._get("/v3/accounts/example/instruments")


def test_account_access_rejects_account_not_visible_to_token(monkeypatch) -> None:
    provider = object.__new__(OandaProvider)
    provider.settings = SimpleNamespace(oanda_account_id="101-001-wrong-002")
    monkeypatch.setattr(
        provider,
        "_get",
        lambda path: {"accounts": [{"id": "101-001-correct-001"}]},
    )

    with pytest.raises(OandaConfigurationError, match="101-001-correct-001"):
        provider.validate_account_access()


def test_instrument_403_explains_account_is_not_api_tradable(monkeypatch) -> None:
    provider = object.__new__(OandaProvider)
    provider.settings = SimpleNamespace(
        oanda_account_id="101-001-visible-002",
        provider_symbol="XAU_USD",
    )
    monkeypatch.setattr(provider, "validate_account_access", lambda: None)
    monkeypatch.setattr(
        provider,
        "_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OandaApiError("forbidden", status_code=403)
        ),
    )

    with pytest.raises(OandaConfigurationError, match="may not be API-tradable"):
        provider.validate_instrument()


def test_missing_instrument_reports_available_instruments(monkeypatch) -> None:
    provider = object.__new__(OandaProvider)
    provider.settings = SimpleNamespace(
        oanda_account_id="101-001-visible-002",
        provider_symbol="XAU_USD",
    )
    monkeypatch.setattr(provider, "validate_account_access", lambda: None)
    monkeypatch.setattr(
        provider,
        "_get",
        lambda *args, **kwargs: {
            "instruments": [
                {"name": "EUR_USD", "displayName": "EUR/USD"},
                {"name": "XAU_EUR", "displayName": "Gold/EUR"},
            ]
        },
    )

    with pytest.raises(
        OandaConfigurationError,
        match="Available instruments.*EUR_USD, XAU_EUR",
    ):
        provider.validate_instrument()


def test_oanda_html_error_body_is_truncated(monkeypatch) -> None:
    response = SimpleNamespace(
        status_code=522,
        text="<html>" + "x" * 5000 + "</html>",
        headers={},
        json=lambda: (_ for _ in ()).throw(ValueError()),
    )

    def raise_for_status() -> None:
        import requests

        raise requests.HTTPError("522")

    response.raise_for_status = raise_for_status
    monkeypatch.setattr(
        "goldie_collector.provider.requests.get",
        lambda *args, **kwargs: response,
    )
    provider = object.__new__(OandaProvider)
    provider.settings = SimpleNamespace(
        oanda_rest_url="https://api-fxpractice.oanda.com",
        request_timeout_seconds=20,
    )
    provider.headers = {"Authorization": "Bearer hidden"}

    with pytest.raises(OandaApiError) as error:
        provider._get("/v3/accounts")

    assert len(str(error.value)) < 700


def test_collector_settings_parse_multiple_instruments() -> None:
    settings = CollectorSettings(
        api_url="https://goldie-api.example",
        agent_token="agent-token",
        oanda_api_token="oanda-token",
        oanda_account_id="practice-account",
        instruments="eur_usd, USD_JPY,EUR_USD",
    )

    assert settings.instrument_symbols == ["EUR_USD", "USD_JPY"]
    usd_jpy = settings.for_instrument("USD_JPY")
    assert usd_jpy.provider_symbol == "USD_JPY"
    assert usd_jpy.canonical_symbol == "USDJPY"
    assert usd_jpy.agent_name.endswith("-usd_jpy")


def test_collector_settings_reject_invalid_instrument() -> None:
    with pytest.raises(ValueError, match="Invalid OANDA instrument"):
        CollectorSettings(
            api_url="https://goldie-api.example",
            agent_token="agent-token",
            oanda_api_token="oanda-token",
            oanda_account_id="practice-account",
            instruments="EURUSD",
        )


def test_remote_collector_settings_are_validated_and_coerced() -> None:
    base = CollectorSettings(
        api_url="https://goldie-api.example",
        agent_token="agent-token",
        oanda_api_token="oanda-token",
        oanda_account_id="practice-account",
    )
    supervisor = object.__new__(CollectorSupervisor)
    supervisor.base_settings = base

    settings = supervisor.effective_settings(
        "GBP_USD",
        {
            "quote_interval_seconds": "7.5",
            "candle_poll_seconds": "20",
            "heartbeat_seconds": "15",
            "backfill_days": "14",
            "backfill_batch_size": "500",
            "configuration_retry_seconds": "120",
        },
        {},
    )

    assert settings.provider_symbol == "GBP_USD"
    assert settings.quote_interval_seconds == 7.5
    assert isinstance(settings.quote_interval_seconds, float)
    assert settings.backfill_days == 14
    assert isinstance(settings.backfill_days, int)


def test_instrument_worker_starts_stream_before_candle_catchup(monkeypatch) -> None:
    events: list[str] = []
    worker_ref = {}

    class FakeClient:
        def __init__(self, _settings):
            pass

        def set_collector_id(self, _collector_id):
            pass

        def register(self, _settings):
            events.append("register")
            return datetime.now(UTC) - timedelta(days=1)

        def instrument(self, _instrument):
            events.append("instrument")

        def heartbeat(self, status, _details):
            events.append(f"heartbeat:{status}")

        def quotes(self, _quotes):
            pass

        def candles(self, _candles):
            events.append("send-candles")
            return {"count": 0, "duplicates": 0}

        def flush_due(self):
            pass

        def flush_quotes(self):
            pass

    class FakeProvider:
        stream_error = None

        def __init__(self, _settings):
            self.started = False

        def validate_instrument(self):
            return SimpleNamespace()

        def start(self):
            self.started = True
            events.append("stream-start")

        def market_is_closed(self):
            return False

        def latest_quote(self):
            return None

        def candles(self, _start, _end):
            events.append(f"candles-started:{self.started}")
            worker_ref["worker"].stop_event.set()
            return []

        def close(self):
            events.append("close")

    monkeypatch.setattr("goldie_collector.__main__.GoldieApiClient", FakeClient)
    monkeypatch.setattr("goldie_collector.__main__.OandaProvider", FakeProvider)
    settings = CollectorSettings(
        api_url="https://goldie-api.example",
        agent_token="agent-token",
        oanda_api_token="oanda-token",
        oanda_account_id="practice-account",
    )
    worker = InstrumentWorker(settings, lambda *_args: None)
    worker_ref["worker"] = worker

    worker._run()

    assert events.index("stream-start") < events.index("candles-started:True")
    assert "heartbeat:ONLINE" in events
