import uuid
from datetime import UTC, datetime

from goldie_collector.client import GoldieApiClient
from goldie_collector.models import Quote
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
