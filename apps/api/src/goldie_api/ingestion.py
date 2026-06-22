import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from goldie_domain import BotConfiguration, get_strategy
from sqlalchemy import and_, desc, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import (
    Agent,
    Bot,
    Candle,
    ConfigVersion,
    IngestionEvent,
    InstrumentSpecification,
    MarketFeed,
    MarketTick,
    Run,
    Signal,
    SignalOutcome,
)
from .realtime import invalidate_collector_overview
from .schemas import FeedCandleBatch, FeedQuoteBatch
from .services import as_utc, evaluate_signal_from_context
from .shadow import create_signal_outcome, evaluate_open_outcome


def _feed_and_agent(
    db: Session,
    feed_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> tuple[MarketFeed, Agent]:
    feed = db.get(MarketFeed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Market feed not found")
    agent = db.get(Agent, agent_id)
    if agent is None or agent.market_feed_id != feed_id:
        raise HTTPException(status_code=403, detail="Agent and market feed do not match")
    return feed, agent


def _existing_result(db: Session, event_id: uuid.UUID) -> dict | None:
    event = db.get(IngestionEvent, event_id)
    if event is None:
        return None
    return {**event.result, "duplicate_event": True}


def _claim_event(
    db: Session,
    *,
    event_id: uuid.UUID,
    event_type: str,
    feed_id: uuid.UUID,
    agent_id: uuid.UUID,
    collector_id: uuid.UUID | None,
    sent_at: datetime,
) -> bool:
    dialect = db.get_bind().dialect.name
    insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
    statement = (
        insert(IngestionEvent)
        .values(
            event_id=event_id,
            event_type=event_type,
            market_feed_id=feed_id,
            agent_id=agent_id,
            collector_id=collector_id,
            sent_at=sent_at,
            result={},
        )
        .on_conflict_do_nothing(index_elements=[IngestionEvent.event_id])
        .returning(IngestionEvent.event_id)
    )
    return db.scalar(statement) is not None


def _complete_event(db: Session, event_id: uuid.UUID, result: dict) -> None:
    db.execute(
        update(IngestionEvent)
        .where(IngestionEvent.event_id == event_id)
        .values(result=result)
    )


def _paused_result(event_id: uuid.UUID, item_count: int) -> tuple[dict, dict]:
    return (
        {
            "accepted": False,
            "dropped": True,
            "reason": "FEED_PAUSED",
            "count": 0,
            "dropped_count": item_count,
            "event_id": str(event_id),
        },
        {},
    )


def ingest_quote_batch(
    db: Session,
    feed_id: uuid.UUID,
    payload: FeedQuoteBatch,
) -> tuple[dict, dict]:
    event_id = payload.event_id or uuid.uuid4()
    existing = _existing_result(db, event_id)
    if existing is not None:
        return existing, {}
    feed, _ = _feed_and_agent(db, feed_id, payload.agent_id)
    if feed.status == "PAUSED" or feed.paused_at is not None:
        return _paused_result(event_id, len(payload.quotes))
    sent_at = (payload.sent_at or datetime.now(UTC)).astimezone(UTC)
    claimed = _claim_event(
        db,
        event_id=event_id,
        event_type="quote_batch",
        feed_id=feed.id,
        agent_id=payload.agent_id,
        collector_id=payload.collector_id,
        sent_at=sent_at,
    )
    if not claimed:
        return _existing_result(db, event_id) or {"duplicate_event": True}, {}
    runtime_rows = list(
        db.execute(
            select(Bot, SignalOutcome, ConfigVersion)
            .join(SignalOutcome, SignalOutcome.bot_id == Bot.id)
            .join(Run, Run.id == SignalOutcome.run_id)
            .join(ConfigVersion, ConfigVersion.id == SignalOutcome.config_version_id)
            .where(
                Bot.market_feed_id == feed.id,
                Bot.archived_at.is_(None),
                Bot.state == "MONITORING",
                SignalOutcome.status == "OPEN",
                Run.status == "ACTIVE",
                ConfigVersion.status == "ACTIVE",
            )
        )
    )
    spec = db.scalar(
        select(InstrumentSpecification)
        .where(InstrumentSpecification.market_feed_id == feed.id)
        .order_by(desc(InstrumentSpecification.updated_at))
    )
    for quote in payload.quotes:
        if quote.ask < quote.bid:
            raise HTTPException(status_code=422, detail="Ask cannot be lower than bid")
        tick = MarketTick(
            market_feed_id=feed.id,
            agent_id=payload.agent_id,
            symbol=feed.canonical_symbol,
            observed_at=quote.observed_at.astimezone(UTC),
            received_at=datetime.now(UTC),
            source=feed.provider,
            bid=quote.bid,
            ask=quote.ask,
        )
        db.add(tick)
        if spec is not None:
            for bot, outcome, config in runtime_rows:
                evaluate_open_outcome(
                    db,
                    bot,
                    tick,
                    loaded_outcome=outcome,
                    loaded_config=config,
                    loaded_spec=spec,
                )
    result = {
        "accepted": True,
        "count": len(payload.quotes),
        "event_id": str(event_id),
    }
    _complete_event(db, event_id, result)
    latest = payload.quotes[-1]
    event = {
        "event_type": "market.quote",
        "occurred_at": datetime.now(UTC).isoformat(),
        "market_feed_id": str(feed.id),
        "bot_instance_ids": [str(bot.id) for bot, _, _ in runtime_rows],
        "data": {
            "symbol": feed.canonical_symbol,
            "observed_at": latest.observed_at.isoformat(),
            "bid": str(latest.bid),
            "ask": str(latest.ask),
        },
    }
    return result, event


def ingest_candle_batch(
    db: Session,
    feed_id: uuid.UUID,
    payload: FeedCandleBatch,
) -> tuple[dict, dict]:
    event_id = payload.event_id or uuid.uuid4()
    existing = _existing_result(db, event_id)
    if existing is not None:
        return existing, {}
    feed, _ = _feed_and_agent(db, feed_id, payload.agent_id)
    if feed.status == "PAUSED" or feed.paused_at is not None:
        return _paused_result(event_id, len(payload.candles))
    sent_at = (payload.sent_at or datetime.now(UTC)).astimezone(UTC)
    claimed = _claim_event(
        db,
        event_id=event_id,
        event_type="candle_batch",
        feed_id=feed.id,
        agent_id=payload.agent_id,
        collector_id=payload.collector_id,
        sent_at=sent_at,
    )
    if not claimed:
        return _existing_result(db, event_id) or {"duplicate_event": True}, {}
    complete_candles = [candle for candle in payload.candles if candle.complete]
    values_by_opened_at: dict[datetime, dict] = {}
    received_at = datetime.now(UTC)
    for candle in complete_candles:
        opened_at = candle.opened_at.astimezone(UTC)
        if candle.high < max(candle.open, candle.close) or candle.low > min(
            candle.open, candle.close
        ):
            raise HTTPException(status_code=422, detail="Invalid candle OHLC values")
        values_by_opened_at.setdefault(
            opened_at,
            {
                "id": uuid.uuid4(),
                "market_feed_id": feed.id,
                "agent_id": payload.agent_id,
                "symbol": feed.canonical_symbol,
                "timeframe": "M1",
                "opened_at": opened_at,
                "received_at": received_at,
                "source": feed.provider,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "tick_volume": candle.volume,
                "is_complete": True,
            },
        )
    values = list(values_by_opened_at.values())
    accepted = 0
    if values:
        dialect = db.get_bind().dialect.name
        insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(Candle).values(values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                Candle.market_feed_id,
                Candle.symbol,
                Candle.timeframe,
                Candle.opened_at,
            ]
        ).returning(Candle.id)
        accepted = len(list(db.scalars(statement)))
    signal_ids: list[str] = []
    if accepted:
        runtime_rows = list(
            db.execute(
                select(Bot, ConfigVersion, Run)
                .join(ConfigVersion, ConfigVersion.id == Bot.active_config_version_id)
                .join(
                    Run,
                    and_(
                        Run.bot_id == Bot.id,
                        Run.config_version_id == ConfigVersion.id,
                    ),
                )
                .where(
                    Bot.market_feed_id == feed.id,
                    Bot.archived_at.is_(None),
                    Bot.state == "MONITORING",
                    ConfigVersion.status == "ACTIVE",
                    Run.status == "ACTIVE",
                )
            )
        )
        tick = db.scalar(
            select(MarketTick)
            .where(MarketTick.market_feed_id == feed.id)
            .order_by(desc(MarketTick.observed_at))
        )
        spec = db.scalar(
            select(InstrumentSpecification)
            .where(InstrumentSpecification.market_feed_id == feed.id)
            .order_by(desc(InstrumentSpecification.updated_at))
        )
        prepared: list[tuple[Bot, ConfigVersion, Run, str, int]] = []
        max_required: dict[str, int] = {}
        for bot, config_row, run in runtime_rows:
            config = BotConfiguration.model_validate(config_row.config)
            strategy = get_strategy(config.strategy.name)
            required = strategy.required_candles(
                strategy.parameters_model.model_validate(config.strategy.parameters)
            )
            timeframe = config.market.timeframe
            prepared.append((bot, config_row, run, timeframe, required))
            max_required[timeframe] = max(max_required.get(timeframe, 0), required)
        candles_by_timeframe = {
            timeframe: list(
                db.scalars(
                    select(Candle)
                    .where(
                        Candle.market_feed_id == feed.id,
                        Candle.symbol == feed.canonical_symbol,
                        Candle.timeframe == timeframe,
                        Candle.is_complete.is_(True),
                    )
                    .order_by(desc(Candle.opened_at))
                    .limit(required)
                )
            )
            for timeframe, required in max_required.items()
        }
        latest_times = {
            max(as_utc(row.opened_at) for row in rows)
            for rows in candles_by_timeframe.values()
            if rows
        }
        bot_ids = [bot.id for bot, _, _, _, _ in prepared]
        duplicates = {
            (signal.bot_id, signal.run_id, as_utc(signal.observed_at)): signal
            for signal in db.scalars(
                select(Signal).where(
                    Signal.bot_id.in_(bot_ids),
                    Signal.observed_at.in_(latest_times),
                )
            )
        } if bot_ids and latest_times else {}
        bots = [bot for bot, _, _, _, _ in prepared]
        for bot, config_row, run, timeframe, required in prepared:
            rows = candles_by_timeframe.get(timeframe, [])[:required]
            if not rows or tick is None or spec is None:
                continue
            latest_at = max(as_utc(row.opened_at) for row in rows)
            signal = duplicates.get((bot.id, run.id, latest_at))
            created = False
            if signal is None:
                signal, created = evaluate_signal_from_context(
                    db,
                    bot=bot,
                    config_row=config_row,
                    active_run=run,
                    tick=tick,
                    spec=spec,
                    rows=rows,
                )
            if signal is not None:
                signal_ids.append(str(signal.id))
            if created and signal is not None:
                create_signal_outcome(db, signal, tick)
    result = {
        "accepted": True,
        "count": accepted,
        "duplicates": len(complete_candles) - accepted,
        "signal_ids": signal_ids,
        "event_id": str(event_id),
    }
    _complete_event(db, event_id, result)
    event = {
        "event_type": "market.candle",
        "occurred_at": datetime.now(UTC).isoformat(),
        "market_feed_id": str(feed.id),
        "bot_instance_ids": [str(bot.id) for bot in bots] if accepted else [],
        "signal_ids": signal_ids,
    }
    return result, event


def process_quote_batch(feed_id: uuid.UUID, payload: FeedQuoteBatch) -> tuple[dict, dict]:
    with SessionLocal() as db:
        result, event = ingest_quote_batch(db, feed_id, payload)
        db.commit()
    invalidate_collector_overview()
    return result, event


def process_candle_batch(feed_id: uuid.UUID, payload: FeedCandleBatch) -> tuple[dict, dict]:
    with SessionLocal() as db:
        result, event = ingest_candle_batch(db, feed_id, payload)
        db.commit()
    invalidate_collector_overview()
    return result, event
