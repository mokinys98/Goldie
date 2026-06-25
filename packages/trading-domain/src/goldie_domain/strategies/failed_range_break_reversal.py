from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import atr, ema_series, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastPriorRange, FastRollingAtr, FastRollingEma, FastRollingRsi


class FailedRangeBreakReversalParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    range_lookback: int = Field(
        default=20,
        ge=2,
        le=500,
        description="Candles used to build the prior high/low range.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make fakeout levels more stable but less reactive.",
            "optimization_minimum": 5,
            "optimization_maximum": 80,
        },
    )
    fakeout_points: Decimal = decimal_parameter(
        "5",
        ge=0,
        le=100000,
        description="Minimum wick distance beyond the prior range.",
        unit="points",
        impact="Higher values require a deeper stop sweep before reversal.",
        optimization_minimum="0",
        optimization_maximum="80",
    )
    reclaim_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=100000,
        description="Required close distance back inside the prior range.",
        unit="points",
        impact="Higher values require a stronger reclaim after the fakeout.",
        optimization_minimum="0",
        optimization_maximum="40",
    )
    rsi_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="RSI period used to confirm exhaustion at the range edge.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth RSI and reduce fast reversal signals.",
            "optimization_minimum": 5,
            "optimization_maximum": 35,
        },
    )
    buy_rsi_max: Decimal = decimal_parameter(
        "45",
        ge=0,
        le=100,
        description="Maximum RSI for BUY after a failed downside break.",
        unit="RSI",
        impact="Lower values require stronger oversold exhaustion.",
        optimization_minimum="20",
        optimization_maximum="45",
    )
    sell_rsi_min: Decimal = decimal_parameter(
        "55",
        ge=0,
        le=100,
        description="Minimum RSI for SELL after a failed upside break.",
        unit="RSI",
        impact="Higher values require stronger overbought exhaustion.",
        optimization_minimum="55",
        optimization_maximum="80",
    )
    atr_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="ATR period for volatility-regime filtering.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make the ATR regime filter slower.",
            "optimization_minimum": 5,
            "optimization_maximum": 50,
        },
    )
    min_atr_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=100000,
        description="Minimum ATR volatility allowed for signals.",
        unit="points",
        impact="Higher values avoid dead ranges with no reversal energy.",
        optimization_minimum="0",
        optimization_maximum="300",
    )
    max_atr_points: Decimal = decimal_parameter(
        "500",
        gt=0,
        le=100000,
        description="Maximum ATR volatility allowed for signals.",
        unit="points",
        impact="Lower values avoid panic moves where fakeouts can become real breakouts.",
        optimization_minimum="20",
        optimization_maximum="1000",
    )
    fast_ema_period: int = Field(
        default=9,
        ge=2,
        le=200,
        description="Fast EMA period for optional flat-trend filtering.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Lower values make the trend filter more reactive.",
            "optimization_minimum": 5,
            "optimization_maximum": 20,
        },
    )
    slow_ema_period: int = Field(
        default=21,
        ge=3,
        le=500,
        description="Slow EMA period for optional flat-trend filtering.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make trend strength smoother.",
            "optimization_minimum": 13,
            "optimization_maximum": 80,
        },
    )
    max_trend_points: Decimal = decimal_parameter(
        "50",
        ge=0,
        le=100000,
        description="Maximum absolute fast/slow EMA distance allowed.",
        unit="points",
        impact="Lower values restrict this reversal strategy to flatter markets.",
        optimization_minimum="0",
        optimization_maximum="200",
    )
    use_ema_flat_filter: bool = Field(
        default=True,
        description="Restrict fakeout reversals to markets without a strong EMA trend.",
        json_schema_extra={
            "unit": "boolean",
            "impact": (
                "Disabling allows more counter-trend reversals but raises trend-failure risk."
            ),
        },
    )

    @model_validator(mode="after")
    def validate_values(self) -> "FailedRangeBreakReversalParameters":
        if self.buy_rsi_max > self.sell_rsi_min:
            raise ValueError("buy_rsi_max must not exceed sell_rsi_min")
        if self.min_atr_points > self.max_atr_points:
            raise ValueError("min_atr_points must not exceed max_atr_points")
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be lower than slow_ema_period")
        return self


