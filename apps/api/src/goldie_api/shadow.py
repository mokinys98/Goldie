from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldie_domain import (
    BotConfiguration,
    calculate_position_size,
    evaluate_shadow_position,
)
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .models import (
    Bot,
    ConfigVersion,
    InstrumentSpecification,
    MarketTick,
    PaperAccount,
    Signal,
    SignalOutcome,
)
from .settings import get_settings


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def instrument_specification(
    db: Session,
    bot: Bot,
    symbol: str,
) -> InstrumentSpecification | None:
    if bot.market_feed_id is None:
        return None
    return db.scalar(
        select(InstrumentSpecification)
        .where(
            InstrumentSpecification.market_feed_id == bot.market_feed_id,
            InstrumentSpecification.canonical_symbol == symbol,
        )
        .order_by(desc(InstrumentSpecification.updated_at))
    )


def trade_step(spec: InstrumentSpecification) -> Decimal:
    precision = spec.trade_units_precision or 0
    return Decimal(1).scaleb(-precision)


def account_values(db: Session, bot: Bot) -> tuple[Decimal, Decimal]:
    account = db.scalar(select(PaperAccount).where(PaperAccount.bot_id == bot.id))
    if account is not None:
        return account.balance, account.equity
    notional = get_settings().shadow_notional_balance
    return notional, notional


def create_signal_outcome(
    db: Session,
    signal: Signal,
    tick: MarketTick,
) -> SignalOutcome | None:
    if signal.signal not in {"BUY", "SELL"}:
        return None
    existing = db.scalar(select(SignalOutcome).where(SignalOutcome.signal_id == signal.id))
    if existing is not None:
        return existing

    bot = db.scalar(select(Bot).where(Bot.id == signal.bot_id).with_for_update())
    if bot is None or bot.market_feed_id != tick.market_feed_id:
        return None
    base = {
        "signal_id": signal.id,
        "bot_id": signal.bot_id,
        "run_id": signal.run_id,
        "config_version_id": signal.config_version_id,
        "direction": signal.signal,
        "entry_price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
    }
    open_outcome = db.scalar(
        select(SignalOutcome).where(
            SignalOutcome.bot_id == signal.bot_id,
            SignalOutcome.status == "OPEN",
        )
    )
    if open_outcome is not None:
        outcome = SignalOutcome(
            **base,
            status="SKIPPED",
            skip_reason="OPEN_POSITION_EXISTS",
        )
        db.add(outcome)
        return outcome

    spec = instrument_specification(db, bot, tick.symbol)
    if spec is None:
        outcome = SignalOutcome(
            **base,
            status="SKIPPED",
            skip_reason="MISSING_SYMBOL_SPEC",
        )
        db.add(outcome)
        return outcome

    config_row = db.get(ConfigVersion, signal.config_version_id)
    config = BotConfiguration.model_validate(config_row.config if config_row else {})
    if signal.entry_price is None or signal.stop_loss is None or signal.take_profit is None:
        outcome = SignalOutcome(
            **base,
            status="SKIPPED",
            skip_reason="INVALID_POSITION_SIZE",
        )
        db.add(outcome)
        return outcome

    balance, equity = account_values(db, bot)
    step = trade_step(spec)
    size = calculate_position_size(
        balance=balance,
        equity=equity,
        risk_per_trade_pct=config.theoretical_trade.risk_per_trade_pct,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        tick_size=spec.point,
        tick_value=spec.point,
        volume_min=spec.minimum_trade_size or step,
        volume_max=Decimal("1000000000"),
        volume_step=step,
    )
    if size is None:
        outcome = SignalOutcome(
            **base,
            status="SKIPPED",
            skip_reason="INVALID_POSITION_SIZE",
        )
        db.add(outcome)
        return outcome

    outcome = SignalOutcome(
        **base,
        status="OPEN",
        opened_at=tick.observed_at,
        last_evaluated_at=tick.observed_at,
        volume=size.volume,
        risk_amount=size.risk_amount,
        mfe_points=Decimal("0"),
        mae_points=Decimal("0"),
    )
    db.add(outcome)
    return outcome


