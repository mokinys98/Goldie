import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie-shadow.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from goldie_domain.config import DEFAULT_BOT_CONFIGURATION
from sqlalchemy import select
from sqlalchemy.orm import Session

from goldie_api.db import Base, engine
from goldie_api.models import (
    Agent,
    Bot,
    ConfigVersion,
    InstrumentSpecification,
    MarketFeed,
    MarketTick,
    Run,
    Signal,
    SignalOutcome,
)
from goldie_api.shadow import create_signal_outcome, evaluate_open_outcome

NOW = datetime(2026, 6, 11, 10, 0, tzinfo=UTC)


def test_shadow_lifecycle_enforces_one_open_position_and_is_idempotent() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        feed = MarketFeed(
            provider="oanda",
            environment="practice",
            canonical_symbol="XAUUSD",
            provider_symbol="XAU_USD",
            status="ONLINE",
            details={},
        )
        db.add(feed)
        db.flush()
        bot = Bot(name="Shadow lifecycle bot", mode="SHADOW", market_feed_id=feed.id)
        agent = Agent(
            market_feed_id=feed.id,
            name="test-oanda-collector",
            adapter="oanda",
            status="ONLINE",
            details={},
        )
        db.add_all([bot, agent])
        db.flush()
        config = ConfigVersion(
            bot_id=bot.id,
            version=1,
            status="ACTIVE",
            config=DEFAULT_BOT_CONFIGURATION,
        )
        db.add(config)
        db.flush()
        bot.active_config_version_id = config.id
        run = Run(
            bot_id=bot.id,
            config_version_id=config.id,
            mode="SHADOW",
        )
        db.add(run)
        db.flush()
        db.add(
            InstrumentSpecification(
                market_feed_id=feed.id,
                agent_id=agent.id,
                canonical_symbol="XAUUSD",
                provider_symbol="XAU_USD",
                display_precision=2,
                pip_location=-2,
                point=Decimal("0.01"),
                minimum_trade_size=Decimal("1"),
                trade_units_precision=0,
                margin_rate=Decimal("0.05"),
                source="oanda",
                provider_metadata={},
            )
        )
        tick = MarketTick(
            market_feed_id=feed.id,
            agent_id=agent.id,
            symbol="XAUUSD",
            observed_at=NOW,
            bid=Decimal("2350.00"),
            ask=Decimal("2350.20"),
        )
        first_signal = Signal(
            bot_id=bot.id,
            run_id=run.id,
            config_version_id=config.id,
            observed_at=NOW,
            signal="BUY",
            reason_code="MOMENTUM_UP",
            entry_price=Decimal("2350.20"),
            stop_loss=Decimal("2349.50"),
            take_profit=Decimal("2351.20"),
            inputs={},
        )
        db.add_all([tick, first_signal])
        db.flush()

        opened = create_signal_outcome(db, first_signal, tick)
        repeated = create_signal_outcome(db, first_signal, tick)
        assert opened is repeated
        assert opened.status == "OPEN"
        assert opened.volume == Decimal("35")
        opened.paused_duration_seconds = 120

        second_signal = Signal(
            bot_id=bot.id,
            run_id=run.id,
            config_version_id=config.id,
            observed_at=NOW + timedelta(seconds=1),
            signal="SELL",
            reason_code="MOMENTUM_DOWN",
            entry_price=Decimal("2350.00"),
            stop_loss=Decimal("2350.70"),
            take_profit=Decimal("2349.00"),
            inputs={},
        )
        db.add(second_signal)
        db.flush()
        skipped = create_signal_outcome(db, second_signal, tick)
        assert skipped.status == "SKIPPED"
        assert skipped.skip_reason == "OPEN_POSITION_EXISTS"

        closing_tick = MarketTick(
            market_feed_id=feed.id,
            agent_id=agent.id,
            symbol="XAUUSD",
            observed_at=NOW + timedelta(seconds=122),
            bid=Decimal("2351.30"),
            ask=Decimal("2351.50"),
        )
        db.add(closing_tick)
        db.flush()
        closed = evaluate_open_outcome(db, bot, closing_tick)
        assert closed is opened
        assert closed.status == "CLOSED"
        assert closed.result == "WIN"
        assert closed.close_reason == "TAKE_PROFIT"
        assert closed.duration_seconds == 2
        assert evaluate_open_outcome(db, bot, closing_tick) is None

        db.commit()
        outcomes = list(db.scalars(select(SignalOutcome).order_by(SignalOutcome.created_at)))
        assert [outcome.status for outcome in outcomes] == ["CLOSED", "SKIPPED"]
