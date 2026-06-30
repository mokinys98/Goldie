from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from goldie_domain import (
    BacktestCandle,
    BacktestCosts,
    BacktestEngine,
    BacktestInstrument,
    BotConfiguration,
    CandleInput,
    InvalidBacktestResult,
    get_strategy,
)
from goldie_domain.backtest import _OpenPosition


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
        slippage_points=Decimal("0"),
        commission_per_trade=Decimal("0"),
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
    assert first.trades[0].signal_reason == "MOMENTUM_UP"
    assert first.trades[0].mfe_points >= 0
    assert first.trades[0].mae_points >= 0


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


def test_theoretical_stop_loss_rejects_loss_below_minus_1_05r() -> None:
    position = _OpenPosition(
        direction="BUY",
        signal_reason="TEST",
        signal_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        opened_at=datetime(2026, 1, 5, 10, 1, tzinfo=UTC),
        entry_price=Decimal("100"),
        stop_loss=Decimal("99"),
        take_profit=Decimal("102"),
        volume=Decimal("1"),
        risk_amount=Decimal("1"),
    )
    instrument = BacktestInstrument(
        point=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        tick_value=Decimal("0.01"),
        volume_min=Decimal("1"),
        volume_max=Decimal("1"),
        volume_step=Decimal("1"),
    )

    with pytest.raises(InvalidBacktestResult, match="below -1.05R"):
        BacktestEngine._close(
            position,
            closed_at=datetime(2026, 1, 5, 10, 2, tzinfo=UTC),
            raw_exit=position.stop_loss,
            close_reason="STOP_LOSS",
            instrument=instrument,
            costs=BacktestCosts(slippage_points=Decimal("10")),
        )


def test_theoretical_take_profit_rejects_profit_above_configured_ratio() -> None:
    position = _OpenPosition(
        direction="BUY",
        signal_reason="TEST",
        signal_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        opened_at=datetime(2026, 1, 5, 10, 1, tzinfo=UTC),
        entry_price=Decimal("100"),
        stop_loss=Decimal("99"),
        take_profit=Decimal("102"),
        volume=Decimal("1"),
        risk_amount=Decimal("0.9"),
    )
    instrument = BacktestInstrument(
        point=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        tick_value=Decimal("0.01"),
        volume_min=Decimal("1"),
        volume_max=Decimal("1"),
        volume_step=Decimal("1"),
    )

    with pytest.raises(InvalidBacktestResult, match="exceeds 2.05R"):
        BacktestEngine._close(
            position,
            closed_at=datetime(2026, 1, 5, 10, 2, tzinfo=UTC),
            raw_exit=position.take_profit,
            close_reason="TAKE_PROFIT",
            instrument=instrument,
            costs=BacktestCosts(fill_mode="perfect"),
        )


def test_btc_stop_loss_points_convert_to_price_distance() -> None:
    config, _, _ = settings()
    payload = config.model_dump(mode="python")
    payload["theoretical_trade"]["stop_loss_points"] = Decimal("22.5")
    payload["theoretical_trade"]["take_profit_points"] = Decimal("37.5")
    btc_config = BotConfiguration.model_validate(payload)
    instrument = BacktestInstrument(
        point=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        tick_value=Decimal("0.01"),
        volume_min=Decimal("0.00001"),
        volume_max=Decimal("100"),
        volume_step=Decimal("0.00001"),
    )
    opened = BacktestEngine()._open(
        direction="BUY",
        signal_reason="TEST",
        signal_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        candle=candle(1, "60000", "60001", "59999", "60000"),
        config=btc_config,
        instrument=instrument,
        costs=BacktestCosts(fill_mode="perfect", spread_points=Decimal("0")),
        balance=Decimal("10000"),
    )

    assert opened is not None
    assert opened.entry_price - opened.stop_loss == Decimal("0.225")
    assert opened.take_profit - opened.entry_price == Decimal("0.375")


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
        fast = BacktestEngine().run(
            candles=candles,
            config=config,
            instrument=instrument,
            costs=costs,
            initial_capital=Decimal("10000"),
            use_fast_strategy=True,
        )

        assert optimized == legacy
        assert fast == legacy


