from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from goldie_domain import (
    BotConfiguration,
    CandleInput,
    MarketContext,
    get_strategy,
    register_strategy,
    strategy_catalog,
)
from goldie_domain.strategies import PineBollingerRsiStochParameters
from pydantic import ValidationError


def ema_config(**parameters) -> BotConfiguration:
    values = {
        "fast_ema_period": 2,
        "slow_ema_period": 3,
        "rsi_period": 2,
        "buy_rsi_max": 100,
        "sell_rsi_min": 0,
        "min_trend_points": 0,
        "require_crossover": False,
        **parameters,
    }
    return BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {"name": "ema_rsi", "parameters": values},
            "filters": {"max_spread_points": 100, "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
            },
        }
    )


def market(closes: list[str]) -> MarketContext:
    observed = datetime(2026, 1, 5, 10, 10, tzinfo=UTC)
    candles = [
        CandleInput(
            opened_at=observed - timedelta(minutes=len(closes) - index),
            open=Decimal(value),
            high=Decimal(value) + Decimal("0.1"),
            low=Decimal(value) - Decimal("0.1"),
            close=Decimal(value),
            tick_volume=100,
        )
        for index, value in enumerate(closes)
    ]
    return MarketContext(
        observed_at=observed,
        evaluated_at=observed,
        bid=Decimal("10"),
        ask=Decimal("10.1"),
        point=Decimal("0.1"),
        candles=candles,
    )


def test_registry_catalog_and_duplicate_protection() -> None:
    catalog = strategy_catalog()
    names = [item["name"] for item in catalog]
    assert names == [
        "basic_momentum",
        "ema_rsi",
        "bb_rsi_mean_reversion",
        "ema_momentum_breakout",
        "ema_atr_trend",
        "bb_momentum_breakout",
        "bb_ema_rsi_mean_reversion",
        "range_break_scalper",
        "pine_bb_rsi_stoch",
    ]
    momentum = catalog[0]["parameters"]["min_momentum_points"]
    assert momentum["type"] == "number"
    assert momentum["exclusiveMinimum"] == 0
    with pytest.raises(ValueError, match="already registered"):
        register_strategy(get_strategy("basic_momentum"))
    with pytest.raises(ValueError, match="Unknown strategy"):
        get_strategy("missing")


def test_unknown_strategy_and_invalid_parameters_are_rejected() -> None:
    with pytest.raises(ValidationError):
        BotConfiguration.model_validate({"strategy": {"name": "missing", "parameters": {}}})
    with pytest.raises(ValidationError):
        ema_config(fast_ema_period=5, slow_ema_period=3)


def test_legacy_momentum_parameters_are_migrated() -> None:
    config = BotConfiguration.model_validate(
        {
            "strategy": {
                "name": "basic_momentum",
                "lookback_candles": 8,
                "min_momentum_points": 12,
            }
        }
    )
    assert config.strategy.parameters == {
        "lookback_candles": 8,
        "min_momentum_points": "12",
    }


def test_ema_rsi_buy_sell_and_insufficient_history() -> None:
    strategy = get_strategy("ema_rsi")
    buy = strategy.evaluate(market(["7", "8", "9", "10"]), ema_config())
    sell = strategy.evaluate(market(["13", "12", "11", "10"]), ema_config())
    insufficient = strategy.evaluate(market(["9", "10"]), ema_config())

    assert buy.signal == "BUY"
    assert buy.reason_code == "EMA_RSI_BUY"
    assert "fast_ema" in buy.inputs
    assert sell.signal == "SELL"
    assert sell.reason_code == "EMA_RSI_SELL"
    assert insufficient.signal == "NO_TRADE"
    assert insufficient.reason_code == "INSUFFICIENT_COMPLETED_CANDLES"


def test_ema_rsi_no_trade_when_thresholds_do_not_match() -> None:
    decision = get_strategy("ema_rsi").evaluate(
        market(["7", "8", "9", "10"]),
        ema_config(buy_rsi_max=50),
    )
    assert decision.signal == "NO_TRADE"
    assert decision.reason_code == "EMA_RSI_CONDITIONS_NOT_MET"


def pine_config() -> BotConfiguration:
    return BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "pine_bb_rsi_stoch",
                "parameters": {
                    "bollinger_period": 3,
                    "bollinger_deviations": "1",
                    "rsi_period": 2,
                    "rsi_overbought": "70",
                    "rsi_oversold": "30",
                    "stochastic_period": 2,
                    "stochastic_overbought": "80",
                    "stochastic_oversold": "20",
                    "smooth_k": 1,
                    "smooth_d": 1,
                },
            },
            "filters": {"max_spread_points": 100, "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
            },
        }
    )


def pine_config_with(**parameters) -> BotConfiguration:
    config = pine_config()
    config.strategy.parameters = {
        **config.strategy.parameters,
        **parameters,
    }
    return BotConfiguration.model_validate(config.model_dump(mode="json"))


def test_pine_port_generates_band_cross_signals() -> None:
    strategy = get_strategy("pine_bb_rsi_stoch")

    buy = strategy.evaluate(market(["10", "10", "10", "0"]), pine_config())
    sell = strategy.evaluate(market(["10", "10", "10", "20"]), pine_config())
    no_trade = strategy.evaluate(market(["10", "10", "10", "10"]), pine_config())

    assert buy.signal == "BUY"
    assert buy.reason_code == "PINE_BB_RSI_STOCH_BUY"
    assert sell.signal == "SELL"
    assert sell.reason_code == "PINE_BB_RSI_STOCH_SELL"
    assert no_trade.signal == "NO_TRADE"


