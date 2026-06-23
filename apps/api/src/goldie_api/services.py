import uuid
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from goldie_domain import BotConfiguration, CandleInput, MarketContext, get_strategy
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    Bot,
    Candle,
    ConfigVersion,
    InstrumentSpecification,
    MarketTick,
    Run,
    Signal,
    StrategyProfile,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def add_audit(
    db: Session,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=jsonable_encoder(details or {}),
        )
    )


def next_config_version(db: Session, bot_id: uuid.UUID) -> int:
    current = db.scalar(
        select(func.max(ConfigVersion.version)).where(ConfigVersion.bot_id == bot_id)
    )
    return (current or 0) + 1


def merge_config(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value
    return result


def effective_strategy_config(
    strategy_profile: StrategyProfile,
    overrides: dict,
    *,
    symbol: str,
) -> BotConfiguration:
    sanitized = dict(overrides)
    sanitized.pop("market", None)
    merged = merge_config(strategy_profile.config, sanitized)
    market = dict(merged.get("market") or {})
    market["symbol"] = symbol
    merged["market"] = market
    return BotConfiguration.model_validate(merged)


def activate_config_version(
    db: Session,
    bot: Bot,
    row: ConfigVersion,
    *,
    now: datetime | None = None,
) -> None:
    activated_at = now or utc_now()
    previous = db.scalar(
        select(ConfigVersion).where(
            ConfigVersion.bot_id == bot.id,
            ConfigVersion.status == "ACTIVE",
            ConfigVersion.id != row.id,
        )
    )
    if previous:
        previous.status = "SUPERSEDED"
    for run in db.scalars(
        select(Run).where(Run.bot_id == bot.id, Run.status == "ACTIVE")
    ):
        run.status = "SUPERSEDED"
        run.ended_at = activated_at
    row.status = "ACTIVE"
    row.activated_at = activated_at
    bot.active_config_version_id = row.id
    bot.state = "MONITORING"
    db.add(Run(bot_id=bot.id, config_version_id=row.id, mode=bot.mode))


def evaluate_latest_signal(db: Session, bot: Bot) -> tuple[Signal | None, bool]:
    if (
        bot.archived_at is not None
        or bot.state != "MONITORING"
        or bot.active_config_version_id is None
    ):
        return None, False
    config_row = db.get(ConfigVersion, bot.active_config_version_id)
    if config_row is None or config_row.status != "ACTIVE":
        return None, False
    active_run = db.scalar(
        select(Run)
        .where(Run.bot_id == bot.id, Run.status == "ACTIVE")
        .order_by(desc(Run.created_at))
    )
    if bot.market_feed_id is None:
        return None, False
    tick = db.scalar(
        select(MarketTick)
        .where(MarketTick.market_feed_id == bot.market_feed_id)
        .order_by(desc(MarketTick.observed_at))
    )
    spec = db.scalar(
        select(InstrumentSpecification)
        .where(InstrumentSpecification.market_feed_id == bot.market_feed_id)
        .order_by(desc(InstrumentSpecification.updated_at))
    )
    if active_run is None or tick is None or spec is None:
        return None, False

    config = BotConfiguration.model_validate(config_row.config)
    strategy = get_strategy(config.strategy.name)
    required_candles = strategy.required_candles(
        strategy.parameters_model.model_validate(config.strategy.parameters)
    )
    rows = list(
        db.scalars(
            select(Candle)
            .where(
                Candle.market_feed_id == bot.market_feed_id,
                Candle.symbol == tick.symbol,
                Candle.timeframe == config.market.timeframe,
                Candle.is_complete.is_(True),
            )
            .order_by(desc(Candle.opened_at))
            .limit(required_candles)
        )
    )
    if not rows:
        return None, False

    latest_candle = max(rows, key=lambda row: as_utc(row.opened_at))
    latest_candle_at = as_utc(latest_candle.opened_at)
    duplicate = db.scalar(
        select(Signal).where(
            Signal.bot_id == bot.id,
            Signal.run_id == active_run.id,
            Signal.observed_at == latest_candle_at,
        )
    )
    if duplicate is not None:
        return duplicate, False

    return evaluate_signal_from_context(
        db,
        bot=bot,
        config_row=config_row,
        active_run=active_run,
        tick=tick,
        spec=spec,
        rows=rows,
    )


def evaluate_signal_from_context(
    db: Session,
    *,
    bot: Bot,
    config_row: ConfigVersion,
    active_run: Run,
    tick: MarketTick,
    spec: InstrumentSpecification,
    rows: list[Candle],
) -> tuple[Signal | None, bool]:
    if not rows:
        return None, False
    config = BotConfiguration.model_validate(config_row.config)
    strategy = get_strategy(config.strategy.name)
    latest_candle_at = max(as_utc(row.opened_at) for row in rows)

    decision = strategy.evaluate(
        MarketContext(
            observed_at=as_utc(tick.observed_at),
            bid=tick.bid,
            ask=tick.ask,
            point=spec.point,
            candles=[
                CandleInput(
                    opened_at=as_utc(row.opened_at),
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    tick_volume=row.tick_volume,
                    is_complete=row.is_complete,
                )
                for row in rows
            ],
        ),
        config,
    )
    signal = Signal(
        id=uuid.uuid4(),
        bot_id=bot.id,
        run_id=active_run.id,
        config_version_id=config_row.id,
        observed_at=latest_candle_at,
        signal=decision.signal.value,
        reason_code=decision.reason_code,
        entry_price=decision.entry_price,
        stop_loss=decision.stop_loss,
        take_profit=decision.take_profit,
        momentum_points=decision.momentum_points,
        spread_points=decision.spread_points,
        inputs=jsonable_encoder(decision.inputs),
    )
    db.add(signal)
    return signal, True