def test_fast_combo_strategies_match_prepared_backtest_results() -> None:
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
    strategy_names = (
        "bb_rsi_mean_reversion",
        "ema_momentum_breakout",
        "ema_atr_trend",
        "bb_momentum_breakout",
        "bb_ema_rsi_mean_reversion",
        "range_break_scalper",
        "pine_bb_rsi_stoch",
        "fvg_ma_volume_profile",
    )
    for strategy_name in strategy_names:
        strategy = get_strategy(strategy_name)
        config = BotConfiguration.model_validate(
            {
                "market": {"symbol": "XAUUSD", "timeframe": "M1"},
                "strategy": {
                    "name": strategy_name,
                    "parameters": strategy.parameters_model().model_dump(mode="json"),
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

        prepared = BacktestEngine().run(
            candles=candles,
            config=config,
            instrument=instrument,
            costs=costs,
            initial_capital=Decimal("10000"),
        )
        fast = BacktestEngine().run(
            candles=candles,
            config=config,
            instrument=instrument,
            costs=costs,
            initial_capital=Decimal("10000"),
            use_fast_strategy=True,
        )

        assert fast == prepared, strategy_name


def pine_backtest_config(parameters: dict | None = None) -> BotConfiguration:
    strategy = get_strategy("pine_bb_rsi_stoch")
    return BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "pine_bb_rsi_stoch",
                "parameters": parameters or strategy.parameters_model().model_dump(mode="json"),
            },
            "filters": {"max_spread_points": "20", "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
            },
            "theoretical_trade": {
                "stop_loss_points": "50",
                "take_profit_points": "80",
                "risk_per_trade_pct": "1",
                "max_trade_duration_minutes": 60,
                "max_open_shadow_positions": 1,
            },
        }
    )


def pine_candles(*, count: int, scale: Decimal, point: Decimal) -> list[CandleInput]:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    result = []
    for index in range(count):
        wave = Decimal((index * 17) % 31 - 15) * point
        trend = Decimal(index % 97) * point / Decimal("10")
        close = scale + wave + trend
        open_price = close - Decimal((index % 5) - 2) * point
        result.append(
            CandleInput(
                opened_at=start + timedelta(minutes=index),
                open=open_price,
                high=max(open_price, close) + point * 3,
                low=min(open_price, close) - point * 3,
                close=close,
            )
        )
    return result


def test_pine_prepared_and_fast_parity_matrix() -> None:
    _, base_instrument, costs = settings()
    parameter_sets = [
        None,
        {
            "bollinger_period": 2,
            "bollinger_deviations": "0.1",
            "rsi_period": 2,
            "rsi_overbought": "100",
            "rsi_oversold": "0",
            "stochastic_period": 1,
            "stochastic_overbought": "100",
            "stochastic_oversold": "0",
            "smooth_k": 1,
            "smooth_d": 1,
        },
        {
            "bollinger_period": 500,
            "bollinger_deviations": "10",
            "rsi_period": 200,
            "rsi_overbought": "100",
            "rsi_oversold": "0",
            "stochastic_period": 200,
            "stochastic_overbought": "100",
            "stochastic_oversold": "0",
            "smooth_k": 20,
            "smooth_d": 20,
        },
    ]
    markets = [
        (Decimal("1.08"), Decimal("0.00001")),
        (Decimal("155"), Decimal("0.001")),
        (Decimal("2350"), Decimal("0.01")),
    ]
    for parameters in parameter_sets:
        for scale, point in markets:
            instrument = BacktestInstrument(
                point=point,
                tick_size=point,
                tick_value=base_instrument.tick_value,
                volume_min=base_instrument.volume_min,
                volume_max=base_instrument.volume_max,
                volume_step=base_instrument.volume_step,
            )
            candles = pine_candles(count=650, scale=scale, point=point)
            reference = BacktestEngine().run(
                candles=candles,
                config=pine_backtest_config(parameters),
                instrument=instrument,
                costs=costs,
                initial_capital=Decimal("10000"),
                use_prepared_strategy=False,
            )
            prepared = BacktestEngine().run(
                candles=candles,
                config=pine_backtest_config(parameters),
                instrument=instrument,
                costs=costs,
                initial_capital=Decimal("10000"),
            )
            fast = BacktestEngine().run(
                candles=candles,
                config=pine_backtest_config(parameters),
                instrument=instrument,
                costs=costs,
                initial_capital=Decimal("10000"),
                use_fast_strategy=True,
            )
            assert prepared == reference, (parameters, scale, "prepared")
            assert fast == reference, (parameters, scale, "fast")


