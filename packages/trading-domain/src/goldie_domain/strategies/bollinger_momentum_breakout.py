from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..indicators import atr, bollinger_bands, momentum
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastRollingAtr, FastRollingBollinger, FastRollingMomentum


class BollingerMomentumBreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bollinger_period: int = Field(default=20, ge=2, le=500)
    bollinger_deviations: Decimal = decimal_parameter(
        "2",
        gt=0,
        le=10,
        description="Bollinger band width.",
        unit="standard deviations",
        impact="Lower values create more breakout signals.",
    )
    momentum_period: int = Field(default=5, ge=1, le=100)
    min_momentum_points: Decimal = decimal_parameter(
        "10",
        gt=0,
        le=10000,
        description="Minimum breakout momentum.",
        unit="points",
        impact="Higher values require a stronger breakout.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = decimal_parameter(
        "5",
        ge=0,
        le=10000,
        description="Minimum ATR volatility.",
        unit="points",
        impact="Higher values avoid low-volatility breakouts.",
    )


class BollingerMomentumBreakoutStrategy(PreparedStrategy):
    name = "bb_momentum_breakout"
    description = "Bollinger close breakout confirmed by momentum and ATR."
    parameters_model = BollingerMomentumBreakoutParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastBollingerMomentumEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastBollingerMomentumEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = BollingerMomentumBreakoutParameters.model_validate(parameters)
        return max(
            values.bollinger_period,
            values.momentum_period + 1,
            values.atr_period + 1,
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = BollingerMomentumBreakoutParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )
        closes = [item.close for item in candles]
        bands = bollinger_bands(
            closes, parameters.bollinger_period, parameters.bollinger_deviations
        )
        momentum_value = momentum(closes, parameters.momentum_period)
        atr_value = atr(candles, parameters.atr_period)
        assert bands is not None and momentum_value is not None and atr_value is not None
        momentum_points = momentum_value / context.point
        atr_points = atr_value / context.point
        latest = closes[-1]
        inputs.update(
            lower_band=str(bands.lower),
            upper_band=str(bands.upper),
            momentum_points=str(momentum_points),
            atr_points=str(atr_points),
        )
        if atr_points >= parameters.min_atr_points:
            if latest > bands.upper and momentum_points >= parameters.min_momentum_points:
                return self._finish(
                    SignalType.BUY, "BB_MOMENTUM_BREAKOUT_BUY", context, config, guard
                )
            if latest < bands.lower and momentum_points <= -parameters.min_momentum_points:
                return self._finish(
                    SignalType.SELL, "BB_MOMENTUM_BREAKOUT_SELL", context, config, guard
                )
        return self._finish(
            SignalType.NO_TRADE,
            "BB_MOMENTUM_BREAKOUT_CONDITIONS_NOT_MET",
            context,
            config,
            guard,
        )


class _FastBollingerMomentumEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: BollingerMomentumBreakoutParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        super().__init__(
            guards=guards,
            required=max(
                parameters.bollinger_period,
                parameters.momentum_period + 1,
                parameters.atr_period + 1,
            ),
        )
        self.point = float(point)
        self.bollinger = FastRollingBollinger(
            period=parameters.bollinger_period,
            deviations=float(parameters.bollinger_deviations),
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
        bands = self.bollinger.update(close)
        momentum_value = self.momentum.update(close)
        atr_value = self.atr.update(candle)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert bands is not None and momentum_value is not None and atr_value is not None
        lower, upper = bands
        momentum_points = momentum_value / self.point
        if atr_value / self.point >= self.min_atr_points:
            if close > upper and momentum_points >= self.min_momentum_points:
                return SignalType.BUY, "BB_MOMENTUM_BREAKOUT_BUY"
            if close < lower and momentum_points <= -self.min_momentum_points:
                return SignalType.SELL, "BB_MOMENTUM_BREAKOUT_SELL"
        return SignalType.NO_TRADE, "BB_MOMENTUM_BREAKOUT_CONDITIONS_NOT_MET"


FastBollingerMomentumEvaluator = _FastBollingerMomentumEvaluator
