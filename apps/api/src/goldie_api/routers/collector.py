import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import require_agent_token
from ..models import (
    Agent,
    Bot,
    Candle,
    CollectorCommand,
    CollectorConfiguration,
    CollectorInstance,
    CollectorInstrumentConfiguration,
    MarketFeed,
    MarketTick,
    User,
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
from ..realtime import (
    OVERVIEW_CACHE_KEY,
    invalidate_collector_overview,
    publish_event_sync,
    redis_client,
)
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
            **configuration_values(row),
        )
    )


def serialize_instrument(row: CollectorInstrumentConfiguration, feed: MarketFeed | None) -> dict:
    return {
        "id": str(row.id),
        "provider_symbol": row.provider_symbol,
        "enabled": row.enabled,
        "overrides": row.overrides,
        "market_feed_id": str(feed.id) if feed else None,
        "canonical_symbol": feed.canonical_symbol if feed else row.provider_symbol.replace("_", ""),
    }


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


def feed_summary(db: Session, feed: MarketFeed, now: datetime) -> dict:
    tick = db.scalar(
        select(MarketTick)
        .where(MarketTick.market_feed_id == feed.id)
        .order_by(desc(MarketTick.observed_at))
    )
    candle = db.scalar(
        select(Candle)
        .where(
            Candle.market_feed_id == feed.id,
            Candle.timeframe == "M1",
            Candle.is_complete.is_(True),
        )
        .order_by(desc(Candle.opened_at))
    )
    earliest_candle_at = db.scalar(
        select(func.min(Candle.opened_at)).where(
            Candle.market_feed_id == feed.id,
            Candle.timeframe == "M1",
            Candle.is_complete.is_(True),
        )
    )
    bots = db.scalar(select(func.count(Bot.id)).where(Bot.market_feed_id == feed.id)) or 0
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
                .where(Bot.market_feed_id.in_(feed_ids))
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
        feed.provider_symbol: feed for feed in db.scalars(select(MarketFeed))
    }
    instruments = list(
        db.scalars(
            select(CollectorInstrumentConfiguration).order_by(
                CollectorInstrumentConfiguration.provider_symbol
            )
        )
    )
    return {
        "configuration": serialize_configuration(configuration),
        "instruments": [
            serialize_instrument(row, feeds.get(row.provider_symbol)) for row in instruments
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
            CollectorInstrumentConfiguration.provider_symbol == feed.provider_symbol
        )
    )
    if row is None:
        row = CollectorInstrumentConfiguration(provider_symbol=feed.provider_symbol)
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
            CollectorInstrumentConfiguration.provider_symbol == payload.provider_symbol
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Instrument already exists")
    row = CollectorInstrumentConfiguration(
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
            "provider_symbol": row.provider_symbol,
        }
    )
    return serialize_instrument(row, None)


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
    )
    instrument = db.scalar(
        select(CollectorInstrumentConfiguration).where(
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
            .where(Candle.market_feed_id == feed.id)
            .order_by(desc(Candle.opened_at))
            .limit(1441)
        )
    )
    gaps = 0
    for newer, older in zip(recent, recent[1:], strict=False):
        delta = int((as_utc(newer) - as_utc(older)).total_seconds() // 60)
        gaps += max(0, delta - 1)
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
                "market_feed_id": str(feed.id),
                "canonical_symbol": feed.canonical_symbol,
            }
        ),
        "gap_count": gaps,
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
        row.provider_symbol: row
        for row in db.scalars(select(CollectorInstrumentConfiguration))
    }
    for symbol in payload.instruments:
        if symbol not in existing:
            db.add(
                CollectorInstrumentConfiguration(
                    provider_symbol=symbol,
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
        feed.provider_symbol: feed for feed in db.scalars(select(MarketFeed))
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
            serialize_instrument(row, feeds.get(row.provider_symbol)) for row in instruments
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
        feed_status = "PAUSED" if command.command == "PAUSE" else "REGISTERED"
        if command.market_feed_id:
            feed = db.get(MarketFeed, command.market_feed_id)
            if feed:
                feed.status = feed_status
        else:
            for feed in db.scalars(select(MarketFeed)):
                feed.status = feed_status
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
