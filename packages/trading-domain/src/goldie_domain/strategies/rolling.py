from collections import deque
from decimal import Decimal
from math import sqrt

from ..models import CandleInput


class RollingWindowEma:
    def __init__(
        self,
        *,
        period: int,
        window_size: int,
        track_previous: bool,
    ) -> None:
        self.period = period
        self.window_size = window_size
        self.track_previous = track_previous
        self.period_decimal = Decimal(period)
        self.alpha = Decimal("2") / Decimal(period + 1)
        self.beta = Decimal("1") - self.alpha
        self.tail_length = window_size - period
        self.beta_tail = self.beta**self.tail_length
        self.values: deque[Decimal] = deque(maxlen=window_size)
        self.seed_sum = Decimal("0")
        self.tail_weighted = Decimal("0")
        self.current: Decimal | None = None

    def update(self, value: Decimal) -> tuple[Decimal | None, Decimal | None]:
        if len(self.values) < self.window_size:
            self.values.append(value)
            if len(self.values) == self.window_size:
                self._initialize()
            previous = self.previous_in_window(value) if self.track_previous else None
            return self.current, previous

        old_first = self.values[0]
        if self.tail_length == 0:
            self.seed_sum += value - old_first
        else:
            old_tail_first = self.values[self.period]
            self.seed_sum += old_tail_first - old_first
            self.tail_weighted = (
                self.beta * self.tail_weighted
                - self.alpha * self.beta_tail * old_tail_first
                + self.alpha * value
            )
        self.values.append(value)
        self.current = self.beta_tail * self.seed_sum / self.period_decimal + self.tail_weighted
        previous = self.previous_in_window(value) if self.track_previous else None
        return self.current, previous

    def _initialize(self) -> None:
        values = list(self.values)
        self.seed_sum = sum(values[: self.period], Decimal("0"))
        self.tail_weighted = Decimal("0")
        for index, item in enumerate(values[self.period :]):
            exponent = self.tail_length - 1 - index
            self.tail_weighted += self.alpha * (self.beta**exponent) * item
        self.current = self.beta_tail * self.seed_sum / self.period_decimal + self.tail_weighted

    def previous_in_window(self, last_value: Decimal) -> Decimal | None:
        if self.current is None or self.tail_length == 0:
            return None
        return (self.current - self.alpha * last_value) / self.beta


class RollingRsi:
    def __init__(self, *, period: int) -> None:
        self.period = period
        self.period_decimal = Decimal(period)
        self.previous: Decimal | None = None
        self.changes: deque[Decimal] = deque(maxlen=period)
        self.gain = Decimal("0")
        self.loss = Decimal("0")

    def update(self, value: Decimal) -> Decimal | None:
        if self.previous is None:
            self.previous = value
            return None
        change = value - self.previous
        self.previous = value
        if len(self.changes) == self.period:
            removed = self.changes[0]
            if removed > 0:
                self.gain -= removed
            elif removed < 0:
                self.loss += removed
        self.changes.append(change)
        if change > 0:
            self.gain += change
        elif change < 0:
            self.loss -= change
        if len(self.changes) < self.period:
            return None
        average_gain = self.gain / self.period_decimal
        average_loss = self.loss / self.period_decimal
        if average_loss == 0:
            return Decimal("100") if average_gain > 0 else Decimal("50")
        strength = average_gain / average_loss
        return Decimal("100") - Decimal("100") / (Decimal("1") + strength)


class FastRollingEma:
    def __init__(self, *, period: int, window_size: int, track_previous: bool) -> None:
        self.period = period
        self.window_size = window_size
        self.track_previous = track_previous
        self.alpha = 2.0 / (period + 1)
        self.beta = 1.0 - self.alpha
        self.tail_length = window_size - period
        self.beta_tail = self.beta**self.tail_length
        self.values: deque[float] = deque(maxlen=window_size)
        self.seed_sum = 0.0
        self.tail_weighted = 0.0
        self.current: float | None = None

    def update(self, value: float) -> tuple[float | None, float | None]:
        if len(self.values) < self.window_size:
            self.values.append(value)
            if len(self.values) == self.window_size:
                values = list(self.values)
                self.seed_sum = sum(values[: self.period])
                self.tail_weighted = sum(
                    self.alpha * (self.beta ** (self.tail_length - 1 - index)) * item
                    for index, item in enumerate(values[self.period :])
                )
                self.current = self.beta_tail * self.seed_sum / self.period + self.tail_weighted
            return self.current, self._previous(value)

        old_first = self.values[0]
        if self.tail_length == 0:
            self.seed_sum += value - old_first
        else:
            old_tail_first = self.values[self.period]
            self.seed_sum += old_tail_first - old_first
            self.tail_weighted = (
                self.beta * self.tail_weighted
                - self.alpha * self.beta_tail * old_tail_first
                + self.alpha * value
            )
        self.values.append(value)
        self.current = self.beta_tail * self.seed_sum / self.period + self.tail_weighted
        return self.current, self._previous(value)

    def _previous(self, last_value: float) -> float | None:
        if not self.track_previous or self.current is None or self.tail_length == 0:
            return None
        return (self.current - self.alpha * last_value) / self.beta


