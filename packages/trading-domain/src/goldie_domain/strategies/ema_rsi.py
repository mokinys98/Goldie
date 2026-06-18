from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import ema_series, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import (
    BacktestGuards,
    common_guard,
    completed,
    trade_prices,
)


class EmaRsiParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=9, ge=2, le=200, description="Greitos EMA periodas.", json_schema_extra={"unit": "candles", "impact": "Mažinant EMA greičiau reaguoja į kainą."})
    slow_ema_period: int = Field(default=21, ge=3, le=500, description="Lėtos EMA periodas.", json_schema_extra={"unit": "candles", "impact": "Didinant bazinė tendencija tampa lygesnė."})
    rsi_period: int = Field(default=14, ge=2, le=200, description="RSI indikatoriaus skaičiavimo periodas.", json_schema_extra={"unit": "candles", "impact": "Didinant RSI tampa mažiau jautrus trumpiems pokyčiams."})
    buy_rsi_max: Decimal = Field(default=Decimal("70"), ge=0, le=100, description="Didžiausia RSI reikšmė, prie kurios leidžiamas BUY.", json_schema_extra={"unit": "RSI", "impact": "Mažinant BUY filtras griežtėja."})
    sell_rsi_min: Decimal = Field(default=Decimal("30"), ge=0, le=100, description="Mažiausia RSI reikšmė, prie kurios leidžiamas SELL.", json_schema_extra={"unit": "RSI", "impact": "Didinant SELL filtras griežtėja."})
    min_trend_points: Decimal = Field(default=Decimal("0"), ge=0, le=10000, description="Mažiausias atstumas tarp greitos ir lėtos EMA.", json_schema_extra={"unit": "points", "impact": "Didinant reikalaujama stipresnės tendencijos."})
    require_crossover: bool = Field(default=False, description="Reikalauja, kad EMA susikirtimas įvyktų paskutinėje žvakėje.", json_schema_extra={"unit": "boolean", "impact": "Įjungus signalai tampa retesni ir priklauso nuo naujo susikirtimo."})

    @model_validator(mode="after")
    def validate_periods(self) -> "EmaRsiParameters":
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be lower than slow_ema_period")
        return self


class EmaRsiStrategy:
    name = "ema_rsi"
    description = "Combines fast/slow EMA trend with an RSI threshold."
    parameters_model = EmaRsiParameters

    def required_candles(self, parameters: BaseModel) -> int:
        values = EmaRsiParameters.model_validate(parameters)
        crossover_extra = 1 if values.require_crossover else 0
        return max(values.slow_ema_period + crossover_extra, values.rsi_period + 1)

    def create_backtest_evaluator(
        self,
        config: Any,
        *,
        point: Decimal,
        spread_points: Decimal,
    ) -> "_EmaRsiBacktestEvaluator":
        parameters = EmaRsiParameters.model_validate(config.strategy.parameters)
        return _EmaRsiBacktestEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def create_fast_backtest_evaluator(
        self,
        config: Any,
        *,
        point: Decimal,
        spread_points: Decimal,
    ) -> "_FastEmaRsiBacktestEvaluator":
        parameters = EmaRsiParameters.model_validate(config.strategy.parameters)
        return _FastEmaRsiBacktestEvaluator(
            parameters=parameters,
            point=float(point),
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles = completed(context)
        parameters = EmaRsiParameters.model_validate(config.strategy.parameters)
        inputs: dict[str, str | int | bool | None] = {
            "strategy": self.name,
            "complete_candles": len(candles),
            "fast_ema_period": parameters.fast_ema_period,
            "slow_ema_period": parameters.slow_ema_period,
            "rsi_period": parameters.rsi_period,
            "require_crossover": parameters.require_crossover,
        }
        guard = common_guard(context, config, inputs)
        if isinstance(guard, SignalDecision):
            return guard
        if len(candles) < self.required_candles(parameters):
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                reason_code="INSUFFICIENT_COMPLETED_CANDLES",
                **guard,
            )
        closes = [candle.close for candle in candles]
        fast_values = ema_series(closes, parameters.fast_ema_period)
        slow_values = ema_series(closes, parameters.slow_ema_period)
        fast = fast_values[-1]
        slow = slow_values[-1]
        rsi_value = rsi(closes, parameters.rsi_period)
        assert rsi_value is not None
        trend_points = (fast - slow) / context.point
        inputs.update(
            {
                "fast_ema": str(fast),
                "slow_ema": str(slow),
                "rsi": str(rsi_value),
                "trend_points": str(trend_points),
            }
        )
        crossed_up = crossed_down = True
        if parameters.require_crossover:
            previous_fast = fast_values[-2]
            previous_slow = slow_values[-2]
            crossed_up = previous_fast <= previous_slow and fast > slow
            crossed_down = previous_fast >= previous_slow and fast < slow
            inputs["crossed_up"] = crossed_up
            inputs["crossed_down"] = crossed_down
        if (
            trend_points >= parameters.min_trend_points
            and rsi_value <= parameters.buy_rsi_max
            and crossed_up
        ):
            signal, reason = SignalType.BUY, "EMA_RSI_BUY"
        elif (
            trend_points <= -parameters.min_trend_points
            and rsi_value >= parameters.sell_rsi_min
            and crossed_down
        ):
            signal, reason = SignalType.SELL, "EMA_RSI_SELL"
        else:
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                reason_code="EMA_RSI_CONDITIONS_NOT_MET",
                **guard,
            )
        entry, stop_loss, take_profit = trade_prices(signal, context, config)
        return SignalDecision(
            signal=signal,
            reason_code=reason,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            **guard,
        )


