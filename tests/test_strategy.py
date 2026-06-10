from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldie_domain import BasicMomentumStrategy, BotConfiguration, CandleInput, MarketContext


def context(
    closes: list[str],
    *,
    observed_at: datetime | None = None,
    spread: str = "0.20",
    include_incomplete: bool = False,
) -> MarketContext:
    now = observed_at or datetime.now(UTC)
    start = now.replace(second=0, microsecond=0) - timedelta(minutes=len(closes))
    candles = [
        CandleInput(
            opened_at=start + timedelta(minutes=index),
            open=Decimal(value),
            high=Decimal(value) + Decimal("0.10"),
            low=Decimal(value) - Decimal("0.10"),
            close=Decimal(value),
        )
        for index, value in enumerate(closes)
    ]
    if include_incomplete:
        candles.append(
            CandleInput(
                opened_at=now.replace(second=0, microsecond=0),
                open=Decimal("2400"),
                high=Decimal("2500"),
                low=Decimal("2300"),
                close=Decimal("2500"),
                is_complete=False,
            )
        )
    return MarketContext(
        observed_at=now,
        bid=Decimal("2350"),
        ask=Decimal("2350") + Decimal(spread),
        point=Decimal("0.01"),
        candles=candles,
    )


def always_open_config() -> BotConfiguration:
    return BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "basic_momentum",
                "lookback_candles": 5,
                "min_momentum_points": 50,
            },
            "filters": {"max_spread_points": 30, "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
            },
            "theoretical_trade": {
                "stop_loss_points": 70,
                "take_profit_points": 100,
            },
        }
    )


def test_buy_signal_is_deterministic() -> None:
    strategy = BasicMomentumStrategy()
    market = context(["2349", "2349.1", "2349.2", "2349.3", "2349.4", "2350"])
    first = strategy.evaluate(market, always_open_config())
    second = strategy.evaluate(market, always_open_config())

    assert first == second
    assert first.signal == "BUY"
    assert first.reason_code == "MOMENTUM_UP"
    assert first.entry_price == Decimal("2350.20")


def test_incomplete_candle_is_ignored() -> None:
    strategy = BasicMomentumStrategy()
    market = context(
        ["2350", "2350", "2350", "2350", "2350", "2350"],
        include_incomplete=True,
    )
    decision = strategy.evaluate(market, always_open_config())

    assert decision.signal == "NO_TRADE"
    assert decision.reason_code == "MOMENTUM_BELOW_THRESHOLD"


def test_stale_data_blocks_signal() -> None:
    market = context(
        ["2349", "2349.1", "2349.2", "2349.3", "2349.4", "2350"],
        observed_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    decision = BasicMomentumStrategy().evaluate(market, always_open_config())

    assert decision.signal == "NO_TRADE"
    assert decision.reason_code == "STALE_MARKET_DATA"


def test_spread_blocks_signal() -> None:
    market = context(
        ["2349", "2349.1", "2349.2", "2349.3", "2349.4", "2350"],
        spread="0.50",
    )
    decision = BasicMomentumStrategy().evaluate(market, always_open_config())

    assert decision.signal == "NO_TRADE"
    assert decision.reason_code == "SPREAD_TOO_HIGH"
