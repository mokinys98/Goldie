from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldie_domain import CandleInput, atr, bollinger_bands, ema, momentum, rsi, sma


def test_standard_indicator_values() -> None:
    values = [Decimal(value) for value in ("1", "2", "3", "4", "5")]

    assert sma(values, 3) == Decimal("4")
    assert ema(values, 3) == Decimal("4")
    assert rsi(values, 3) == Decimal("100")
    assert momentum(values, 2) == Decimal("2")
    bands = bollinger_bands(values, 3, Decimal("1"))
    assert bands is not None
    assert bands.middle == Decimal("4")
    assert bands.lower < bands.middle < bands.upper


def test_atr_uses_true_range() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        CandleInput(
            opened_at=start + timedelta(minutes=index),
            open=Decimal(str(10 + index)),
            high=Decimal(str(11 + index)),
            low=Decimal(str(9 + index)),
            close=Decimal(str(10 + index)),
            tick_volume=100 + index,
        )
        for index in range(4)
    ]

    assert atr(candles, 3) == Decimal("2")
    assert candles[-1].tick_volume == 103
