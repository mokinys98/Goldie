from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldie_domain import (
    BacktestCandle,
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


def ema_settings(*, require_crossover: bool) -> BotConfiguration:
    return BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "ema_rsi",
                "parameters": {
                    "fast_ema_period": 3,
                    "slow_ema_period": 7,
                    "rsi_period": 5,
                    "buy_rsi_max": "65",
                    "sell_rsi_min": "35",
                    "min_trend_points": "1",
                    "require_crossover": require_crossover,
                },
            },
            "filters": {"max_spread_points": "20", "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
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


def test_prepared_strategies_match_legacy_backtest_results() -> None:
    _, instrument, costs = settings()
    start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    candles = [
        CandleInput(
            opened_at=start + timedelta(minutes=index + (2 if index >= 80 else 0)),
            open=Decimal("100") + Decimal(index % 13) / Decimal("10"),
            high=Decimal("101") + Decimal(index % 17) / Decimal("10"),
            low=Decimal("99") + Decimal(index % 11) / Decimal("10"),
            close=Decimal("100") + Decimal((index * 7) % 19) / Decimal("10"),
        )
        for index in range(200)
    ]
    configs = [
        settings()[0],
        ema_settings(require_crossover=False),
        ema_settings(require_crossover=True),
    ]

    for config in configs:
        legacy = BacktestEngine().run(
            candles=candles,
            config=config,
            instrument=instrument,
            costs=costs,
            initial_capital=Decimal("10000"),
            use_prepared_strategy=False,
        )
        optimized = BacktestEngine().run(
            candles=candles,
            config=config,
            instrument=instrument,
            costs=costs,
            initial_capital=Decimal("10000"),
        )

        assert optimized == legacy


def test_prepared_combo_strategy_matches_legacy_backtest_result() -> None:
    _, instrument, costs = settings()
    start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    candles = [
        CandleInput(
            opened_at=start + timedelta(minutes=index),
            open=Decimal("100") + Decimal(index % 5) / Decimal("10"),
            high=Decimal("100.4") + Decimal(index % 7) / Decimal("10"),
            low=Decimal("99.6") - Decimal(index % 3) / Decimal("10"),
            close=Decimal("100") + Decimal((index * 3) % 11 - 5) / Decimal("10"),
        )
        for index in range(80)
    ]
    config = BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "bb_rsi_mean_reversion",
                "parameters": {
                    "bollinger_period": 10,
                    "bollinger_deviations": "1.5",
                    "rsi_period": 7,
                    "buy_rsi_max": "45",
                    "sell_rsi_min": "55",
                    "atr_period": 7,
                    "atr_stop_multiplier": "1.5",
                    "require_touch_band": True,
                },
            },
            "filters": {"max_spread_points": "20", "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
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

    legacy = BacktestEngine().run(
        candles=candles,
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
        use_prepared_strategy=False,
    )
    prepared = BacktestEngine().run(
        candles=candles,
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
    )

    assert prepared == legacy


def test_run_stream_consumes_generator_and_reports_final_progress() -> None:
    config, instrument, costs = settings()
    candles = [
        candle(0, "100", "100.2", "99.8", "100"),
        candle(1, "100", "100.3", "99.9", "100.2"),
        candle(2, "100.2", "100.6", "100.1", "100.5"),
        candle(3, "101.0", "102.2", "100.8", "102"),
    ]
    progress = []

    result = BacktestEngine().run_stream(
        candles=(item for item in candles),
        total_candles=len(candles),
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
        progress_callback=lambda processed, total: (
            progress.append((processed, total)) or True
        ),
    )

    assert result.trades
    assert progress[-1] == (len(candles), len(candles))


def test_run_stream_accepts_lightweight_candles_for_combo_strategies() -> None:
    _, instrument, costs = settings()
    config = ema_settings(require_crossover=False)
    config.strategy.name = "range_break_scalper"
    config.strategy.parameters = {
        "fast_ema_period": 3,
        "slow_ema_period": 7,
        "rsi_period": 5,
        "buy_rsi_min": "55",
        "sell_rsi_max": "45",
        "range_lookback": 5,
        "min_breakout_points": "1",
    }
    start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    candles = [
        BacktestCandle(
            opened_at=start + timedelta(minutes=index),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100") + Decimal(index % 3) / Decimal("10"),
        )
        for index in range(30)
    ]

    result = BacktestEngine().run_stream(
        candles=iter(candles),
        total_candles=len(candles),
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
    )

    assert isinstance(result.reason_counts, dict)
