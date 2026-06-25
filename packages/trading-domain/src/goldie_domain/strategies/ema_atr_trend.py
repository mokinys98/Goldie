from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import atr, ema_series
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastRollingAtr, FastRollingEma


class EmaAtrTrendParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=9, ge=2, le=200)
    slow_ema_period: int = Field(default=21, ge=3, le=500)
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = decimal_parameter(
        "5",
        ge=0,
        le=10000,
        description="Minimum ATR volatility.",
        unit="points",
        impact="Higher values suppress signals in quiet markets.",
    )
    max_atr_points: Decimal = decimal_parameter(
        "500",
        gt=0,
        le=100000,
        description="Maximum ATR volatility.",
        unit="points",
        impact="Lower values suppress signals in extreme volatility.",
    )
    min_trend_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=10000,
        description="Minimum EMA separation.",
        unit="points",
        impact="Higher values require a stronger trend.",
    )
    atr_stop_multiplier: Decimal = decimal_parameter(
        "1.5",
        gt=0,
        le=20,
        description="ATR stop recommendation multiplier.",
        unit="ATR",
        impact="Higher values recommend a wider stop.",
    )
    require_crossover: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_ranges(self) -> "EmaAtrTrendParameters":
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be lower than slow_ema_period")
        if self.min_atr_points > self.max_atr_points:
            raise ValueError("min_atr_points must not exceed max_atr_points")
        return self


class EmaAtrTrendStrategy(PreparedStrategy):
    name = "ema_atr_trend"
    description = "EMA trend following constrained by an ATR volatility range."
    parameters_model = EmaAtrTrendParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastEmaAtrTrendEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastEmaAtrTrendEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = EmaAtrTrendParameters.model_validate(parameters)
        return max(
            values.slow_ema_period + (1 if values.require_crossover else 0),
            values.atr_period + 1,
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = EmaAtrTrendParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )
        closes = [item.close for item in candles]
        fast_values = ema_series(closes, parameters.fast_ema_period)
        slow_values = ema_series(closes, parameters.slow_ema_period)
        fast, slow = fast_values[-1], slow_values[-1]
        atr_value = atr(candles, parameters.atr_period)
        assert atr_value is not None
        trend_points = (fast - slow) / context.point
        atr_points = atr_value / context.point
        crossed_up = crossed_down = True
        if parameters.require_crossover:
            crossed_up = fast_values[-2] <= slow_values[-2] and fast > slow
            crossed_down = fast_values[-2] >= slow_values[-2] and fast < slow
        inputs.update(
            fast_ema=str(fast),
            slow_ema=str(slow),
            trend_points=str(trend_points),
            atr_points=str(atr_points),
            crossed_up=crossed_up,
            crossed_down=crossed_down,
            recommended_stop_points=str(atr_points * parameters.atr_stop_multiplier),
        )
        volatile = parameters.min_atr_points <= atr_points <= parameters.max_atr_points
        if volatile and trend_points >= parameters.min_trend_points and crossed_up:
            return self._finish(SignalType.BUY, "EMA_ATR_TREND_BUY", context, config, guard)
        if volatile and trend_points <= -parameters.min_trend_points and crossed_down:
            return self._finish(SignalType.SELL, "EMA_ATR_TREND_SELL", context, config, guard)
        return self._finish(
            SignalType.NO_TRADE, "EMA_ATR_TREND_CONDITIONS_NOT_MET", context, config, guard
        )


class _FastEmaAtrTrendEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: EmaAtrTrendParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.slow_ema_period + (1 if parameters.require_crossover else 0),
            parameters.atr_period + 1,
        )
        super().__init__(guards=guards, required=required)
        self.parameters = parameters
        self.point = float(point)
        self.fast = FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=required,
            track_previous=parameters.require_crossover,
        )
        self.slow = FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=required,
            track_previous=parameters.require_crossover,
        )
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.min_atr_points = float(parameters.min_atr_points)
        self.max_atr_points = float(parameters.max_atr_points)
        self.min_trend_points = float(parameters.min_trend_points)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        fast, previous_fast = self.fast.update(close)
        slow, previous_slow = self.slow.update(close)
        atr_value = self.atr.update(candle)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert fast is not None and slow is not None and atr_value is not None
        trend_points = (fast - slow) / self.point
        atr_points = atr_value / self.point
        crossed_up = crossed_down = True
        if self.parameters.require_crossover:
            assert previous_fast is not None and previous_slow is not None
            crossed_up = previous_fast <= previous_slow and fast > slow
            crossed_down = previous_fast >= previous_slow and fast < slow
        volatile = self.min_atr_points <= atr_points <= self.max_atr_points
        if volatile and trend_points >= self.min_trend_points and crossed_up:
            return SignalType.BUY, "EMA_ATR_TREND_BUY"
        if volatile and trend_points <= -self.min_trend_points and crossed_down:
            return SignalType.SELL, "EMA_ATR_TREND_SELL"
        return SignalType.NO_TRADE, "EMA_ATR_TREND_CONDITIONS_NOT_MET"


FastEmaAtrTrendEvaluator = _FastEmaAtrTrendEvaluator
