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