def _ema_tail(
    values: deque[Decimal],
    period: int,
    period_decimal: Decimal,
    multiplier: Decimal,
) -> tuple[Decimal, Decimal | None]:
    # Preserve the legacy bounded-window Decimal operation order exactly.
    iterator = iter(values)
    seed = Decimal("0")
    for _ in range(period):
        seed += next(iterator)
    current = seed / period_decimal
    previous = None
    for value in iterator:
        previous = current
        current = (value - current) * multiplier + current
    return current, previous


def _rsi_tail(
    values: deque[Decimal],
    period: int,
    period_decimal: Decimal,
) -> Decimal:
    iterator = iter(values)
    previous = next(iterator)
    skip = len(values) - period - 1
    gain = Decimal("0")
    loss = Decimal("0")
    for index, current in enumerate(iterator):
        if index >= skip:
            change = current - previous
            if change > 0:
                gain += change
            elif change < 0:
                loss -= change
        previous = current
    average_gain = gain / period_decimal
    average_loss = loss / period_decimal
    if average_loss == 0:
        return Decimal("100") if average_gain > 0 else Decimal("50")
    strength = average_gain / average_loss
    return Decimal("100") - Decimal("100") / (Decimal("1") + strength)


class _RollingWindowEma:
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


class _RollingRsi:
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


class _FastRollingEma:
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
                self.current = (
                    self.beta_tail * self.seed_sum / self.period + self.tail_weighted
                )
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


class _FastRollingRsi:
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


