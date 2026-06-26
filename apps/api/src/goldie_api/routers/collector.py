import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import require_agent_token
from ..models import (
    Agent,
    BacktestExperiment,
    BacktestTrade,
    Bot,
    Candle,
    CollectorCommand,
    CollectorConfiguration,
    CollectorInstance,
    CollectorInstrumentConfiguration,
    ConfigVersion,
    IngestionEvent,
    InstrumentSpecification,
    MarketFeed,
    MarketTick,
    OptimizationRun,
    OptimizationTrial,
    OptimizationTrialTrade,
    PaperAccount,
    Run,
    Signal,
    SignalOutcome,
    User,
)
from ..realtime import (
    OVERVIEW_CACHE_KEY,
    invalidate_collector_overview,
    publish_event_sync,
    redis_client,
)
from ..schemas import (
    CollectorCommandCreate,
    CollectorCommandUpdate,
    CollectorInstanceHeartbeat,
    CollectorInstanceRegister,
    CollectorInstrumentCreate,
    CollectorInstrumentSettingsUpdate,
    CollectorSettingsRead,
    CollectorSettingsUpdate,
    CollectorSettingsValues,
)
from ..security import get_current_user
from ..services import add_audit, as_utc
from ..settings import get_settings

router = APIRouter(prefix="/api/v1/collector", tags=["collector"])
ALLOWED_OVERRIDE_KEYS = {
    "quote_interval_seconds",
    "candle_poll_seconds",
    "heartbeat_seconds",
    "backfill_days",
    "backfill_batch_size",
    "configuration_retry_seconds",
}
ACTIVE_JOB_STATUSES = {"PENDING", "RUNNING", "CANCEL_REQUESTED"}


def feed_key(provider: str, environment: str, provider_symbol: str) -> tuple[str, str, str]:
    return provider, environment, provider_symbol


def instrument_key(row: CollectorInstrumentConfiguration) -> tuple[str, str, str]:
    return feed_key(row.provider, row.environment, row.provider_symbol)


def configuration_values(row: CollectorConfiguration) -> dict:
    return {
        key: getattr(row, key)
        for key in (
            "quote_interval_seconds",
            "candle_poll_seconds",
            "heartbeat_seconds",
            "backfill_days",
            "backfill_batch_size",
            "configuration_retry_seconds",
        )
    }


def get_configuration(db: Session) -> CollectorConfiguration:
    row = db.scalar(select(CollectorConfiguration).order_by(desc(CollectorConfiguration.version)))
    if row is None:
        values = CollectorSettingsValues()
        row = CollectorConfiguration(version=1, **values.model_dump())
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def serialize_configuration(row: CollectorConfiguration) -> dict:
    return jsonable_encoder(
        CollectorSettingsRead(
            id=row.id,
            version=row.version,
            updated_at=row.updated_at,
            globally_paused=row.globally_paused,
            **configuration_values(row),
        )
    )


def serialize_instrument(row: CollectorInstrumentConfiguration, feed: MarketFeed | None) -> dict:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "environment": row.environment,
        "provider_symbol": row.provider_symbol,
        "enabled": row.enabled,
        "overrides": row.overrides,
        "market_feed_id": str(feed.id) if feed else None,
        "canonical_symbol": feed.canonical_symbol if feed else row.provider_symbol.replace("_", ""),
        "feed_status": feed.status if feed else None,
        "resume_from_at": feed.resume_from_at.isoformat() if feed and feed.resume_from_at else None,
    }


def pause_feed(feed: MarketFeed, now: datetime) -> None:
    if feed.paused_at is None:
        feed.paused_at = now
    feed.status = "PAUSED"


def resume_feed(db: Session, feed: MarketFeed, now: datetime) -> None:
    paused_at = as_utc(feed.paused_at) if feed.paused_at else now
    paused_seconds = max(0, int((now - paused_at).total_seconds()))
    bot_ids = select(Bot.id).where(Bot.market_feed_id == feed.id)
    if paused_seconds:
        db.execute(
            update(SignalOutcome)
            .where(
                SignalOutcome.bot_id.in_(bot_ids),
                SignalOutcome.status == "OPEN",
            )
            .values(
                paused_duration_seconds=(
                    SignalOutcome.paused_duration_seconds + paused_seconds
                )
            )
        )
    next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    feed.paused_at = None
    feed.resume_from_at = next_minute
    feed.status = "REGISTERED"


