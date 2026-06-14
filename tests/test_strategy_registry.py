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
    assert names == ["basic_momentum", "ema_rsi"]
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
