from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

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
            "optimization_minimum": 20,
            "optimization_maximum": 60,
        },
    )
    bollinger_deviations: Decimal = decimal_parameter(
        "2",
        gt=0,
        le=10,
        description="Bollinger standard-deviation multiplier.",
        unit="standard deviations",
        impact="Higher values widen the bands and reduce breakout frequency.",
        optimization_minimum="1.8",
        optimization_maximum="2.5",
    )
    squeeze_lookback: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Previous Bollinger widths scanned for compression.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values compare compression against a longer volatility regime.",
            "optimization_minimum": 20,
            "optimization_maximum": 80,
        },
    )
    squeeze_percentile: Decimal = decimal_parameter(
        "25",
        ge=0,
        le=100,
        description="Maximum percentile rank of the prior Bollinger width inside the squeeze lookback.",
        unit="percentile",
        impact="Lower values require the setup width to be unusually compressed for its recent regime.",
        optimization_minimum="5",
        optimization_maximum="35",
    )
    max_squeeze_width_points: Decimal = decimal_parameter(
        "180",
        ge=0,
        le=100000,
        description="Maximum prior Bollinger width allowed even when relative squeeze qualifies.",
        unit="points",
        impact="Lower values keep the relative squeeze filter from accepting broad volatile regimes.",
        optimization_minimum="50",
        optimization_maximum="180",
    )
    breakout_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=100000,
        description="Required close distance beyond the current Bollinger band.",
        unit="points",
        impact="Higher values filter marginal band breaks.",
        optimization_minimum="0",
        optimization_maximum="20",
    )
    momentum_period: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Momentum confirmation period.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values require broader directional continuation.",
            "optimization_minimum": 5,
            "optimization_maximum": 24,
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
        optimization_maximum="80",
    )
    atr_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="ATR period for volatility-regime confirmation.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth the ATR expansion filter.",
            "optimization_minimum": 10,
            "optimization_maximum": 40,
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
        optimization_maximum="50",
    )
    max_atr_points: Decimal = decimal_parameter(
        "300",
        gt=0,
        le=100000,
        description="Maximum ATR volatility allowed after breakout.",
        unit="points",
        impact="Lower values avoid late entries in panic expansion.",
        optimization_minimum="50",
        optimization_maximum="300",
    )
    trade_direction: Literal["BOTH", "BUY_ONLY", "SELL_ONLY"] = Field(
        default="BOTH",
        description="Allowed signal direction for directional robustness tests.",
        json_schema_extra={
            "unit": "mode",
            "impact": "Use BUY_ONLY or SELL_ONLY to isolate asymmetric squeeze-breakout edge.",
        },
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
        prior_width_points = prior_widths_points[-1]
        squeeze_percentile_rank = _percentile_rank(prior_width_points, prior_widths_points)
        squeezed = (
            prior_width_points <= parameters.max_squeeze_width_points
            and squeeze_percentile_rank <= parameters.squeeze_percentile
        )
        current_width_points = (current_bands.upper - current_bands.lower) / context.point
        momentum_points = momentum_value / context.point
        atr_points = atr_value / context.point
        breakout = parameters.breakout_points * context.point
        latest = closes[-1]

        inputs.update(
            lower_band=str(current_bands.lower),
            upper_band=str(current_bands.upper),
            current_width_points=str(current_width_points),
            prior_width_points=str(prior_width_points),
            squeeze_percentile_rank=str(squeeze_percentile_rank),
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
                if parameters.trade_direction == "SELL_ONLY":
                    return self._finish(
                        SignalType.NO_TRADE,
                        "BB_SQUEEZE_BREAKOUT_BUY_DISABLED",
                        context,
                        config,
                        guard,
                    )
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
                if parameters.trade_direction == "BUY_ONLY":
                    return self._finish(
                        SignalType.NO_TRADE,
                        "BB_SQUEEZE_BREAKOUT_SELL_DISABLED",
                        context,
                        config,
                        guard,
                    )
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


def _percentile_rank(value: Decimal, values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("100")
    below = sum(1 for item in values if item < value)
    return Decimal(below * 100) / Decimal(len(values))


class _FastRollingPercentileWindow:
    def __init__(self, *, period: int) -> None:
        self.period = period
        self.values: deque[float] = deque(maxlen=period)

    def update(self, value: float) -> None:
        self.values.append(value)

    def latest(self) -> float | None:
        return self.values[-1] if self.values else None

    def percentile_rank(self, value: float) -> float | None:
        if len(self.values) < self.period:
            return None
        below = sum(1 for item in self.values if item < value)
        return below * 100.0 / len(self.values)


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
        self.widths = _FastRollingPercentileWindow(period=parameters.squeeze_lookback)
        self.momentum = FastRollingMomentum(period=parameters.momentum_period)
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.squeeze_percentile = float(parameters.squeeze_percentile)
        self.max_squeeze_width_points = float(parameters.max_squeeze_width_points)
        self.breakout = float(parameters.breakout_points) * self.point
        self.min_momentum_points = float(parameters.min_momentum_points)
        self.min_atr_points = float(parameters.min_atr_points)
        self.max_atr_points = float(parameters.max_atr_points)
        self.trade_direction = parameters.trade_direction

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        bands = self.bollinger.update(close)
        momentum_value = self.momentum.update(close)
        atr_value = self.atr.update(candle)
        prior_width_points = self.widths.latest()
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
            assert prior_width_points is not None
            lower, upper = bands
            atr_points = atr_value / self.point
            momentum_points = momentum_value / self.point
            squeeze_percentile_rank = self.widths.percentile_rank(prior_width_points)
            assert squeeze_percentile_rank is not None
            squeezed = (
                prior_width_points <= self.max_squeeze_width_points
                and squeeze_percentile_rank <= self.squeeze_percentile
            )
            volatility_ok = self.min_atr_points <= atr_points <= self.max_atr_points
            if squeezed and volatility_ok:
                if close >= upper + self.breakout and momentum_points >= self.min_momentum_points:
                    if self.trade_direction == "SELL_ONLY":
                        result = SignalType.NO_TRADE, "BB_SQUEEZE_BREAKOUT_BUY_DISABLED"
                    else:
                        result = SignalType.BUY, "BB_SQUEEZE_BREAKOUT_BUY"
                elif (
                    close <= lower - self.breakout
                    and momentum_points <= -self.min_momentum_points
                ):
                    if self.trade_direction == "BUY_ONLY":
                        result = SignalType.NO_TRADE, "BB_SQUEEZE_BREAKOUT_SELL_DISABLED"
                    else:
                        result = SignalType.SELL, "BB_SQUEEZE_BREAKOUT_SELL"
                else:
                    result = SignalType.NO_TRADE, "BB_SQUEEZE_BREAKOUT_CONDITIONS_NOT_MET"
            else:
                result = SignalType.NO_TRADE, "BB_SQUEEZE_BREAKOUT_CONDITIONS_NOT_MET"

        if current_width_points is not None:
            self.widths.update(current_width_points)
        return result


FastBollingerSqueezeBreakoutEvaluator = _FastBollingerSqueezeBreakoutEvaluator