def serialize_command(row: CollectorCommand) -> dict:
    return jsonable_encoder(
        {
            "id": row.id,
            "collector_instance_id": row.collector_instance_id,
            "market_feed_id": row.market_feed_id,
            "command": row.command,
            "status": row.status,
            "payload": row.payload,
            "progress": row.progress,
            "result": row.result,
            "error": row.error,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


def effective_instance_status(instance: CollectorInstance | None) -> str:
    if instance is None or instance.last_heartbeat_at is None:
        return "OFFLINE"
    if (datetime.now(UTC) - as_utc(instance.last_heartbeat_at)).total_seconds() > (
        get_settings().agent_offline_after_seconds
    ):
        return "OFFLINE"
    return instance.status


def latest_instance(db: Session) -> CollectorInstance | None:
    return db.scalar(select(CollectorInstance).order_by(desc(CollectorInstance.updated_at)))


def feed_or_404(db: Session, feed_id: uuid.UUID) -> MarketFeed:
    feed = db.get(MarketFeed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Market feed not found")
    return feed


def delete_count(db: Session, statement) -> int:
    result = db.execute(statement.execution_options(synchronize_session=False))
    return max(0, result.rowcount or 0)


def feed_summary(db: Session, feed: MarketFeed, now: datetime) -> dict:
    tick = db.scalar(
        select(MarketTick)
        .where(MarketTick.market_feed_id == feed.id)
        .order_by(desc(MarketTick.observed_at))
        .limit(1)
    )
    candle = db.scalar(
        select(Candle)
        .where(
            Candle.market_feed_id == feed.id,
            Candle.timeframe == "M1",
            Candle.is_complete.is_(True),
        )
        .order_by(desc(Candle.opened_at))
        .limit(1)
    )
    earliest_candle_at = db.scalar(
        select(func.min(Candle.opened_at)).where(
            Candle.market_feed_id == feed.id,
            Candle.timeframe == "M1",
            Candle.is_complete.is_(True),
        )
    )
    bots = db.scalar(
        select(func.count(Bot.id)).where(
            Bot.market_feed_id == feed.id,
            Bot.archived_at.is_(None),
        )
    ) or 0
    lag = None
    spread = None
    if tick:
        lag = max(0, int((now - as_utc(tick.observed_at)).total_seconds()))
        spread = tick.ask - tick.bid
    return jsonable_encoder(
        {
            "id": feed.id,
            "provider": feed.provider,
            "environment": feed.environment,
            "canonical_symbol": feed.canonical_symbol,
            "provider_symbol": feed.provider_symbol,
            "status": feed.status,
            "last_heartbeat_at": feed.last_heartbeat_at,
            "latest_tick": (
                {
                    "observed_at": tick.observed_at,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "spread": spread,
                }
                if tick
                else None
            ),
            "earliest_candle_at": earliest_candle_at,
            "latest_candle_at": candle.opened_at if candle else None,
            "data_lag_seconds": lag,
            "bot_count": bots,
        }
    )


def feed_summary_from_rows(
    feed: MarketFeed,
    tick: MarketTick | None,
    candle: Candle | None,
    earliest_candle_at: datetime | None,
    bots: int,
    now: datetime,
) -> dict:
    lag = None
    spread = None
    if tick:
        lag = max(0, int((now - as_utc(tick.observed_at)).total_seconds()))
        spread = tick.ask - tick.bid
    return jsonable_encoder(
        {
            "id": feed.id,
            "provider": feed.provider,
            "environment": feed.environment,
            "canonical_symbol": feed.canonical_symbol,
            "provider_symbol": feed.provider_symbol,
            "status": feed.status,
            "last_heartbeat_at": feed.last_heartbeat_at,
            "latest_tick": (
                {
                    "observed_at": tick.observed_at,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "spread": spread,
                }
                if tick
                else None
            ),
            "earliest_candle_at": earliest_candle_at,
            "latest_candle_at": candle.opened_at if candle else None,
            "data_lag_seconds": lag,
            "bot_count": bots,
        }
    )


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        cached = redis_client().get(OVERVIEW_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    feeds = list(db.scalars(select(MarketFeed).order_by(MarketFeed.provider_symbol)))
    feed_ids = [feed.id for feed in feeds]
    ticks: dict[uuid.UUID, MarketTick] = {}
    candles: dict[uuid.UUID, Candle] = {}
    earliest_candles: dict[uuid.UUID, datetime] = {}
    bot_counts: dict[uuid.UUID, int] = {}
    if feed_ids:
        tick_times = (
            select(
                MarketTick.market_feed_id.label("feed_id"),
                func.max(MarketTick.observed_at).label("observed_at"),
            )
            .where(MarketTick.market_feed_id.in_(feed_ids))
            .group_by(MarketTick.market_feed_id)
            .subquery()
        )
        ticks = {
            row.market_feed_id: row
            for row in db.scalars(
                select(MarketTick).join(
                    tick_times,
                    (MarketTick.market_feed_id == tick_times.c.feed_id)
                    & (MarketTick.observed_at == tick_times.c.observed_at),
                )
            )
        }
        candle_times = (
            select(
                Candle.market_feed_id.label("feed_id"),
                func.min(Candle.opened_at).label("earliest_opened_at"),
                func.max(Candle.opened_at).label("opened_at"),
            )
            .where(
                Candle.market_feed_id.in_(feed_ids),
                Candle.timeframe == "M1",
                Candle.is_complete.is_(True),
            )
            .group_by(Candle.market_feed_id)
            .subquery()
        )
        for candle, earliest_opened_at in db.execute(
            select(Candle, candle_times.c.earliest_opened_at).join(
                candle_times,
                (Candle.market_feed_id == candle_times.c.feed_id)
                & (Candle.opened_at == candle_times.c.opened_at),
            )
        ):
            candles[candle.market_feed_id] = candle
            earliest_candles[candle.market_feed_id] = earliest_opened_at
        bot_counts = {
            feed_id: count
            for feed_id, count in db.execute(
                select(Bot.market_feed_id, func.count(Bot.id))
                .where(
                    Bot.market_feed_id.in_(feed_ids),
                    Bot.archived_at.is_(None),
                )
                .group_by(Bot.market_feed_id)
            )
        }
    summaries = [
        feed_summary_from_rows(
            feed,
            ticks.get(feed.id),
            candles.get(feed.id),
            earliest_candles.get(feed.id),
            bot_counts.get(feed.id, 0),
            now,
        )
        for feed in feeds
    ]
    commands = list(
        db.scalars(select(CollectorCommand).order_by(desc(CollectorCommand.created_at)).limit(10))
    )
    instance = latest_instance(db)
    counts = {
        "online": sum(feed.status == "ONLINE" for feed in feeds),
        "paused": sum(feed.status == "PAUSED" for feed in feeds),
        "error": sum(feed.status in {"ERROR", "DEGRADED"} for feed in feeds),
        "market_closed": sum(feed.status == "MARKET_CLOSED" for feed in feeds),
        "ticks_24h": db.scalar(
            select(func.count(MarketTick.id)).where(MarketTick.received_at >= since)
        )
        or 0,
        "candles_24h": db.scalar(
            select(func.count(Candle.id)).where(Candle.received_at >= since)
        )
        or 0,
    }
    result = {
        "instance": (
            jsonable_encoder(
                {
                    "id": instance.id,
                    "name": instance.name,
                    "status": effective_instance_status(instance),
                    "reported_status": instance.status,
                    "last_heartbeat_at": instance.last_heartbeat_at,
                    "applied_config_version": instance.applied_config_version,
                    "details": instance.details,
                }
            )
            if instance
            else None
        ),
        "counts": counts,
        "feeds": summaries,
        "recent_commands": [serialize_command(command) for command in commands],
    }
    try:
        redis_client().set(OVERVIEW_CACHE_KEY, json.dumps(result), ex=3)
    except Exception:
        pass
    return result


@router.get("/settings")
def read_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    configuration = get_configuration(db)
    feeds = {
        feed_key(feed.provider, feed.environment, feed.provider_symbol): feed
        for feed in db.scalars(select(MarketFeed))
    }
    instruments = list(
        db.scalars(
            select(CollectorInstrumentConfiguration).order_by(
                CollectorInstrumentConfiguration.provider,
                CollectorInstrumentConfiguration.environment,
                CollectorInstrumentConfiguration.provider_symbol
            )
        )
    )
    return {
        "configuration": serialize_configuration(configuration),
        "instruments": [
            serialize_instrument(row, feeds.get(instrument_key(row))) for row in instruments
        ],
    }


@router.put("/settings")
def update_settings(
    payload: CollectorSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = get_configuration(db)
    if row.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Settings changed; current version is {row.version}",
        )
    for key, value in payload.model_dump(exclude={"expected_version"}).items():
        setattr(row, key, value)
    row.version += 1
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="COLLECTOR_SETTINGS_UPDATED",
        target_type="COLLECTOR_CONFIGURATION",
        target_id=str(row.id),
        details={"version": row.version},
    )
    db.commit()
    db.refresh(row)
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.configuration",
            "occurred_at": datetime.now(UTC).isoformat(),
            "version": row.version,
        }
    )
    return serialize_configuration(row)


@router.put("/feeds/{feed_id}/settings")
def update_instrument_settings(
    feed_id: uuid.UUID,
    payload: CollectorInstrumentSettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    feed = feed_or_404(db, feed_id)
    invalid = set(payload.overrides) - ALLOWED_OVERRIDE_KEYS
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported overrides: {', '.join(sorted(invalid))}",
        )
    effective = configuration_values(get_configuration(db)) | payload.overrides
    CollectorSettingsValues.model_validate(effective)
    row = db.scalar(
        select(CollectorInstrumentConfiguration).where(
            CollectorInstrumentConfiguration.provider == feed.provider,
            CollectorInstrumentConfiguration.environment == feed.environment,
            CollectorInstrumentConfiguration.provider_symbol == feed.provider_symbol
        )
    )
    if row is None:
        row = CollectorInstrumentConfiguration(
            provider=feed.provider,
            environment=feed.environment,
            provider_symbol=feed.provider_symbol,
        )
        db.add(row)
    row.enabled = payload.enabled
    row.overrides = payload.overrides
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="COLLECTOR_INSTRUMENT_SETTINGS_UPDATED",
        target_type="MARKET_FEED",
        target_id=str(feed.id),
        details={"enabled": row.enabled, "overrides": row.overrides},
    )
    db.commit()
    db.refresh(row)
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.configuration",
            "occurred_at": datetime.now(UTC).isoformat(),
            "market_feed_id": str(feed.id),
        }
    )
    return serialize_instrument(row, feed)


