from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import ema_series, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import PreparedStrategy
from .rolling import FastRollingEma, FastRollingRsi, RollingRsi, RollingWindowEma


class EmaRsiParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(
        default=9,
        ge=2,
        le=200,
        description="Greitos EMA periodas.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Mažinant EMA greičiau reaguoja į kainą.",
        },
    )
    slow_ema_period: int = Field(
        default=21,
        ge=3,
        le=500,
        description="Lėtos EMA periodas.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Didinant bazinė tendencija tampa lygesnė.",
        },
    )
    rsi_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="RSI indikatoriaus skaičiavimo periodas.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Didinant RSI tampa mažiau jautrus trumpiems pokyčiams.",
        },
    )
    buy_rsi_max: Decimal = Field(
        default=Decimal("70"),
        ge=0,
        le=100,
        description="Didžiausia RSI reikšmė, prie kurios leidžiamas BUY.",
        json_schema_extra={"unit": "RSI", "impact": "Mažinant BUY filtras griežtėja."},
    )
    sell_rsi_min: Decimal = Field(
        default=Decimal("30"),
        ge=0,
        le=100,
        description="Mažiausia RSI reikšmė, prie kurios leidžiamas SELL.",
        json_schema_extra={"unit": "RSI", "impact": "Didinant SELL filtras griežtėja."},
    )
    min_trend_points: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=10000,
        description="Mažiausias atstumas tarp greitos ir lėtos EMA.",
        json_schema_extra={
            "unit": "points",
            "impact": "Didinant reikalaujama stipresnės tendencijos.",
        },
    )
    require_crossover: bool = Field(
        default=False,
        description="Reikalauja, kad EMA susikirtimas įvyktų paskutinėje žvakėje.",
        json_schema_extra={
            "unit": "boolean",
            "impact": "Įjungus signalai tampa retesni ir priklauso nuo naujo susikirtimo.",
        },
    )

    @model_validator(mode="after")
    def validate_periods(self) -> "EmaRsiParameters":
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be lower than slow_ema_period")
        return self


class EmaRsiStrategy(PreparedStrategy):
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
        candles, raw, inputs, guard = self._start(context, config)
        parameters = EmaRsiParameters.model_validate(raw)
        inputs.update(
            fast_ema_period=parameters.fast_ema_period,
            slow_ema_period=parameters.slow_ema_period,
            rsi_period=parameters.rsi_period,
            require_crossover=parameters.require_crossover,
        )
        if isinstance(guard, SignalDecision):
            return guard
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE,
                "INSUFFICIENT_COMPLETED_CANDLES",
                context,
                config,
                guard,
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
            return self._finish(
                SignalType.NO_TRADE,
                "EMA_RSI_CONDITIONS_NOT_MET",
                context,
                config,
                guard,
            )
        return self._finish(signal, reason, context, config, guard)

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
        self.fast_ema = FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.slow_ema = FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.rsi = FastRollingRsi(period=parameters.rsi_period)
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
        crossover_extra = 1 if parameters.require_crossover else 0
        self.required = max(
            parameters.slow_ema_period + crossover_extra,
            parameters.rsi_period + 1,
        )
        self.count = 0
        self.fast_ema = RollingWindowEma(
            period=parameters.fast_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.slow_ema = RollingWindowEma(
            period=parameters.slow_ema_period,
            window_size=self.required,
            track_previous=parameters.require_crossover,
        )
        self.rsi = RollingRsi(period=parameters.rsi_period)

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
