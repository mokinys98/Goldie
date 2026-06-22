import uuid
from datetime import UTC, datetime
from decimal import Decimal

from goldie_collector.client import GoldieApiClient
from goldie_collector.models import Candle, Quote
from goldie_collector.settings import CollectorSettings
from redis.exceptions import ConnectionError


def settings() -> CollectorSettings:
    return CollectorSettings(
        api_url="https://api.example",
        agent_token="token",
        ingestion_transport="redis",
        redis_url="redis://localhost:6379/0",
        oanda_api_token="oanda-token",
        oanda_account_id="account",
        instruments="EUR_USD",
    )


def test_redis_failure_falls_back_to_http_with_same_event_id(monkeypatch) -> None:
    client = GoldieApiClient(settings())
    client.feed_id = uuid.uuid4()
    client.agent_id = uuid.uuid4()
    sent: list[dict] = []

    class BrokenRedis:
        def xadd(self, *_args, **_kwargs):
            raise ConnectionError("offline")

    client.redis = BrokenRedis()

    def fake_post(_path: str, payload: dict) -> dict:
        sent.append(payload)
        return {"accepted": True, "count": 1}

    monkeypatch.setattr(client, "post", fake_post)
    client._send_batch(
        "quote_batch",
        [Quote(observed_at=datetime.now(UTC), bid="1.08", ask="1.081")],
    )

    assert len(sent) == 1
    assert sent[0]["event_id"]
    assert sent[0]["quotes"][0]["bid"] == "1.08"


def test_http_candle_ingestion_is_capped_at_small_batches(monkeypatch) -> None:
    collector_settings = settings().model_copy(
        update={"ingestion_transport": "http", "candle_batch_size": 500}
    )
    client = GoldieApiClient(collector_settings)
    client.feed_id = uuid.uuid4()
    client.agent_id = uuid.uuid4()
    batches: list[int] = []

    def fake_post(_path: str, payload: dict) -> dict:
        batches.append(len(payload["candles"]))
        return {"accepted": True, "count": len(payload["candles"]), "duplicates": 0}

    monkeypatch.setattr(client, "post", fake_post)
    candles = [
        Candle(
            opened_at=datetime(2026, 6, 22, 10, index, tzinfo=UTC),
            open=Decimal("1.0"),
            high=Decimal("1.1"),
            low=Decimal("0.9"),
            close=Decimal("1.0"),
            volume=100,
            complete=True,
        )
        for index in range(55)
    ]

    result = client.candles(candles)

    assert batches == [50, 5]
    assert result["count"] == 55