class FailedRangeBreakReversalStrategy(PreparedStrategy):
    name = "failed_range_break_reversal"
    description = "Fades failed prior-range breaks confirmed by RSI and ATR regime filters."
    parameters_model = FailedRangeBreakReversalParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastFailedRangeBreakReversalEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastFailedRangeBreakReversalEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = FailedRangeBreakReversalParameters.model_validate(parameters)
        return max(
            values.range_lookback + 1,
            values.rsi_period + 1,
            values.atr_period + 1,
            values.slow_ema_period,
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = FailedRangeBreakReversalParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )

        closes = [item.close for item in candles]
        prior = candles[-(parameters.range_lookback + 1) : -1]
        range_high = max(item.high for item in prior)
        range_low = min(item.low for item in prior)
        latest = candles[-1]
        rsi_value = rsi(closes, parameters.rsi_period)
        atr_value = atr(candles, parameters.atr_period)
        fast = ema_series(closes, parameters.fast_ema_period)[-1]
        slow = ema_series(closes, parameters.slow_ema_period)[-1]
        assert rsi_value is not None and atr_value is not None

        fakeout = parameters.fakeout_points * context.point
        reclaim = parameters.reclaim_points * context.point
        atr_points = atr_value / context.point
        trend_points = abs(fast - slow) / context.point
        volatility_ok = parameters.min_atr_points <= atr_points <= parameters.max_atr_points
        trend_ok = not parameters.use_ema_flat_filter or trend_points <= parameters.max_trend_points

        downside_sweep = latest.low <= range_low - fakeout
        upside_sweep = latest.high >= range_high + fakeout
        downside_reclaim = latest.close >= range_low + reclaim
        upside_reclaim = latest.close <= range_high - reclaim

        inputs.update(
            range_high=str(range_high),
            range_low=str(range_low),
            rsi=str(rsi_value),
            atr_points=str(atr_points),
            trend_points=str(trend_points),
            downside_sweep=downside_sweep,
            upside_sweep=upside_sweep,
            downside_reclaim=downside_reclaim,
            upside_reclaim=upside_reclaim,
        )

        if volatility_ok and trend_ok:
            if downside_sweep and downside_reclaim and rsi_value <= parameters.buy_rsi_max:
                return self._finish(
                    SignalType.BUY,
                    "FAILED_RANGE_BREAK_REVERSAL_BUY",
                    context,
                    config,
                    guard,
                )
            if upside_sweep and upside_reclaim and rsi_value >= parameters.sell_rsi_min:
                return self._finish(
                    SignalType.SELL,
                    "FAILED_RANGE_BREAK_REVERSAL_SELL",
                    context,
                    config,
                    guard,
                )
        return self._finish(
            SignalType.NO_TRADE,
            "FAILED_RANGE_BREAK_REVERSAL_CONDITIONS_NOT_MET",
            context,
            config,
            guard,
        )


class _FastFailedRangeBreakReversalEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: FailedRangeBreakReversalParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.range_lookback + 1,
            parameters.rsi_period + 1,
            parameters.atr_period + 1,
            parameters.slow_ema_period,
        )
        super().__init__(guards=guards, required=required)
        self.parameters = parameters
        self.point = float(point)
        self.prior_range = FastPriorRange(period=parameters.range_lookback)
        self.rsi = FastRollingRsi(period=parameters.rsi_period)
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.fast_ema = FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=required,
            track_previous=False,
        )
        self.slow_ema = FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=required,
            track_previous=False,
        )
        self.fakeout = float(parameters.fakeout_points) * self.point
        self.reclaim = float(parameters.reclaim_points) * self.point
        self.buy_rsi_max = float(parameters.buy_rsi_max)
        self.sell_rsi_min = float(parameters.sell_rsi_min)
        self.min_atr_points = float(parameters.min_atr_points)
        self.max_atr_points = float(parameters.max_atr_points)
        self.max_trend_points = float(parameters.max_trend_points)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        high = float(candle.high)
        low = float(candle.low)
        prior = self.prior_range.update(candle)
        rsi_value = self.rsi.update(close)
        atr_value = self.atr.update(candle)
        fast, _ = self.fast_ema.update(close)
        slow, _ = self.slow_ema.update(close)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert prior is not None
        assert rsi_value is not None and atr_value is not None
        assert fast is not None and slow is not None

        range_high, range_low = prior
        atr_points = atr_value / self.point
        trend_points = abs(fast - slow) / self.point
        volatility_ok = self.min_atr_points <= atr_points <= self.max_atr_points
        trend_ok = not self.parameters.use_ema_flat_filter or trend_points <= self.max_trend_points

        if volatility_ok and trend_ok:
            if (
                low <= range_low - self.fakeout
                and close >= range_low + self.reclaim
                and rsi_value <= self.buy_rsi_max
            ):
                return SignalType.BUY, "FAILED_RANGE_BREAK_REVERSAL_BUY"
            if (
                high >= range_high + self.fakeout
                and close <= range_high - self.reclaim
                and rsi_value >= self.sell_rsi_min
            ):
                return SignalType.SELL, "FAILED_RANGE_BREAK_REVERSAL_SELL"
        return SignalType.NO_TRADE, "FAILED_RANGE_BREAK_REVERSAL_CONDITIONS_NOT_MET"


FastFailedRangeBreakReversalEvaluator = _FastFailedRangeBreakReversalEvaluator
