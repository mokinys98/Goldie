import os
import uuid
from datetime import UTC, datetime

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from goldie_api.db import Base, SessionLocal, engine
from goldie_api.ingestion import process_candle_batch, process_quote_batch
from goldie_api.models import Agent, Candle, IngestionEvent, MarketFeed, MarketTick
from goldie_api.schemas import FeedCandleBatch, FeedQuoteBatch
from sqlalchemy import func, select


def registered_feed() -> tuple[uuid.UUID, uuid.UUID]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        feed = MarketFeed(
            provider="oanda",
            environment="practice",
            canonical_symbol="EURUSD",
            provider_symbol="EUR_USD",
        )
        db.add(feed)
        db.flush()
        agent = Agent(
            market_feed_id=feed.id,
            name="ingestion-test",
            adapter="oanda",
        )
        db.add(agent)
        db.commit()
        return feed.id, agent.id


def test_quote_event_is_idempotent() -> None:
    feed_id, agent_id = registered_feed()
    event_id = uuid.uuid4()
    payload = FeedQuoteBatch.model_validate(
        {
            "event_id": event_id,
            "agent_id": agent_id,
            "sent_at": datetime.now(UTC),
            "quotes": [
                {
                    "observed_at": datetime.now(UTC),
                    "bid": "1.08",
                    "ask": "1.081",
                }
            ],
        }
    )

    first, first_event = process_quote_batch(feed_id, payload)
    second, second_event = process_quote_batch(feed_id, payload)

    assert first["count"] == 1
    assert first_event["event_type"] == "market.quote"
    assert second["duplicate_event"] is True
    assert second_event == {}
    with SessionLocal() as db:
        assert db.scalar(select(func.count(MarketTick.id))) == 1
        assert db.scalar(select(func.count(IngestionEvent.event_id))) == 1


def test_paused_feed_drops_quotes_and_candles_without_persistence() -> None:
    feed_id, agent_id = registered_feed()
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    with SessionLocal() as db:
        feed = db.get(MarketFeed, feed_id)
        feed.status = "PAUSED"
        feed.paused_at = now
        db.commit()

    quote_result, quote_event = process_quote_batch(
        feed_id,
        FeedQuoteBatch.model_validate(
            {
                "event_id": uuid.uuid4(),
                "agent_id": agent_id,
                "sent_at": now,
                "quotes": [{"observed_at": now, "bid": "1.08", "ask": "1.081"}],
            }
        ),
    )
    candle_result, candle_event = process_candle_batch(
        feed_id,
        FeedCandleBatch.model_validate(
            {
                "event_id": uuid.uuid4(),
                "agent_id": agent_id,
                "sent_at": now,
                "candles": [
                    {
                        "opened_at": now,
                        "open": "1.08",
                        "high": "1.09",
                        "low": "1.07",
                        "close": "1.085",
                        "volume": 10,
                        "complete": True,
                    }
                ],
            }
        ),
    )

    assert quote_result["reason"] == "FEED_PAUSED"
    assert candle_result["reason"] == "FEED_PAUSED"
    assert quote_event == candle_event == {}
    with SessionLocal() as db:
        assert db.scalar(select(func.count(MarketTick.id))) == 0
        assert db.scalar(select(func.count(Candle.id))) == 0
        assert db.scalar(select(func.count(IngestionEvent.event_id))) == 0