class _FastEmaRsiBacktestEvaluator:
    def __init__(
        self,
        *,
        parameters: EmaRsiParameters,
        point: float,
        guards: BacktestGuards,
    ) -> None:
        self.parameters = parameters
        self.point = point
        self.guards = guards
        self.skip_guards = (
            guards.spread_points <= guards.max_spread_points
            and guards.timezone.key == "UTC"
            and guards.start_time == datetime.min.time()
            and guards.end_time >= datetime.max.time().replace(microsecond=0)
        )
        crossover_extra = 1 if parameters.require_crossover else 0
        self.required = max(
            parameters.slow_ema_period + crossover_extra,
            parameters.rsi_period + 1,
        )
        self.count = 0
        self.fast_ema = _FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.slow_ema = _FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.rsi = _FastRollingRsi(period=parameters.rsi_period)
        self.min_trend_points = float(parameters.min_trend_points)
        self.buy_rsi_max = float(parameters.buy_rsi_max)
        self.sell_rsi_min = float(parameters.sell_rsi_min)

    def evaluate(
        self,
        candle: CandleInput,
        observed_at: datetime,
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        fast, previous_fast = self.fast_ema.update(close)
        slow, previous_slow = self.slow_ema.update(close)
        rsi_value = self.rsi.update(close)
        rejection = (
            None if self.skip_guards else self.guards.rejection_reason(observed_at)
        )
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert fast is not None and slow is not None and rsi_value is not None
        trend_points = (fast - slow) / self.point
        crossed_up = crossed_down = True
        if self.parameters.require_crossover:
            assert previous_fast is not None and previous_slow is not None
            crossed_up = previous_fast <= previous_slow and fast > slow
            crossed_down = previous_fast >= previous_slow and fast < slow
        if (
            trend_points >= self.min_trend_points
            and rsi_value <= self.buy_rsi_max
            and crossed_up
        ):
            return SignalType.BUY, "EMA_RSI_BUY"
        if (
            trend_points <= -self.min_trend_points
            and rsi_value >= self.sell_rsi_min
            and crossed_down
        ):
            return SignalType.SELL, "EMA_RSI_SELL"
        return SignalType.NO_TRADE, "EMA_RSI_CONDITIONS_NOT_MET"


class _EmaRsiBacktestEvaluator:
    def __init__(
        self,
        *,
        parameters: EmaRsiParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        self.parameters = parameters
        self.point = point
        self.guards = guards
        self.fast_period_decimal = Decimal(parameters.fast_ema_period)
        self.slow_period_decimal = Decimal(parameters.slow_ema_period)
        self.rsi_period_decimal = Decimal(parameters.rsi_period)
        self.fast_multiplier = Decimal("2") / Decimal(parameters.fast_ema_period + 1)
        self.slow_multiplier = Decimal("2") / Decimal(parameters.slow_ema_period + 1)
        crossover_extra = 1 if parameters.require_crossover else 0
        self.required = max(
            parameters.slow_ema_period + crossover_extra,
            parameters.rsi_period + 1,
        )
        self.count = 0
        self.fast_ema = _RollingWindowEma(
            period=parameters.fast_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.slow_ema = _RollingWindowEma(
            period=parameters.slow_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.rsi = _RollingRsi(period=parameters.rsi_period)

    def evaluate(
        self,
        candle: CandleInput,
        observed_at: datetime,
    ) -> tuple[SignalType, str]:
        self.count += 1
        fast, previous_fast = self.fast_ema.update(candle.close)
        slow, previous_slow = self.slow_ema.update(candle.close)
        rsi_value = self.rsi.update(candle.close)
        rejection = self.guards.rejection_reason(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return (
                SignalType.NO_TRADE,
                "INSUFFICIENT_COMPLETED_CANDLES",
            )
        assert fast is not None and slow is not None and rsi_value is not None
        trend_points = (fast - slow) / self.point
        crossed_up = crossed_down = True
        if self.parameters.require_crossover:
            assert previous_fast is not None and previous_slow is not None
            crossed_up = previous_fast <= previous_slow and fast > slow
            crossed_down = previous_fast >= previous_slow and fast < slow
        if (
            trend_points >= self.parameters.min_trend_points
            and rsi_value <= self.parameters.buy_rsi_max
            and crossed_up
        ):
            return SignalType.BUY, "EMA_RSI_BUY"
        if (
            trend_points <= -self.parameters.min_trend_points
            and rsi_value >= self.parameters.sell_rsi_min
            and crossed_down
        ):
            return SignalType.SELL, "EMA_RSI_SELL"
        return SignalType.NO_TRADE, "EMA_RSI_CONDITIONS_NOT_MET"