@router.post("/instruments", status_code=201)
def create_instrument(
    payload: CollectorInstrumentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    existing = db.scalar(
        select(CollectorInstrumentConfiguration).where(
            CollectorInstrumentConfiguration.provider == payload.provider,
            CollectorInstrumentConfiguration.environment == payload.environment,
            CollectorInstrumentConfiguration.provider_symbol == payload.provider_symbol
        )
    )
    if existing:
        if existing.enabled:
            raise HTTPException(status_code=409, detail="Instrument already exists")
        existing.enabled = True
        existing.overrides = existing.overrides or {}
        add_audit(
            db,
            actor_type="USER",
            actor_id=str(user.id),
            action="COLLECTOR_INSTRUMENT_REENABLED",
            target_type="COLLECTOR_INSTRUMENT",
            target_id=str(existing.id),
            details={"provider_symbol": existing.provider_symbol},
        )
        db.commit()
        db.refresh(existing)
        invalidate_collector_overview()
        publish_event_sync(
            {
                "event_type": "collector.configuration",
                "occurred_at": datetime.now(UTC).isoformat(),
                "provider": existing.provider,
                "environment": existing.environment,
                "provider_symbol": existing.provider_symbol,
            }
        )
        feed = db.scalar(
            select(MarketFeed).where(
                MarketFeed.provider == existing.provider,
                MarketFeed.environment == existing.environment,
                MarketFeed.provider_symbol == existing.provider_symbol,
            )
        )
        return serialize_instrument(existing, feed)
    row = CollectorInstrumentConfiguration(
        provider=payload.provider,
        environment=payload.environment,
        provider_symbol=payload.provider_symbol,
        enabled=True,
        overrides={},
    )
    db.add(row)
    db.flush()
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="COLLECTOR_INSTRUMENT_CREATED",
        target_type="COLLECTOR_INSTRUMENT",
        target_id=str(row.id),
        details={"provider_symbol": row.provider_symbol},
    )
    db.commit()
    db.refresh(row)
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.configuration",
            "occurred_at": datetime.now(UTC).isoformat(),
            "provider": row.provider,
            "environment": row.environment,
            "provider_symbol": row.provider_symbol,
        }
    )
    return serialize_instrument(row, None)


