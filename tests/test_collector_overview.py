import os
import uuid
from datetime import UTC, datetime

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"

from goldie_api.db import Base, SessionLocal, engine
from goldie_api.models import Candle, MarketFeed, MarketTick
from goldie_api.routers import collector
from sqlalchemy import event


class NoCache:
    def get(self, _key):
        return None

    def set(self, *_args, **_kwargs):
        return True


@pytest.mark.parametrize("feed_count", [1, 10, 20])
def test_overview_query_count_does_not_grow_with_feeds(monkeypatch, feed_count: int) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for index in range(feed_count):
            feed = MarketFeed(
                provider="oanda",
                environment="practice",
                canonical_symbol=f"PAIR{index}",
                provider_symbol=f"PAIR_{index}",
            )
            db.add(feed)
            db.flush()
            db.add(
                MarketTick(
                    id=uuid.uuid4(),
                    market_feed_id=feed.id,
                    symbol=feed.canonical_symbol,
                    observed_at=now,
                    received_at=now,
                    bid="1.0",
                    ask="1.1",
                )
            )
            db.add(
                Candle(
                    id=uuid.uuid4(),
                    market_feed_id=feed.id,
                    symbol=feed.canonical_symbol,
                    timeframe="M1",
                    opened_at=now.replace(hour=10),
                    received_at=now,
                    open="1.0",
                    high="1.1",
                    low="0.9",
                    close="1.0",
                    tick_volume=1,
                )
            )
            db.add(
                Candle(
                    id=uuid.uuid4(),
                    market_feed_id=feed.id,
                    symbol=feed.canonical_symbol,
                    timeframe="M1",
                    opened_at=now.replace(hour=11),
                    received_at=now,
                    open="1.0",
                    high="1.1",
                    low="0.9",
                    close="1.0",
                    tick_volume=1,
                )
            )
        db.commit()

        statements = 0

        def count_statement(*_args):
            nonlocal statements
            statements += 1

        monkeypatch.setattr(collector, "redis_client", lambda: NoCache())
        event.listen(engine, "before_cursor_execute", count_statement)
        try:
            result = collector.overview(db, None)
        finally:
            event.remove(engine, "before_cursor_execute", count_statement)

    assert len(result["feeds"]) == feed_count
    assert result["feeds"][0]["earliest_candle_at"] != result["feeds"][0]["latest_candle_at"]
    assert statements <= 9
