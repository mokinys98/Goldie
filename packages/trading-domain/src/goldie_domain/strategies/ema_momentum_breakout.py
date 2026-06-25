from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import atr, ema_series, momentum
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastRollingAtr, FastRollingEma, FastRollingMomentum


class EmaMomentumBreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=5, ge=2, le=200)
    medium_ema_period: int = Field(default=13, ge=3, le=300)
    slow_ema_period: int = Field(default=34, ge=4, le=500)
    momentum_period: int = Field(default=5, ge=1, le=100)
    min_momentum_points: Decimal = decimal_parameter(
        "10",
        gt=0,
        le=10000,
        description="Minimum directional momentum.",
        unit="points",
        impact="Higher values filter weak breakouts.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=10000,
        description="Minimum market volatility.",
        unit="points",
        impact="Higher values avoid quiet markets.",
    )

    @model_validator(mode="after")
    def validate_periods(self) -> "EmaMomentumBreakoutParameters":
        if not self.fast_ema_period < self.medium_ema_period < self.slow_ema_period:
            raise ValueError("EMA periods must satisfy fast < medium < slow")
        return self


class EmaMomentumBreakoutStrategy(PreparedStrategy):
    name = "ema_momentum_breakout"
    description = "Multi-EMA trend alignment confirmed by momentum and ATR."
    parameters_model = EmaMomentumBreakoutParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastEmaMomentumEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastEmaMomentumEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = EmaMomentumBreakoutParameters.model_validate(parameters)
        return max(
            values.slow_ema_period,
            values.momentum_period + 1,
            values.atr_period + 1,
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = EmaMomentumBreakoutParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )
        closes = [item.close for item in candles]
        fast = ema_series(closes, parameters.fast_ema_period)[-1]
        medium = ema_series(closes, parameters.medium_ema_period)[-1]
        slow = ema_series(closes, parameters.slow_ema_period)[-1]
        momentum_value = momentum(closes, parameters.momentum_period)
        atr_value = atr(candles, parameters.atr_period)
        assert momentum_value is not None and atr_value is not None
        momentum_points = momentum_value / context.point
        atr_points = atr_value / context.point
        inputs.update(
            fast_ema=str(fast),
            medium_ema=str(medium),
            slow_ema=str(slow),
            momentum_points=str(momentum_points),
            atr_points=str(atr_points),
        )
        if atr_points >= parameters.min_atr_points:
            if fast > medium > slow and momentum_points >= parameters.min_momentum_points:
                return self._finish(
                    SignalType.BUY, "EMA_MOMENTUM_BREAKOUT_BUY", context, config, guard
                )
            if fast < medium < slow and momentum_points <= -parameters.min_momentum_points:
                return self._finish(
                    SignalType.SELL, "EMA_MOMENTUM_BREAKOUT_SELL", context, config, guard
                )
        return self._finish(
            SignalType.NO_TRADE,
            "EMA_MOMENTUM_BREAKOUT_CONDITIONS_NOT_MET",
            context,
            config,
            guard,
        )


class _FastEmaMomentumEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: EmaMomentumBreakoutParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.slow_ema_period,
            parameters.momentum_period + 1,
            parameters.atr_period + 1,
        )
        super().__init__(guards=guards, required=required)
        self.point = float(point)
        self.fast = FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=required,
            track_previous=False,
        )
        self.medium = FastRollingEma(
            period=parameters.medium_ema_period,
            window_size=required,
            track_previous=False,
        )
        self.slow = FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=required,
            track_previous=False,
        )
        self.momentum = FastRollingMomentum(period=parameters.momentum_period)
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.min_momentum_points = float(parameters.min_momentum_points)
        self.min_atr_points = float(parameters.min_atr_points)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        fast, _ = self.fast.update(close)
        medium, _ = self.medium.update(close)
        slow, _ = self.slow.update(close)
        momentum_value = self.momentum.update(close)
        atr_value = self.atr.update(candle)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert fast is not None and medium is not None and slow is not None
        assert momentum_value is not None and atr_value is not None
        momentum_points = momentum_value / self.point
        if atr_value / self.point >= self.min_atr_points:
            if fast > medium > slow and momentum_points >= self.min_momentum_points:
                return SignalType.BUY, "EMA_MOMENTUM_BREAKOUT_BUY"
            if fast < medium < slow and momentum_points <= -self.min_momentum_points:
                return SignalType.SELL, "EMA_MOMENTUM_BREAKOUT_SELL"
        return SignalType.NO_TRADE, "EMA_MOMENTUM_BREAKOUT_CONDITIONS_NOT_MET"


FastEmaMomentumEvaluator = _FastEmaMomentumEvaluator