def test_pine_parity_across_price_patterns() -> None:
    _, instrument, costs = settings()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    patterns = {
        "rising": [Decimal(index) for index in range(120)],
        "falling": [Decimal(120 - index) for index in range(120)],
        "flat": [Decimal("50") for _ in range(120)],
        "noisy": [Decimal((index * 19) % 37) for index in range(120)],
    }
    for name, values in patterns.items():
        candles = [
            CandleInput(
                opened_at=start + timedelta(minutes=index),
                open=Decimal("100") + value / Decimal("10"),
                high=Decimal("100.3") + value / Decimal("10"),
                low=Decimal("99.7") + value / Decimal("10"),
                close=Decimal("100") + value / Decimal("10"),
            )
            for index, value in enumerate(values)
        ]
        results = [
            BacktestEngine().run(
                candles=candles,
                config=pine_backtest_config(),
                instrument=instrument,
                costs=costs,
                initial_capital=Decimal("10000"),
                use_prepared_strategy=prepared,
                use_fast_strategy=fast,
            )
            for prepared, fast in ((False, False), (True, False), (True, True))
        ]
        assert results[1] == results[0], (name, "prepared")
        assert results[2] == results[0], (name, "fast")


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
        progress_callback=lambda processed, total: progress.append((processed, total)) or True,
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


def test_ema_atr_fast_backtest_reports_condition_counts_after_warmup() -> None:
    _, instrument, costs = settings()
    strategy = get_strategy("ema_atr_pullback_continuation")
    config = BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "ema_atr_pullback_continuation",
                "parameters": strategy.parameters_model().model_dump(mode="json"),
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
    start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    candles = [
        CandleInput(
            opened_at=start + timedelta(minutes=index),
            open=Decimal("100") + Decimal(index) / Decimal("10"),
            high=Decimal("100.4") + Decimal(index) / Decimal("10"),
            low=Decimal("99.6") + Decimal(index) / Decimal("10"),
            close=Decimal("100.2") + Decimal(index) / Decimal("10"),
        )
        for index in range(80)
    ]

    result = BacktestEngine().run(
        candles=candles,
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
        use_fast_strategy=True,
    )

    required = strategy.required_candles(strategy.parameters_model())
    assert result.condition_counts["volatility_ok"]["evaluated"] == len(candles) - required + 1
    assert result.condition_counts["signal_ready"]["evaluated"] == len(candles) - required + 1
    assert set(result.condition_counts["trend_ok"]) == {"evaluated", "passed"}


def test_perfect_fill_has_no_slippage_or_commission() -> None:
    _, instrument, _ = settings()
    costs = BacktestCosts(
        fill_mode="perfect",
        fee_taker=Decimal("0.01"),
        taker_slippage=Decimal("0.5"),
        slippage_small=Decimal("0.5"),
        medium_impact=Decimal("0.5"),
    )

    assert BacktestEngine._slippage_amount(costs, instrument, Decimal("100")) == 0
    assert (
        BacktestEngine._commission_amount(
            costs=costs,
            entry_price=Decimal("100"),
            exit_price=Decimal("101"),
            volume=Decimal("10"),
        )
        == 0
    )


def test_simulated_fill_applies_fee_and_slippage() -> None:
    _, instrument, _ = settings()
    costs = BacktestCosts(
        fill_mode="simulated",
        fee_taker=Decimal("0.001"),
        taker_slippage=Decimal("0.1"),
        slippage_small=Decimal("0.2"),
        medium_impact=Decimal("0.3"),
        model_sqrt_limit=Decimal("1"),
    )

    slippage = BacktestEngine._slippage_amount(costs, instrument, Decimal("4"))
    commission = BacktestEngine._commission_amount(
        costs=costs,
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        volume=Decimal("10"),
    )

    assert slippage > costs.slippage_small
    assert commission == Decimal("2.010")


def test_min_qty_threshold_rejects_small_position() -> None:
    config, instrument, costs = settings()
    costs = BacktestCosts(
        spread_points=costs.spread_points,
        fill_mode="simulated",
        min_qty_check=True,
        min_qty_threshold=Decimal("1000000"),
    )
    result = BacktestEngine().run(
        candles=[
            candle(0, "100", "100.2", "99.8", "100"),
            candle(1, "100", "100.3", "99.9", "100.2"),
            candle(2, "100.2", "100.6", "100.1", "100.5"),
            candle(3, "101.0", "102.2", "100.8", "102"),
        ],
        config=config,
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
    )

    assert result.trades == []
    assert result.reason_counts["INVALID_POSITION_SIZE"] == 1


def test_model_sqrt_limit_caps_impact() -> None:
    _, instrument, _ = settings()
    costs = BacktestCosts(
        fill_mode="simulated",
        taker_slippage=Decimal("0"),
        slippage_small=Decimal("0"),
        medium_impact=Decimal("0.1"),
        model_sqrt_limit=Decimal("0.7"),
    )

    assert BacktestEngine._slippage_amount(costs, instrument, Decimal("1000000")) == Decimal("0.07")