class FastRollingRsi:
    def __init__(self, *, period: int) -> None:
        self.period = period
        self.previous: float | None = None
        self.changes: deque[float] = deque(maxlen=period)
        self.gain = 0.0
        self.loss = 0.0

    def update(self, value: float) -> float | None:
        if self.previous is None:
            self.previous = value
            return None
        change = value - self.previous
        self.previous = value
        if len(self.changes) == self.period:
            removed = self.changes[0]
            if removed > 0:
                self.gain -= removed
            elif removed < 0:
                self.loss += removed
        self.changes.append(change)
        if change > 0:
            self.gain += change
        elif change < 0:
            self.loss -= change
        if len(self.changes) < self.period:
            return None
        average_gain = self.gain / self.period
        average_loss = self.loss / self.period
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


class FastRollingBollinger:
    def __init__(self, *, period: int, deviations: float) -> None:
        self.period = period
        self.deviations = deviations
        self.values: deque[float] = deque(maxlen=period)
        self.total = 0.0
        self.total_squared = 0.0

    def update(self, value: float) -> tuple[float, float] | None:
        if len(self.values) == self.period:
            removed = self.values[0]
            self.total -= removed
            self.total_squared -= removed * removed
        self.values.append(value)
        self.total += value
        self.total_squared += value * value
        if len(self.values) < self.period:
            return None
        middle = self.total / self.period
        variance = max(0.0, self.total_squared / self.period - middle * middle)
        width = self.deviations * sqrt(variance)
        return middle - width, middle + width


class FastRollingAtr:
    def __init__(self, *, period: int) -> None:
        self.period = period
        self.previous_close: float | None = None
        self.ranges: deque[float] = deque(maxlen=period)
        self.total = 0.0

    def update(self, candle: CandleInput) -> float | None:
        high = float(candle.high)
        low = float(candle.low)
        close = float(candle.close)
        if self.previous_close is None:
            self.previous_close = close
            return None
        true_range = max(
            high - low,
            abs(high - self.previous_close),
            abs(low - self.previous_close),
        )
        self.previous_close = close
        if len(self.ranges) == self.period:
            self.total -= self.ranges[0]
        self.ranges.append(true_range)
        self.total += true_range
        return self.total / self.period if len(self.ranges) == self.period else None


class FastRollingMomentum:
    def __init__(self, *, period: int) -> None:
        self.values: deque[float] = deque(maxlen=period + 1)

    def update(self, value: float) -> float | None:
        self.values.append(value)
        return value - self.values[0] if len(self.values) == self.values.maxlen else None


class FastPriorRange:
    def __init__(self, *, period: int) -> None:
        self.period = period
        self.index = 0
        self.highs: deque[tuple[int, float]] = deque()
        self.lows: deque[tuple[int, float]] = deque()

    def update(self, candle: CandleInput) -> tuple[float, float] | None:
        cutoff = self.index - self.period
        while self.highs and self.highs[0][0] < cutoff:
            self.highs.popleft()
        while self.lows and self.lows[0][0] < cutoff:
            self.lows.popleft()
        prior = (self.highs[0][1], self.lows[0][1]) if self.index >= self.period else None
        high = float(candle.high)
        low = float(candle.low)
        while self.highs and self.highs[-1][1] <= high:
            self.highs.pop()
        while self.lows and self.lows[-1][1] >= low:
            self.lows.pop()
        self.highs.append((self.index, high))
        self.lows.append((self.index, low))
        self.index += 1
        return prior