def hard_delete_feed_data(db: Session, feed: MarketFeed) -> dict[str, int]:
    feed_id = feed.id
    bot_ids = select(Bot.id).where(Bot.market_feed_id == feed_id)
    run_ids = select(Run.id).where(Run.bot_id.in_(bot_ids))
    config_ids = select(ConfigVersion.id).where(ConfigVersion.bot_id.in_(bot_ids))
    backtest_ids = select(BacktestExperiment.id).where(BacktestExperiment.market_feed_id == feed_id)
    optimization_ids = select(OptimizationRun.id).where(OptimizationRun.market_feed_id == feed_id)
    trial_ids = select(OptimizationTrial.id).where(
        OptimizationTrial.optimization_run_id.in_(optimization_ids)
    )
    counts: dict[str, int] = {}
    counts["optimization_trial_trades"] = delete_count(
        db,
        delete(OptimizationTrialTrade).where(OptimizationTrialTrade.trial_id.in_(trial_ids)),
    )
    counts["optimization_trials"] = delete_count(
        db,
        delete(OptimizationTrial).where(
            OptimizationTrial.optimization_run_id.in_(optimization_ids)
        ),
    )
    counts["optimization_runs"] = delete_count(
        db,
        delete(OptimizationRun).where(OptimizationRun.market_feed_id == feed_id),
    )
    counts["backtest_trades"] = delete_count(
        db,
        delete(BacktestTrade).where(BacktestTrade.experiment_id.in_(backtest_ids)),
    )
    counts["backtest_experiments"] = delete_count(
        db,
        delete(BacktestExperiment).where(BacktestExperiment.market_feed_id == feed_id),
    )
    counts["signal_outcomes"] = delete_count(
        db,
        delete(SignalOutcome).where(SignalOutcome.bot_id.in_(bot_ids)),
    )
    counts["signals"] = delete_count(
        db,
        delete(Signal).where(Signal.bot_id.in_(bot_ids)),
    )
    counts["paper_accounts"] = delete_count(
        db,
        delete(PaperAccount).where(PaperAccount.bot_id.in_(bot_ids)),
    )
    counts["runs"] = delete_count(
        db,
        delete(Run).where(Run.id.in_(run_ids)),
    )
    counts["config_versions"] = delete_count(
        db,
        delete(ConfigVersion).where(ConfigVersion.id.in_(config_ids)),
    )
    counts["bots"] = delete_count(
        db,
        delete(Bot).where(Bot.market_feed_id == feed_id),
    )
    counts["ingestion_events"] = delete_count(
        db,
        delete(IngestionEvent).where(IngestionEvent.market_feed_id == feed_id),
    )
    counts["market_ticks"] = delete_count(
        db,
        delete(MarketTick).where(MarketTick.market_feed_id == feed_id),
    )
    counts["candles"] = delete_count(
        db,
        delete(Candle).where(Candle.market_feed_id == feed_id),
    )
    counts["instrument_specifications"] = delete_count(
        db,
        delete(InstrumentSpecification).where(InstrumentSpecification.market_feed_id == feed_id),
    )
    counts["collector_commands"] = delete_count(
        db,
        delete(CollectorCommand).where(CollectorCommand.market_feed_id == feed_id),
    )
    counts["agents"] = delete_count(
        db,
        delete(Agent).where(Agent.market_feed_id == feed_id),
    )
    counts["market_feeds"] = delete_count(
        db,
        delete(MarketFeed).where(MarketFeed.id == feed_id),
    )
    return counts


