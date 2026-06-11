from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum


class ShadowCloseReason(StrEnum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TIMEOUT = "TIMEOUT"
    DATA_GAP = "DATA_GAP"


class ShadowResult(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


@dataclass(frozen=True)
class PositionSize:
    volume: Decimal
    risk_amount: Decimal


@dataclass(frozen=True)
class ShadowEvaluation:
    should_close: bool
    close_reason: ShadowCloseReason | None
    exit_price: Decimal | None
    result: ShadowResult | None
    pnl_points: Decimal | None
    net_pnl: Decimal | None
    r_multiple: Decimal | None
    mfe_points: Decimal
    mae_points: Decimal


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("Volume step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def calculate_position_size(
    *,
    balance: Decimal,
    equity: Decimal,
    risk_per_trade_pct: Decimal,
    entry_price: Decimal,
    stop_loss: Decimal,
    tick_size: Decimal,
    tick_value: Decimal,
    volume_min: Decimal,
    volume_max: Decimal,
    volume_step: Decimal,
) -> PositionSize | None:
    if tick_size <= 0 or tick_value <= 0:
        return None
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        return None
    risk_base = min(balance, equity)
    risk_amount = risk_base * risk_per_trade_pct / Decimal("100")
    stop_value_per_lot = stop_distance / tick_size * tick_value
    if risk_amount <= 0 or stop_value_per_lot <= 0:
        return None
    volume = floor_to_step(risk_amount / stop_value_per_lot, volume_step)
    volume = min(volume, volume_max)
    if volume < volume_min:
        return None
    actual_risk = stop_value_per_lot * volume
    return PositionSize(volume=volume, risk_amount=actual_risk)


def evaluate_shadow_position(
    *,
    direction: str,
    entry_price: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal,
    volume: Decimal,
    risk_amount: Decimal,
    point: Decimal,
    tick_size: Decimal,
    tick_value: Decimal,
    opened_at: datetime,
    last_evaluated_at: datetime,
    tick_at: datetime,
    bid: Decimal,
    ask: Decimal,
    max_duration_minutes: int,
    stale_after_seconds: int,
    current_mfe_points: Decimal = Decimal("0"),
    current_mae_points: Decimal = Decimal("0"),
) -> ShadowEvaluation:
    executable_price = bid if direction == "BUY" else ask
    move = (
        (executable_price - entry_price) / point
        if direction == "BUY"
        else (entry_price - executable_price) / point
    )
    mfe = max(current_mfe_points, move, Decimal("0"))
    mae = max(current_mae_points, -move, Decimal("0"))

    close_reason = None
    exit_price = None
    if (tick_at - last_evaluated_at).total_seconds() > stale_after_seconds:
        close_reason = ShadowCloseReason.DATA_GAP
        exit_price = stop_loss
    elif direction == "BUY" and bid <= stop_loss:
        close_reason = ShadowCloseReason.STOP_LOSS
        exit_price = stop_loss
    elif direction == "BUY" and bid >= take_profit:
        close_reason = ShadowCloseReason.TAKE_PROFIT
        exit_price = take_profit
    elif direction == "SELL" and ask >= stop_loss:
        close_reason = ShadowCloseReason.STOP_LOSS
        exit_price = stop_loss
    elif direction == "SELL" and ask <= take_profit:
        close_reason = ShadowCloseReason.TAKE_PROFIT
        exit_price = take_profit
    elif tick_at >= opened_at + timedelta(minutes=max_duration_minutes):
        close_reason = ShadowCloseReason.TIMEOUT
        exit_price = executable_price

    if close_reason is None or exit_price is None:
        return ShadowEvaluation(
            should_close=False,
            close_reason=None,
            exit_price=None,
            result=None,
            pnl_points=None,
            net_pnl=None,
            r_multiple=None,
            mfe_points=mfe,
            mae_points=mae,
        )

    pnl_points = (
        (exit_price - entry_price) / point
        if direction == "BUY"
        else (entry_price - exit_price) / point
    )
    net_pnl = pnl_points * point / tick_size * tick_value * volume
    result = (
        ShadowResult.WIN
        if net_pnl > 0
        else ShadowResult.LOSS
        if net_pnl < 0
        else ShadowResult.BREAKEVEN
    )
    return ShadowEvaluation(
        should_close=True,
        close_reason=close_reason,
        exit_price=exit_price,
        result=result,
        pnl_points=pnl_points,
        net_pnl=net_pnl,
        r_multiple=net_pnl / risk_amount if risk_amount else Decimal("0"),
        mfe_points=mfe,
        mae_points=mae,
    )
