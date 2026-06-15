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
        required = max(
            parameters.slow_ema_period + crossover_extra,
            parameters.rsi_period + 1,
        )
        self.closes: deque[Decimal] = deque(maxlen=required)

    def evaluate(
        self,
        candle: CandleInput,
        observed_at: datetime,
    ) -> tuple[SignalType, str]:
        self.closes.append(candle.close)
        rejection = self.guards.rejection_reason(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if len(self.closes) < self.closes.maxlen:
            return (
                SignalType.NO_TRADE,
                "INSUFFICIENT_COMPLETED_CANDLES",
            )
        fast, previous_fast = _ema_tail(
            self.closes,
            self.parameters.fast_ema_period,
            self.fast_period_decimal,
            self.fast_multiplier,
        )
        slow, previous_slow = _ema_tail(
            self.closes,
            self.parameters.slow_ema_period,
            self.slow_period_decimal,
            self.slow_multiplier,
        )
        rsi_value = _rsi_tail(
            self.closes,
            self.parameters.rsi_period,
            self.rsi_period_decimal,
        )
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
