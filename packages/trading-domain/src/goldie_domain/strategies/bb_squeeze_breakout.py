from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import atr, bollinger_bands, momentum
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastRollingAtr, FastRollingBollinger, FastRollingMomentum


class BollingerSqueezeBreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bollinger_period: int = Field(
        default=20,
        ge=2,
        le=500,
        description="Bollinger SMA period.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make band width smoother and squeeze signals slower.",
            "optimization_minimum": 10,
            "optimization_maximum": 80,
        },
    )
    bollinger_deviations: Decimal = decimal_parameter(
        "2",
        gt=0,
        le=10,
        description="Bollinger standard-deviation multiplier.",
        unit="standard deviations",
        impact="Higher values widen the bands and reduce breakout frequency.",
        optimization_minimum="1.5",
        optimization_maximum="3.2",
    )
    squeeze_lookback: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Previous Bollinger widths scanned for compression.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values allow older squeezes to qualify breakouts.",
            "optimization_minimum": 20,
            "optimization_maximum": 200,
        },
    )
    max_squeeze_width_points: Decimal = decimal_parameter(
        "50",
        ge=0,
        le=100000,
        description="Maximum prior Bollinger width that qualifies as squeeze.",
        unit="points",
        impact="Lower values require tighter compression before breakout.",
        optimization_minimum="5",
        optimization_maximum="300",
    )
    breakout_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=100000,
        description="Required close distance beyond the current Bollinger band.",
        unit="points",
        impact="Higher values filter marginal band breaks.",
        optimization_minimum="0",
        optimization_maximum="80",
    )
    momentum_period: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Momentum confirmation period.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values require broader directional continuation.",
            "optimization_minimum": 2,
            "optimization_maximum": 30,
        },
    )
    min_momentum_points: Decimal = decimal_parameter(
        "10",
        ge=0,
        le=100000,
        description="Minimum directional momentum after squeeze breakout.",
        unit="points",
        impact="Higher values require stronger post-squeeze expansion.",
        optimization_minimum="0",
        optimization_maximum="200",
    )
    atr_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="ATR period for volatility-regime confirmation.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth the ATR expansion filter.",
            "optimization_minimum": 5,
            "optimization_maximum": 50,
        },
    )
    min_atr_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=100000,
        description="Minimum ATR volatility allowed after breakout.",
        unit="points",
        impact="Higher values avoid very weak post-squeeze breaks.",
        optimization_minimum="0",
        optimization_maximum="300",
    )
    max_atr_points: Decimal = decimal_parameter(
        "1000",
        gt=0,
        le=100000,
        description="Maximum ATR volatility allowed after breakout.",
        unit="points",
        impact="Lower values avoid late entries in panic expansion.",
        optimization_minimum="50",
        optimization_maximum="1500",
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> "BollingerSqueezeBreakoutParameters":
        if self.min_atr_points > self.max_atr_points:
            raise ValueError("min_atr_points must not exceed max_atr_points")
        return self


class BollingerSqueezeBreakoutStrategy(PreparedStrategy):
    name = "bb_squeeze_breakout"
    description = "Bollinger breakout that requires prior volatility compression."
    parameters_model = BollingerSqueezeBreakoutParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastBollingerSqueezeBreakoutEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastBollingerSqueezeBreakoutEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = BollingerSqueezeBreakoutParameters.model_validate(parameters)
        return max(
            values.bollinger_period + values.squeeze_lookback,
            values.momentum_period + 1,
            values.atr_period + 1,
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = BollingerSqueezeBreakoutParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )

        closes = [item.close for item in candles]
        current_bands = bollinger_bands(
            closes,
            parameters.bollinger_period,
            parameters.bollinger_deviations,
        )
        momentum_value = momentum(closes, parameters.momentum_period)
        atr_value = atr(candles, parameters.atr_period)
        assert current_bands is not None and momentum_value is not None and atr_value is not None

        start_index = len(closes) - 1 - parameters.squeeze_lookback
        prior_widths_points: list[Decimal] = []
        for index in range(start_index, len(closes) - 1):
            bands = bollinger_bands(
                closes[: index + 1],
                parameters.bollinger_period,
                parameters.bollinger_deviations,
            )
            if bands is not None:
                prior_widths_points.append((bands.upper - bands.lower) / context.point)
        squeeze_width_points = min(prior_widths_points)
        squeezed = squeeze_width_points <= parameters.max_squeeze_width_points
        current_width_points = (current_bands.upper - current_bands.lower) / context.point
        momentum_points = momentum_value / context.point
        atr_points = atr_value / context.point
        breakout = parameters.breakout_points * context.point
        latest = closes[-1]

        inputs.update(
            lower_band=str(current_bands.lower),
            upper_band=str(current_bands.upper),
            current_width_points=str(current_width_points),
            squeeze_width_points=str(squeeze_width_points),
            squeezed=squeezed,
            momentum_points=str(momentum_points),
            atr_points=str(atr_points),
        )

        volatility_ok = parameters.min_atr_points <= atr_points <= parameters.max_atr_points
        if squeezed and volatility_ok:
            if (
                latest >= current_bands.upper + breakout
                and momentum_points >= parameters.min_momentum_points
            ):
                return self._finish(
                    SignalType.BUY,
                    "BB_SQUEEZE_BREAKOUT_BUY",
                    context,
                    config,
                    guard,
                )
            if (
                latest <= current_bands.lower - breakout
                and momentum_points <= -parameters.min_momentum_points
            ):
                return self._finish(
                    SignalType.SELL,
                    "BB_SQUEEZE_BREAKOUT_SELL",
                    context,
                    config,
                    guard,
                )
        return self._finish(
            SignalType.NO_TRADE,
            "BB_SQUEEZE_BREAKOUT_CONDITIONS_NOT_MET",
            context,
            config,
            guard,
        )


class _FastRollingMinimum:
    def __init__(self, *, period: int) -> None:
        self.period = period
        self.index = 0
        self.values: deque[tuple[int, float]] = deque()

    def update(self, value: float) -> None:
        cutoff = self.index - self.period + 1
        while self.values and self.values[0][0] < cutoff:
            self.values.popleft()
        while self.values and self.values[-1][1] >= value:
            self.values.pop()
        self.values.append((self.index, value))
        self.index += 1

    def minimum(self) -> float | None:
        return self.values[0][1] if self.values else None


class _FastBollingerSqueezeBreakoutEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: BollingerSqueezeBreakoutParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.bollinger_period + parameters.squeeze_lookback,
            parameters.momentum_period + 1,
            parameters.atr_period + 1,
        )
        super().__init__(guards=guards, required=required)
        self.point = float(point)
        self.bollinger = FastRollingBollinger(
            period=parameters.bollinger_period,
            deviations=float(parameters.bollinger_deviations),
        )
        self.width_min = _FastRollingMinimum(period=parameters.squeeze_lookback)
        self.momentum = FastRollingMomentum(period=parameters.momentum_period)
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.max_squeeze_width_points = float(parameters.max_squeeze_width_points)
        self.breakout = float(parameters.breakout_points) * self.point
        self.min_momentum_points = float(parameters.min_momentum_points)
        self.min_atr_points = float(parameters.min_atr_points)
        self.max_atr_points = float(parameters.max_atr_points)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        bands = self.bollinger.update(close)
        momentum_value = self.momentum.update(close)
        atr_value = self.atr.update(candle)
        squeeze_width_points = self.width_min.minimum()
        current_width_points: float | None = None
        if bands is not None:
            lower, upper = bands
            current_width_points = (upper - lower) / self.point

        rejection = self.rejection(observed_at)
        if rejection:
            result = SignalType.NO_TRADE, rejection
        elif self.count < self.required:
            result = SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        else:
            assert bands is not None and momentum_value is not None and atr_value is not None
            assert squeeze_width_points is not None
            lower, upper = bands
            atr_points = atr_value / self.point
            momentum_points = momentum_value / self.point
            squeezed = squeeze_width_points <= self.max_squeeze_width_points
            volatility_ok = self.min_atr_points <= atr_points <= self.max_atr_points
            if squeezed and volatility_ok:
                if close >= upper + self.breakout and momentum_points >= self.min_momentum_points:
                    result = SignalType.BUY, "BB_SQUEEZE_BREAKOUT_BUY"
                elif (
                    close <= lower - self.breakout
                    and momentum_points <= -self.min_momentum_points
                ):
                    result = SignalType.SELL, "BB_SQUEEZE_BREAKOUT_SELL"
                else:
                    result = SignalType.NO_TRADE, "BB_SQUEEZE_BREAKOUT_CONDITIONS_NOT_MET"
            else:
                result = SignalType.NO_TRADE, "BB_SQUEEZE_BREAKOUT_CONDITIONS_NOT_MET"

        if current_width_points is not None:
            self.width_min.update(current_width_points)
        return result


FastBollingerSqueezeBreakoutEvaluator = _FastBollingerSqueezeBreakoutEvaluator
