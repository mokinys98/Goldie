from dataclasses import dataclass
from decimal import Decimal

from .models import CandleInput


def sma(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:], Decimal("0")) / Decimal(period)


def ema_series(values: list[Decimal], period: int) -> list[Decimal]:
    if period <= 0 or len(values) < period:
        return []
    seed = sum(values[:period], Decimal("0")) / Decimal(period)
    multiplier = Decimal("2") / Decimal(period + 1)
    result = [seed]
    for value in values[period:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def ema(values: list[Decimal], period: int) -> Decimal | None:
    series = ema_series(values, period)
    return series[-1] if series else None


def rsi(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) < period + 1:
        return None
    changes = [right - left for left, right in zip(values, values[1:], strict=False)]
    gains = [max(change, Decimal("0")) for change in changes[-period:]]
    losses = [max(-change, Decimal("0")) for change in changes[-period:]]
    average_gain = sum(gains, Decimal("0")) / Decimal(period)
    average_loss = sum(losses, Decimal("0")) / Decimal(period)
    if average_loss == 0:
        return Decimal("100") if average_gain > 0 else Decimal("50")
    strength = average_gain / average_loss
    return Decimal("100") - Decimal("100") / (Decimal("1") + strength)


def atr(candles: list[CandleInput], period: int) -> Decimal | None:
    if period <= 0 or len(candles) < period + 1:
        return None
    ranges = []
    for previous, current in zip(candles, candles[1:], strict=False):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sma(ranges, period)


@dataclass(frozen=True)
class BollingerBands:
    lower: Decimal
    middle: Decimal
    upper: Decimal


def bollinger_bands(
    values: list[Decimal],
    period: int,
    deviations: Decimal = Decimal("2"),
) -> BollingerBands | None:
    middle = sma(values, period)
    if middle is None:
        return None
    window = values[-period:]
    variance = sum(((value - middle) ** 2 for value in window), Decimal("0")) / Decimal(
        period
    )
    standard_deviation = variance.sqrt()
    return BollingerBands(
        lower=middle - deviations * standard_deviation,
        middle=middle,
        upper=middle + deviations * standard_deviation,
    )


def momentum(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) < period + 1:
        return None
    return values[-1] - values[-(period + 1)]


def percent_change(values: list[Decimal], period: int) -> Decimal | None:
    change = momentum(values, period)
    if change is None:
        return None
    baseline = values[-(period + 1)]
    return change / baseline * Decimal("100") if baseline else None