def evaluate_open_outcome(
    db: Session,
    bot: Bot,
    tick: MarketTick,
    *,
    loaded_outcome: SignalOutcome | None = None,
    loaded_config: ConfigVersion | None = None,
    loaded_spec: InstrumentSpecification | None = None,
) -> SignalOutcome | None:
    if (
        bot.archived_at is not None
        or bot.market_feed_id != tick.market_feed_id
    ):
        return None
    outcome = loaded_outcome or db.scalar(
        select(SignalOutcome).where(
            SignalOutcome.bot_id == bot.id, SignalOutcome.status == "OPEN"
        )
    )
    if outcome is None or outcome.opened_at is None or outcome.last_evaluated_at is None:
        return None
    if (
        outcome.entry_price is None
        or outcome.stop_loss is None
        or outcome.take_profit is None
        or outcome.volume is None
        or outcome.risk_amount is None
    ):
        return None
    config_row = loaded_config or db.get(ConfigVersion, outcome.config_version_id)
    config = BotConfiguration.model_validate(config_row.config if config_row else {})
    spec = loaded_spec or instrument_specification(db, bot, tick.symbol)
    if spec is None:
        return None

    tick_at = as_utc(tick.observed_at)
    last_evaluated_at = as_utc(outcome.last_evaluated_at)
    if tick_at <= last_evaluated_at:
        return outcome
    evaluation = evaluate_shadow_position(
        direction=outcome.direction,
        entry_price=outcome.entry_price,
        stop_loss=outcome.stop_loss,
        take_profit=outcome.take_profit,
        volume=outcome.volume,
        risk_amount=outcome.risk_amount,
        point=spec.point,
        tick_size=spec.point,
        tick_value=spec.point,
        opened_at=as_utc(outcome.opened_at)
        + timedelta(seconds=outcome.paused_duration_seconds),
        last_evaluated_at=last_evaluated_at
        + timedelta(seconds=outcome.paused_duration_seconds),
        tick_at=tick_at,
        bid=tick.bid,
        ask=tick.ask,
        max_duration_minutes=config.theoretical_trade.max_trade_duration_minutes,
        stale_after_seconds=config.filters.stale_after_seconds,
        current_mfe_points=outcome.mfe_points,
        current_mae_points=outcome.mae_points,
    )
    outcome.mfe_points = evaluation.mfe_points
    outcome.mae_points = evaluation.mae_points
    outcome.last_evaluated_at = tick.observed_at
    if evaluation.should_close:
        outcome.status = "CLOSED"
        outcome.result = evaluation.result.value if evaluation.result else None
        outcome.close_reason = (
            evaluation.close_reason.value if evaluation.close_reason else None
        )
        outcome.closed_at = tick.observed_at
        outcome.exit_price = evaluation.exit_price
        outcome.pnl_points = evaluation.pnl_points
        outcome.gross_pnl = evaluation.net_pnl
        outcome.net_pnl = evaluation.net_pnl
        outcome.r_multiple = evaluation.r_multiple
        outcome.duration_seconds = max(
            0,
            int((tick_at - as_utc(outcome.opened_at)).total_seconds())
            - outcome.paused_duration_seconds,
        )
    return outcome


def performance_summary(outcomes: list[SignalOutcome]) -> dict:
    closed = [item for item in outcomes if item.status == "CLOSED"]
    skipped = [item for item in outcomes if item.status == "SKIPPED"]
    wins = [item for item in closed if item.result == "WIN"]
    losses = [item for item in closed if item.result == "LOSS"]
    net_values = [item.net_pnl or Decimal("0") for item in closed]
    point_values = [item.pnl_points or Decimal("0") for item in closed]
    r_values = [item.r_multiple or Decimal("0") for item in closed]
    gross_profit = sum((value for value in net_values if value > 0), Decimal("0"))
    gross_loss = abs(sum((value for value in net_values if value < 0), Decimal("0")))

    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    equity_curve = []
    max_wins = max_losses = current_wins = current_losses = 0
    direction = defaultdict(lambda: {"trades": 0, "net_pnl": Decimal("0")})
    hour = defaultdict(lambda: {"trades": 0, "net_pnl": Decimal("0")})
    run = defaultdict(lambda: {"trades": 0, "net_pnl": Decimal("0")})
    config = defaultdict(lambda: {"trades": 0, "net_pnl": Decimal("0")})

    for item in sorted(closed, key=lambda row: row.closed_at or row.created_at):
        value = item.net_pnl or Decimal("0")
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
        equity_curve.append({"time": item.closed_at, "value": cumulative})
        if item.result == "WIN":
            current_wins += 1
            current_losses = 0
        elif item.result == "LOSS":
            current_losses += 1
            current_wins = 0
        max_wins = max(max_wins, current_wins)
        max_losses = max(max_losses, current_losses)
        direction[item.direction]["trades"] += 1
        direction[item.direction]["net_pnl"] += value
        if item.opened_at:
            hour[str(as_utc(item.opened_at).hour)]["trades"] += 1
            hour[str(as_utc(item.opened_at).hour)]["net_pnl"] += value
        run[str(item.run_id)]["trades"] += 1
        run[str(item.run_id)]["net_pnl"] += value
        config[str(item.config_version_id)]["trades"] += 1
        config[str(item.config_version_id)]["net_pnl"] += value

    skipped_reasons = defaultdict(int)
    for item in skipped:
        skipped_reasons[item.skip_reason or "UNKNOWN"] += 1

    def average(values: list[Decimal]) -> Decimal | None:
        return sum(values, Decimal("0")) / len(values) if values else None

    def breakdown(rows: dict) -> list[dict]:
        return [
            {"key": key, "trades": value["trades"], "net_pnl": value["net_pnl"]}
            for key, value in sorted(rows.items())
        ]

    return {
        "total_signals": len(outcomes),
        "closed_trades": len(closed),
        "open_trades": sum(1 for item in outcomes if item.status == "OPEN"),
        "skipped_trades": len(skipped),
        "win_rate": Decimal(len(wins) * 100) / len(closed) if closed else None,
        "average_win": average([item.net_pnl or Decimal("0") for item in wins]),
        "average_loss": average([item.net_pnl or Decimal("0") for item in losses]),
        "net_pnl": sum(net_values, Decimal("0")),
        "total_points": sum(point_values, Decimal("0")),
        "total_r": sum(r_values, Decimal("0")),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "expectancy": average(net_values),
        "expectancy_r": average(r_values),
        "max_drawdown": max_drawdown,
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "average_duration_seconds": (
            sum(item.duration_seconds or 0 for item in closed) / len(closed)
            if closed
            else None
        ),
        "skipped_by_reason": dict(sorted(skipped_reasons.items())),
        "equity_curve": equity_curve,
        "breakdown": {
            "direction": breakdown(direction),
            "hour_utc": breakdown(hour),
            "run": breakdown(run),
            "config_version": breakdown(config),
        },
    }