@router.delete("/feeds/{feed_id}")
def delete_feed(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    feed = feed_or_404(db, feed_id)
    provider = feed.provider
    environment = feed.environment
    provider_symbol = feed.provider_symbol
    active_backtest = db.scalar(
        select(BacktestExperiment.id).where(
            BacktestExperiment.market_feed_id == feed.id,
            BacktestExperiment.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    active_optimization = db.scalar(
        select(OptimizationRun.id).where(
            OptimizationRun.market_feed_id == feed.id,
            OptimizationRun.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active_backtest or active_optimization:
        raise HTTPException(
            status_code=409,
            detail="Feed has active backtests or optimizations; cancel or finish them first",
        )
    instrument = db.scalar(
        select(CollectorInstrumentConfiguration).where(
            CollectorInstrumentConfiguration.provider == provider,
            CollectorInstrumentConfiguration.environment == environment,
            CollectorInstrumentConfiguration.provider_symbol == provider_symbol,
        )
    )
    if instrument is None:
        instrument = CollectorInstrumentConfiguration(
            provider=provider,
            environment=environment,
            provider_symbol=provider_symbol,
            enabled=False,
            overrides={},
        )
        db.add(instrument)
        db.flush()
    else:
        instrument.enabled = False
    counts = hard_delete_feed_data(db, feed)
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="MARKET_FEED_HARD_DELETED",
        target_type="MARKET_FEED",
        target_id=str(feed_id),
        details={
            "provider": provider,
            "environment": environment,
            "provider_symbol": provider_symbol,
            "deleted": counts,
        },
    )
    db.commit()
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.configuration",
            "occurred_at": datetime.now(UTC).isoformat(),
            "market_feed_id": str(feed_id),
            "provider": provider,
            "environment": environment,
            "provider_symbol": provider_symbol,
        }
    )
    return {
        "deleted": True,
        "market_feed_id": str(feed_id),
        "provider": provider,
        "environment": environment,
        "provider_symbol": provider_symbol,
        "counts": counts,
    }


@router.get("/feeds/{feed_id}")
def feed_detail(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    feed = feed_or_404(db, feed_id)
    now = datetime.now(UTC)
    summary = feed_summary(db, feed, now)
    agent = db.scalar(
        select(Agent)
        .where(Agent.market_feed_id == feed.id)
        .order_by(desc(Agent.updated_at))
        .limit(1)
    )
    instrument = db.scalar(
        select(CollectorInstrumentConfiguration).where(
            CollectorInstrumentConfiguration.provider == feed.provider,
            CollectorInstrumentConfiguration.environment == feed.environment,
            CollectorInstrumentConfiguration.provider_symbol == feed.provider_symbol
        )
    )
    commands = list(
        db.scalars(
            select(CollectorCommand)
            .where(CollectorCommand.market_feed_id == feed.id)
            .order_by(desc(CollectorCommand.created_at))
            .limit(50)
        )
    )
    recent = list(
        db.scalars(
            select(Candle.opened_at)
            .where(
                Candle.market_feed_id == feed.id,
                Candle.timeframe == "M1",
                Candle.is_complete.is_(True),
            )
            .order_by(desc(Candle.opened_at))
            .limit(1441)
        )
    )
    gaps = 0
    gap_segments = []
    for newer, older in zip(recent, recent[1:], strict=False):
        delta = int((as_utc(newer) - as_utc(older)).total_seconds() // 60)
        missing_minutes = max(0, delta - 1)
        gaps += missing_minutes
        if missing_minutes:
            gap_segments.append(
                {
                    "from": as_utc(older + timedelta(minutes=1)),
                    "to": as_utc(newer - timedelta(minutes=1)),
                    "missing_minutes": missing_minutes,
                }
            )
    return {
        "feed": summary,
        "agent": jsonable_encoder(agent) if agent else None,
        "instrument_settings": (
            serialize_instrument(instrument, feed)
            if instrument
            else {
                "provider_symbol": feed.provider_symbol,
                "enabled": True,
                "overrides": {},
                "provider": feed.provider,
                "environment": feed.environment,
                "market_feed_id": str(feed.id),
                "canonical_symbol": feed.canonical_symbol,
            }
        ),
        "gap_count": gaps,
        "gaps": jsonable_encoder(gap_segments),
        "commands": [serialize_command(command) for command in commands],
    }


def parse_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        return datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


@router.get("/feeds/{feed_id}/candles")
def list_candles(
    feed_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    feed_or_404(db, feed_id)
    statement = select(Candle).where(Candle.market_feed_id == feed_id)
    before = parse_cursor(cursor)
    if before:
        statement = statement.where(Candle.opened_at < before)
    rows = list(db.scalars(statement.order_by(desc(Candle.opened_at)).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            jsonable_encoder(
                {
                    "opened_at": row.opened_at,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.tick_volume,
                    "complete": row.is_complete,
                }
            )
            for row in rows
        ],
        "next_cursor": rows[-1].opened_at.isoformat() if has_more and rows else None,
    }


@router.get("/feeds/{feed_id}/ticks")
def list_ticks(
    feed_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    feed_or_404(db, feed_id)
    statement = select(MarketTick).where(MarketTick.market_feed_id == feed_id)
    before = parse_cursor(cursor)
    if before:
        statement = statement.where(MarketTick.observed_at < before)
    rows = list(db.scalars(statement.order_by(desc(MarketTick.observed_at)).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            jsonable_encoder(
                {
                    "observed_at": row.observed_at,
                    "received_at": row.received_at,
                    "bid": row.bid,
                    "ask": row.ask,
                    "spread": row.ask - row.bid,
                }
            )
            for row in rows
        ],
        "next_cursor": rows[-1].observed_at.isoformat() if has_more and rows else None,
    }


@router.get("/feeds/{feed_id}/export/{data_type}")
def export_data(
    feed_id: uuid.UUID,
    data_type: str,
    start: datetime,
    end: datetime,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    feed = feed_or_404(db, feed_id)
    start, end = as_utc(start), as_utc(end)
    if end <= start:
        raise HTTPException(status_code=422, detail="End must be after start")
    if data_type == "candles":
        rows = list(
            db.scalars(
                select(Candle)
                .where(
                    Candle.market_feed_id == feed_id,
                    Candle.opened_at >= start,
                    Candle.opened_at <= end,
                )
                .order_by(Candle.opened_at)
                .limit(100001)
            )
        )
        headers = ["opened_at", "open", "high", "low", "close", "volume"]
        values = (
            [row.opened_at.isoformat(), row.open, row.high, row.low, row.close, row.tick_volume]
            for row in rows
        )
    elif data_type == "ticks":
        rows = list(
            db.scalars(
                select(MarketTick)
                .where(
                    MarketTick.market_feed_id == feed_id,
                    MarketTick.observed_at >= start,
                    MarketTick.observed_at <= end,
                )
                .order_by(MarketTick.observed_at)
                .limit(100001)
            )
        )
        headers = ["observed_at", "received_at", "bid", "ask", "spread"]
        values = (
            [
                row.observed_at.isoformat(),
                row.received_at.isoformat(),
                row.bid,
                row.ask,
                row.ask - row.bid,
            ]
            for row in rows
        )
    else:
        raise HTTPException(status_code=404, detail="Unknown export type")
    if len(rows) > 100000:
        raise HTTPException(status_code=413, detail="Export exceeds 100000 rows")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(values)
    filename = f"{feed.provider_symbol}-{data_type}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/commands")
def list_commands(
    market_feed_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    statement = select(CollectorCommand)
    if market_feed_id:
        statement = statement.where(CollectorCommand.market_feed_id == market_feed_id)
    rows = db.scalars(statement.order_by(desc(CollectorCommand.created_at)).limit(limit))
    return [serialize_command(row) for row in rows]


@router.post("/commands", status_code=201)
def create_command(
    payload: CollectorCommandCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.market_feed_id:
        feed_or_404(db, payload.market_feed_id)
    if payload.command in {"RECONNECT", "BACKFILL"} and payload.market_feed_id is None:
        raise HTTPException(status_code=422, detail="This command requires a market feed")
    if payload.command == "BACKFILL":
        try:
            start = as_utc(
                datetime.fromisoformat(str(payload.payload["start"]).replace("Z", "+00:00"))
            )
            end = as_utc(datetime.fromisoformat(str(payload.payload["end"]).replace("Z", "+00:00")))
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Backfill requires valid start and end",
            ) from exc
        if end <= start or end - start > timedelta(days=365):
            raise HTTPException(status_code=422, detail="Backfill range must be 0-365 days")
        active = db.scalar(
            select(CollectorCommand).where(
                CollectorCommand.command == "BACKFILL",
                CollectorCommand.market_feed_id == payload.market_feed_id,
                CollectorCommand.status.in_(["PENDING", "RUNNING"]),
            )
        )
        if active:
            raise HTTPException(
                status_code=409,
                detail="Another backfill is already active for this feed",
            )
    row = CollectorCommand(
        market_feed_id=payload.market_feed_id,
        command=payload.command,
        payload=payload.payload,
        requested_by=user.id,
    )
    db.add(row)
    db.flush()
    if payload.command == "PAUSE":
        now = datetime.now(UTC)
        if payload.market_feed_id:
            pause_feed(feed_or_404(db, payload.market_feed_id), now)
        else:
            get_configuration(db).globally_paused = True
            for feed in db.scalars(select(MarketFeed)):
                pause_feed(feed, now)
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="COLLECTOR_COMMAND_CREATED",
        target_type="COLLECTOR_COMMAND",
        target_id=str(row.id),
        details={"command": row.command, "market_feed_id": str(row.market_feed_id or "")},
    )
    db.commit()
    db.refresh(row)
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.command",
            "occurred_at": datetime.now(UTC).isoformat(),
            "command_id": str(row.id),
            "status": row.status,
        }
    )
    return serialize_command(row)


@router.post("/instances/register", status_code=201)
def register_instance(
    payload: CollectorInstanceRegister,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    instance = db.scalar(select(CollectorInstance).where(CollectorInstance.name == payload.name))
    if instance is None:
        instance = CollectorInstance(name=payload.name)
        db.add(instance)
    else:
        interrupted_commands = db.scalars(
            select(CollectorCommand).where(
                CollectorCommand.collector_instance_id == instance.id,
                CollectorCommand.status == "RUNNING",
            )
        )
        for command in interrupted_commands:
            command.collector_instance_id = None
            command.status = "PENDING"
            command.started_at = None
    configuration = db.scalar(select(CollectorConfiguration))
    if configuration is None:
        configuration = CollectorConfiguration(version=1, **payload.defaults.model_dump())
        db.add(configuration)
    existing = {
        instrument_key(row): row
        for row in db.scalars(select(CollectorInstrumentConfiguration))
    }
    for item in payload.instruments:
        seed = (
            {"provider": "oanda", "environment": "practice", "provider_symbol": item}
            if isinstance(item, str)
            else item.model_dump()
        )
        key = feed_key(seed["provider"], seed["environment"], seed["provider_symbol"])
        if key not in existing:
            db.add(
                CollectorInstrumentConfiguration(
                    provider=seed["provider"],
                    environment=seed["environment"],
                    provider_symbol=seed["provider_symbol"],
                    enabled=True,
                    overrides={},
                )
            )
    db.commit()
    db.refresh(instance)
    db.refresh(configuration)
    invalidate_collector_overview()
    return {
        "instance": jsonable_encoder(instance),
        "configuration": serialize_configuration(configuration),
    }


@router.post("/instances/{instance_id}/heartbeat")
def instance_heartbeat(
    instance_id: uuid.UUID,
    payload: CollectorInstanceHeartbeat,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    instance = db.get(CollectorInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Collector instance not found")
    instance.status = payload.status
    instance.last_heartbeat_at = as_utc(payload.observed_at)
    instance.applied_config_version = payload.applied_config_version
    instance.details = payload.details
    db.commit()
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.heartbeat",
            "occurred_at": datetime.now(UTC).isoformat(),
            "collector_instance_id": str(instance.id),
            "status": instance.status,
        }
    )
    return {"accepted": True}


@router.post("/instances/{instance_id}/poll")
def poll_control(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    instance = db.get(CollectorInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Collector instance not found")
    configuration = get_configuration(db)
    feeds = {
        feed_key(feed.provider, feed.environment, feed.provider_symbol): feed
        for feed in db.scalars(select(MarketFeed))
    }
    instruments = list(db.scalars(select(CollectorInstrumentConfiguration)))
    statement = (
        select(CollectorCommand)
        .where(
            CollectorCommand.status == "PENDING",
            CollectorCommand.collector_instance_id.is_(None),
        )
        .order_by(CollectorCommand.created_at)
        .limit(20)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    commands = list(db.scalars(statement))
    now = datetime.now(UTC)
    for command in commands:
        command.collector_instance_id = instance.id
        command.status = "RUNNING"
        command.started_at = now
    db.commit()
    invalidate_collector_overview()
    return {
        "configuration": serialize_configuration(configuration),
        "instruments": [
            serialize_instrument(row, feeds.get(instrument_key(row))) for row in instruments
        ],
        "commands": [serialize_command(command) for command in commands],
    }


@router.patch("/commands/{command_id}")
def update_command(
    command_id: uuid.UUID,
    payload: CollectorCommandUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    command = db.get(CollectorCommand, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Collector command not found")
    if command.status in {"SUCCEEDED", "FAILED"}:
        return serialize_command(command)
    command.status = payload.status
    command.progress = payload.progress
    command.result = payload.result
    command.error = payload.error
    if payload.status in {"SUCCEEDED", "FAILED"}:
        command.completed_at = datetime.now(UTC)
    if payload.status == "SUCCEEDED" and command.command in {"PAUSE", "RESUME"}:
        now = datetime.now(UTC)
        if command.market_feed_id:
            feed = db.get(MarketFeed, command.market_feed_id)
            if feed:
                if command.command == "PAUSE":
                    pause_feed(feed, now)
                else:
                    get_configuration(db).globally_paused = False
                    resume_feed(db, feed, now)
        else:
            if command.command == "PAUSE":
                get_configuration(db).globally_paused = True
            else:
                get_configuration(db).globally_paused = False
            for feed in db.scalars(select(MarketFeed)):
                if command.command == "PAUSE":
                    pause_feed(feed, now)
                else:
                    resume_feed(db, feed, now)
    db.commit()
    db.refresh(command)
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.command",
            "occurred_at": datetime.now(UTC).isoformat(),
            "command_id": str(command.id),
            "market_feed_id": str(command.market_feed_id or ""),
            "status": command.status,
            "progress": command.progress,
        }
    )
    return serialize_command(command)


@router.delete("/commands/{command_id}")
def delete_command(
    command_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    command = db.get(CollectorCommand, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Collector command not found")
    if command.status in {"SUCCEEDED", "FAILED"}:
        return serialize_command(command)
    command.status = "FAILED"
    command.error = "Cancelled by user"
    command.completed_at = datetime.now(UTC)
    command.progress = command.progress or {}
    command.result = command.result or {}
    add_audit(
        db,
        actor_type="USER",
        actor_id=str(user.id),
        action="COLLECTOR_COMMAND_CANCELLED",
        target_type="COLLECTOR_COMMAND",
        target_id=str(command.id),
        details={"command": command.command, "market_feed_id": str(command.market_feed_id or "")},
    )
    db.commit()
    db.refresh(command)
    invalidate_collector_overview()
    publish_event_sync(
        {
            "event_type": "collector.command",
            "occurred_at": datetime.now(UTC).isoformat(),
            "command_id": str(command.id),
            "market_feed_id": str(command.market_feed_id or ""),
            "status": command.status,
            "progress": command.progress,
        }
    )
    return serialize_command(command)
