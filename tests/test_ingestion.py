import os
import uuid
from datetime import UTC, datetime

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from goldie_api.db import Base, engine
from goldie_api.ingestion import process_quote_batch
from goldie_api.models import Agent, IngestionEvent, MarketFeed, MarketTick
from goldie_api.schemas import FeedQuoteBatch
from goldie_api.db import SessionLocal
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
