from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldie_domain import (
    ShadowCloseReason,
    ShadowResult,
    calculate_position_size,
    evaluate_shadow_position,
)

NOW = datetime(2026, 6, 11, 10, 0, tzinfo=UTC)


def evaluate(**overrides):
    values = {
        "direction": "BUY",
        "entry_price": Decimal("2350.20"),
        "stop_loss": Decimal("2349.50"),
        "take_profit": Decimal("2351.20"),
        "volume": Decimal("0.10"),
        "risk_amount": Decimal("7.00"),
        "point": Decimal("0.01"),
        "tick_size": Decimal("0.01"),
        "tick_value": Decimal("1.00"),
        "opened_at": NOW,
        "last_evaluated_at": NOW,
        "tick_at": NOW + timedelta(seconds=2),
        "bid": Decimal("2350.40"),
        "ask": Decimal("2350.60"),
        "max_duration_minutes": 5,
        "stale_after_seconds": 15,
    }
    values.update(overrides)
    return evaluate_shadow_position(**values)


def test_position_size_is_floored_to_broker_step() -> None:
    size = calculate_position_size(
        balance=Decimal("2500"),
        equity=Decimal("2400"),
        risk_per_trade_pct=Decimal("0.25"),
        entry_price=Decimal("2350.20"),
        stop_loss=Decimal("2349.50"),
        tick_size=Decimal("0.01"),
        tick_value=Decimal("1"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("100"),
        volume_step=Decimal("0.01"),
    )

    assert size is not None
    assert size.volume == Decimal("0.08")
    assert size.risk_amount == Decimal("5.60")


def test_position_size_rejects_below_minimum_volume() -> None:
    size = calculate_position_size(
        balance=Decimal("100"),
        equity=Decimal("100"),
        risk_per_trade_pct=Decimal("0.25"),
        entry_price=Decimal("2350"),
        stop_loss=Decimal("2340"),
        tick_size=Decimal("0.01"),
        tick_value=Decimal("1"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("100"),
        volume_step=Decimal("0.01"),
    )

    assert size is None


def test_buy_take_profit_and_sell_stop_loss() -> None:
    buy = evaluate(bid=Decimal("2351.30"), ask=Decimal("2351.50"))
    sell = evaluate(
        direction="SELL",
        entry_price=Decimal("2350.00"),
        stop_loss=Decimal("2350.70"),
        take_profit=Decimal("2349.00"),
        bid=Decimal("2350.60"),
        ask=Decimal("2350.80"),
    )

    assert buy.close_reason == ShadowCloseReason.TAKE_PROFIT
    assert buy.result == ShadowResult.WIN
    assert buy.pnl_points == Decimal("100")
    assert sell.close_reason == ShadowCloseReason.STOP_LOSS
    assert sell.result == ShadowResult.LOSS


def test_timeout_can_close_at_breakeven() -> None:
    result = evaluate(
        last_evaluated_at=NOW + timedelta(minutes=4, seconds=59),
        tick_at=NOW + timedelta(minutes=5),
        bid=Decimal("2350.20"),
        ask=Decimal("2350.40"),
    )

    assert result.close_reason == ShadowCloseReason.TIMEOUT
    assert result.result == ShadowResult.BREAKEVEN
    assert result.net_pnl == 0


def test_mfe_and_mae_accumulate_across_ticks() -> None:
    favorable = evaluate(bid=Decimal("2350.70"), ask=Decimal("2350.90"))
    adverse = evaluate(
        last_evaluated_at=NOW + timedelta(seconds=2),
        tick_at=NOW + timedelta(seconds=4),
        bid=Decimal("2349.90"),
        ask=Decimal("2350.10"),
        current_mfe_points=favorable.mfe_points,
        current_mae_points=favorable.mae_points,
    )

    assert favorable.should_close is False
    assert adverse.should_close is False
    assert adverse.mfe_points == Decimal("50")
    assert adverse.mae_points == Decimal("30")


def test_data_gap_is_conservative_loss_even_if_price_reaches_target() -> None:
    result = evaluate(
        tick_at=NOW + timedelta(seconds=30),
        bid=Decimal("2352.00"),
        ask=Decimal("2352.20"),
    )

    assert result.close_reason == ShadowCloseReason.DATA_GAP
    assert result.result == ShadowResult.LOSS
    assert result.exit_price == Decimal("2349.50")


def test_repeated_or_older_tick_does_not_need_second_close() -> None:
    result = evaluate(
        last_evaluated_at=NOW + timedelta(seconds=5),
        tick_at=NOW + timedelta(seconds=5),
    )

    assert result.should_close is False
