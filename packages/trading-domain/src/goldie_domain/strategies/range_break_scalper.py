from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import ema_series, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastPriorRange, FastRollingEma, FastRollingRsi


class RangeBreakScalperParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=3, ge=2, le=50)
    slow_ema_period: int = Field(default=8, ge=3, le=100)
    rsi_period: int = Field(default=7, ge=2, le=100)
    buy_rsi_min: Decimal = decimal_parameter(
        "55",
        ge=0,
        le=100,
        description="Minimum RSI for BUY.",
        unit="RSI",
        impact="Higher values require stronger upward momentum.",
    )
    sell_rsi_max: Decimal = decimal_parameter(
        "45",
        ge=0,
        le=100,
        description="Maximum RSI for SELL.",
        unit="RSI",
        impact="Lower values require stronger downward momentum.",
    )
    range_lookback: int = Field(default=5, ge=2, le=100)
    min_breakout_points: Decimal = decimal_parameter(
        "2",
        ge=0,
        le=10000,
        description="Distance beyond the prior range.",
        unit="points",
        impact="Higher values filter marginal range breaks.",
    )

    @model_validator(mode="after")
    def validate_values(self) -> "RangeBreakScalperParameters":
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be lower than slow_ema_period")
        if self.sell_rsi_max > self.buy_rsi_min:
            raise ValueError("sell_rsi_max must not exceed buy_rsi_min")
        return self


class RangeBreakScalperStrategy(PreparedStrategy):
    name = "range_break_scalper"
    description = "Short EMA and RSI scalper for closes breaking the recent range."
    parameters_model = RangeBreakScalperParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastRangeBreakEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastRangeBreakEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = RangeBreakScalperParameters.model_validate(parameters)
        return max(
            values.slow_ema_period,
            values.rsi_period + 1,
            values.range_lookback + 1,
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = RangeBreakScalperParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )
        closes = [item.close for item in candles]
        fast = ema_series(closes, parameters.fast_ema_period)[-1]
        slow = ema_series(closes, parameters.slow_ema_period)[-1]
        rsi_value = rsi(closes, parameters.rsi_period)
        assert rsi_value is not None
        prior = candles[-(parameters.range_lookback + 1) : -1]
        range_high = max(item.high for item in prior)
        range_low = min(item.low for item in prior)
        latest = closes[-1]
        breakout = parameters.min_breakout_points * context.point
        inputs.update(
            fast_ema=str(fast),
            slow_ema=str(slow),
            rsi=str(rsi_value),
            range_high=str(range_high),
            range_low=str(range_low),
        )
        if latest >= range_high + breakout and fast > slow and rsi_value >= parameters.buy_rsi_min:
            return self._finish(SignalType.BUY, "RANGE_BREAK_SCALPER_BUY", context, config, guard)
        if latest <= range_low - breakout and fast < slow and rsi_value <= parameters.sell_rsi_max:
            return self._finish(SignalType.SELL, "RANGE_BREAK_SCALPER_SELL", context, config, guard)
        return self._finish(
            SignalType.NO_TRADE,
            "RANGE_BREAK_SCALPER_CONDITIONS_NOT_MET",
            context,
            config,
            guard,
        )


class _FastRangeBreakEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: RangeBreakScalperParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.slow_ema_period,
            parameters.rsi_period + 1,
            parameters.range_lookback + 1,
        )
        super().__init__(guards=guards, required=required)
        self.point = float(point)
        self.fast = FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=required,
            track_previous=False,
        )
        self.slow = FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=required,
            track_previous=False,
        )
        self.rsi = FastRollingRsi(period=parameters.rsi_period)
        self.prior_range = FastPriorRange(period=parameters.range_lookback)
        self.buy_rsi_min = float(parameters.buy_rsi_min)
        self.sell_rsi_max = float(parameters.sell_rsi_max)
        self.breakout = float(parameters.min_breakout_points) * self.point

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        fast, _ = self.fast.update(close)
        slow, _ = self.slow.update(close)
        rsi_value = self.rsi.update(close)
        prior = self.prior_range.update(candle)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert fast is not None and slow is not None and rsi_value is not None
        assert prior is not None
        range_high, range_low = prior
        if close >= range_high + self.breakout and fast > slow and rsi_value >= self.buy_rsi_min:
            return SignalType.BUY, "RANGE_BREAK_SCALPER_BUY"
        if close <= range_low - self.breakout and fast < slow and rsi_value <= self.sell_rsi_max:
            return SignalType.SELL, "RANGE_BREAK_SCALPER_SELL"
        return SignalType.NO_TRADE, "RANGE_BREAK_SCALPER_CONDITIONS_NOT_MET"


FastRangeBreakEvaluator = _FastRangeBreakEvaluator
