from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldie_domain import (
    BacktestCosts,
    BacktestEngine,
    BacktestInstrument,
    BotConfiguration,
    CandleInput,
)


def candle(minute: int, open_: str, high: str, low: str, close: str) -> CandleInput:
    return CandleInput(
        opened_at=datetime(2026, 1, 5, 10, minute, tzinfo=UTC),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def settings() -> tuple[BotConfiguration, BacktestInstrument, BacktestCosts]:
    config = BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "basic_momentum",
                "lookback_candles": 2,
                "min_momentum_points": "2",
            },
            "filters": {"max_spread_points": "20", "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:00",
            },
            "theoretical_trade": {
                "stop_loss_points": "5",
                "take_profit_points": "8",
                "risk_per_trade_pct": "1",
                "max_trade_duration_minutes": 5,
                "max_open_shadow_positions": 1,
            },
        }
    )
    instrument = BacktestInstrument(
        point=Decimal("0.1"),
        tick_size=Decimal("0.1"),
        tick_value=Decimal("0.1"),
        volume_min=Decimal("1"),
        volume_max=Decimal("100000"),
        volume_step=Decimal("1"),
    )
    costs = BacktestCosts(
        spread_points=Decimal("2"),
        slippage_points=Decimal("1"),
        commission_per_trade=Decimal("1"),
    )
    return config, instrument, costs


def test_signal_opens_only_on_next_candle_and_is_deterministic() -> None:
    config, instrument, costs = settings()
    candles = [
        candle(0, "100", "100.2", "99.8", "100"),
        candle(1, "100", "100.3", "99.9", "100.2"),
        candle(2, "100.2", "100.6", "100.1", "100.5"),
        candle(3, "101.0", "102.2", "100.8", "102"),
    ]
    engine = BacktestEngine()
    first = engine.run(
        candles=candles,
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
    )
    second = engine.run(
        candles=candles,
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
    )
    assert first == second
    assert first.trades[0].signal_at == candles[2].opened_at + timedelta(minutes=1)
    assert first.trades[0].opened_at == candles[3].opened_at


def test_same_candle_stop_and_take_uses_stop_first() -> None:
    config, instrument, costs = settings()
    candles = [
        candle(0, "100", "100.1", "99.9", "100"),
        candle(1, "100", "100.3", "99.9", "100.2"),
        candle(2, "100.2", "100.6", "100.1", "100.5"),
        candle(3, "100.5", "102", "99", "100.5"),
    ]
    result = BacktestEngine().run(
        candles=candles,
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
    )
    assert result.trades[0].close_reason == "STOP_LOSS"
    assert result.trades[0].net_pnl < 0


def test_gap_closes_open_position_and_counts_reason() -> None:
    config, instrument, costs = settings()
    candles = [
        candle(0, "100", "100.1", "99.9", "100"),
        candle(1, "100", "100.3", "99.9", "100.2"),
        candle(2, "100.2", "100.6", "100.1", "100.5"),
        candle(3, "100.5", "100.7", "100.4", "100.6"),
        CandleInput(
            opened_at=datetime(2026, 1, 5, 10, 6, tzinfo=UTC),
            open=Decimal("100.6"),
            high=Decimal("100.7"),
            low=Decimal("100.5"),
            close=Decimal("100.6"),
        ),
    ]
    result = BacktestEngine().run(
        candles=candles,
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
    )
    assert result.trades[0].close_reason == "DATA_GAP"
    assert result.reason_counts["DATA_GAP"] == 1