def test_pine_direction_filter_blocks_opposite_side() -> None:
    strategy = get_strategy("pine_bb_rsi_stoch")

    buy_disabled = strategy.evaluate(
        market(["10", "10", "10", "0"]),
        pine_config_with(trade_direction="SELL_ONLY"),
    )
    sell_disabled = strategy.evaluate(
        market(["10", "10", "10", "20"]),
        pine_config_with(trade_direction="BUY_ONLY"),
    )

    assert buy_disabled.signal == "NO_TRADE"
    assert buy_disabled.reason_code == "PINE_BB_RSI_STOCH_BUY_DISABLED"
    assert sell_disabled.signal == "NO_TRADE"
    assert sell_disabled.reason_code == "PINE_BB_RSI_STOCH_SELL_DISABLED"


def test_pine_parameters_defaults_bounds_and_required_candles() -> None:
    strategy = get_strategy("pine_bb_rsi_stoch")
    defaults = PineBollingerRsiStochParameters()

    assert strategy.required_candles(defaults) == 21
    assert (
        strategy.required_candles(
            PineBollingerRsiStochParameters(
                bollinger_period=500,
                rsi_period=200,
                stochastic_period=200,
                smooth_k=20,
                smooth_d=20,
            )
        )
        == 501
    )
    with pytest.raises(ValidationError):
        PineBollingerRsiStochParameters(bollinger_deviations=0)
    with pytest.raises(ValidationError, match="rsi_oversold"):
        PineBollingerRsiStochParameters(rsi_oversold=70, rsi_overbought=60)
    with pytest.raises(ValidationError, match="stochastic_oversold"):
        PineBollingerRsiStochParameters(stochastic_oversold=90, stochastic_overbought=80)


def test_pine_strategy_guards_and_fast_factory() -> None:
    strategy = get_strategy("pine_bb_rsi_stoch")
    insufficient = strategy.evaluate(market(["10", "11", "12"]), pine_config())
    high_spread_market = market(["10", "10", "10", "20"])
    high_spread_market.ask = Decimal("30")
    spread = strategy.evaluate(high_spread_market, pine_config())
    outside_config = pine_config()
    outside_config.session.start_time = datetime.strptime("11:00", "%H:%M").time()
    outside_config.session.end_time = datetime.strptime("12:00", "%H:%M").time()
    outside = strategy.evaluate(market(["10", "10", "10", "20"]), outside_config)

    assert insufficient.reason_code == "INSUFFICIENT_COMPLETED_CANDLES"
    assert spread.reason_code == "SPREAD_TOO_HIGH"
    assert outside.reason_code == "OUTSIDE_TRADING_SESSION"
    assert callable(strategy.create_fast_backtest_evaluator)


@pytest.mark.parametrize(
    ("name", "parameters", "closes", "signal"),
    [
        (
            "bb_rsi_mean_reversion",
            {
                "bollinger_period": 4,
                "bollinger_deviations": "1",
                "rsi_period": 2,
                "buy_rsi_max": "100",
                "sell_rsi_min": "100",
                "atr_period": 2,
                "atr_stop_multiplier": "1.5",
                "require_touch_band": False,
            },
            ["10", "10", "10", "8"],
            "BUY",
        ),
        (
            "ema_momentum_breakout",
            {
                "fast_ema_period": 2,
                "medium_ema_period": 3,
                "slow_ema_period": 4,
                "momentum_period": 2,
                "min_momentum_points": "1",
                "atr_period": 2,
                "min_atr_points": "0",
            },
            ["6", "7", "8", "10"],
            "BUY",
        ),
        (
            "ema_atr_trend",
            {
                "fast_ema_period": 2,
                "slow_ema_period": 4,
                "atr_period": 2,
                "min_atr_points": "0",
                "max_atr_points": "100",
                "min_trend_points": "0",
                "atr_stop_multiplier": "1.5",
                "require_crossover": False,
            },
            ["6", "7", "8", "10"],
            "BUY",
        ),
        (
            "bb_momentum_breakout",
            {
                "bollinger_period": 4,
                "bollinger_deviations": "1",
                "momentum_period": 2,
                "min_momentum_points": "1",
                "atr_period": 2,
                "min_atr_points": "0",
            },
            ["10", "10", "10", "12"],
            "BUY",
        ),
        (
            "bb_ema_rsi_mean_reversion",
            {
                "bollinger_period": 4,
                "bollinger_deviations": "1",
                "rsi_period": 2,
                "buy_rsi_max": "100",
                "sell_rsi_min": "100",
                "atr_period": 2,
                "atr_stop_multiplier": "1.5",
                "require_touch_band": False,
                "fast_ema_period": 2,
                "slow_ema_period": 4,
                "max_trend_points": "100",
            },
            ["10", "10", "10", "8"],
            "BUY",
        ),
        (
            "range_break_scalper",
            {
                "fast_ema_period": 2,
                "slow_ema_period": 4,
                "rsi_period": 2,
                "buy_rsi_min": "50",
                "sell_rsi_max": "50",
                "range_lookback": 2,
                "min_breakout_points": "0",
            },
            ["8", "8", "9", "10"],
            "BUY",
        ),
    ],
)
def test_combo_algorithms_generate_expected_signal(
    name: str,
    parameters: dict,
    closes: list[str],
    signal: str,
) -> None:
    config = BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {"name": name, "parameters": parameters},
            "filters": {"max_spread_points": 100, "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
            },
        }
    )

    decision = get_strategy(name).evaluate(market(closes), config)

    assert decision.signal == signal
    assert decision.entry_price is not None
