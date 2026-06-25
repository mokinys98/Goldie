from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import atr, ema_series, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastRollingAtr, FastRollingEma, FastRollingRsi


class EmaAtrPullbackContinuationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(
        default=9,
        ge=2,
        le=200,
        description="Fast EMA used as reclaim trigger.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Lower values make reclaims more reactive.",
            "optimization_minimum": 5,
            "optimization_maximum": 20,
        },
    )
    medium_ema_period: int = Field(
        default=21,
        ge=3,
        le=300,
        description="Medium EMA used as pullback area.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values require deeper pullbacks before continuation.",
            "optimization_minimum": 13,
            "optimization_maximum": 60,
        },
    )
    slow_ema_period: int = Field(
        default=55,
        ge=4,
        le=500,
        description="Slow EMA used for trend stack confirmation.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make trend regime slower and more selective.",
            "optimization_minimum": 34,
            "optimization_maximum": 200,
        },
    )
    atr_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="ATR period for volatility-regime filtering.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth volatility regime changes.",
            "optimization_minimum": 5,
            "optimization_maximum": 50,
        },
    )
    min_atr_points: Decimal = decimal_parameter(
        "5",
        ge=0,
        le=100000,
        description="Minimum ATR volatility allowed for pullback continuation.",
        unit="points",
        impact="Higher values avoid weak trends with no continuation energy.",
        optimization_minimum="0",
        optimization_maximum="300",
    )
    max_atr_points: Decimal = decimal_parameter(
        "1000",
        gt=0,
        le=100000,
        description="Maximum ATR volatility allowed for pullback continuation.",
        unit="points",
        impact="Lower values avoid chasing highly unstable pullbacks.",
        optimization_minimum="50",
        optimization_maximum="1500",
    )
    min_trend_points: Decimal = decimal_parameter(
        "10",
        ge=0,
        le=100000,
        description="Minimum fast/slow EMA separation required for trend regime.",
        unit="points",
        impact="Higher values require a stronger trend before pullback entries.",
        optimization_minimum="0",
        optimization_maximum="300",
    )
    pullback_tolerance_points: Decimal = decimal_parameter(
        "10",
        ge=0,
        le=100000,
        description="Allowed distance around the medium EMA for pullback touch.",
        unit="points",
        impact="Higher values accept looser pullbacks around the EMA area.",
        optimization_minimum="0",
        optimization_maximum="150",
    )
    rsi_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="RSI period for continuation confirmation without overextension.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth continuation momentum.",
            "optimization_minimum": 7,
            "optimization_maximum": 35,
        },
    )
    buy_rsi_min: Decimal = decimal_parameter(
        "45",
        ge=0,
        le=100,
        description="Minimum RSI for BUY continuation.",
        unit="RSI",
        impact="Higher values require stronger bullish momentum after pullback.",
        optimization_minimum="40",
        optimization_maximum="60",
    )
    buy_rsi_max: Decimal = decimal_parameter(
        "70",
        ge=0,
        le=100,
        description="Maximum RSI for BUY continuation.",
        unit="RSI",
        impact="Lower values avoid overbought continuation entries.",
        optimization_minimum="60",
        optimization_maximum="80",
    )
    sell_rsi_min: Decimal = decimal_parameter(
        "30",
        ge=0,
        le=100,
        description="Minimum RSI for SELL continuation.",
        unit="RSI",
        impact="Higher values avoid oversold continuation shorts.",
        optimization_minimum="20",
        optimization_maximum="40",
    )
    sell_rsi_max: Decimal = decimal_parameter(
        "55",
        ge=0,
        le=100,
        description="Maximum RSI for SELL continuation.",
        unit="RSI",
        impact="Lower values require stronger bearish momentum after pullback.",
        optimization_minimum="40",
        optimization_maximum="60",
    )
    require_reversal_candle: bool = Field(
        default=False,
        description="Require candle body to close in the continuation direction.",
        json_schema_extra={
            "unit": "boolean",
            "impact": "Enabling makes entries stricter and can reduce early pullback signals.",
        },
    )

    @model_validator(mode="after")
    def validate_values(self) -> "EmaAtrPullbackContinuationParameters":
        if not self.fast_ema_period < self.medium_ema_period < self.slow_ema_period:
            raise ValueError("EMA periods must satisfy fast < medium < slow")
        if self.min_atr_points > self.max_atr_points:
            raise ValueError("min_atr_points must not exceed max_atr_points")
        if self.buy_rsi_min > self.buy_rsi_max:
            raise ValueError("buy_rsi_min must not exceed buy_rsi_max")
        if self.sell_rsi_min > self.sell_rsi_max:
            raise ValueError("sell_rsi_min must not exceed sell_rsi_max")
        return self


class EmaAtrPullbackContinuationStrategy(PreparedStrategy):
    name = "ema_atr_pullback_continuation"
    description = "Trend-stack continuation entry after an EMA-area pullback and reclaim."
    parameters_model = EmaAtrPullbackContinuationParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastEmaAtrPullbackContinuationEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastEmaAtrPullbackContinuationEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = EmaAtrPullbackContinuationParameters.model_validate(parameters)
        return max(values.slow_ema_period, values.atr_period + 1, values.rsi_period + 1)

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = EmaAtrPullbackContinuationParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )

        closes = [item.close for item in candles]
        fast = ema_series(closes, parameters.fast_ema_period)[-1]
        medium = ema_series(closes, parameters.medium_ema_period)[-1]
        slow = ema_series(closes, parameters.slow_ema_period)[-1]
        atr_value = atr(candles, parameters.atr_period)
        rsi_value = rsi(closes, parameters.rsi_period)
        assert atr_value is not None and rsi_value is not None

        latest = candles[-1]
        tolerance = parameters.pullback_tolerance_points * context.point
        atr_points = atr_value / context.point
        bullish_trend = fast > medium > slow
        bearish_trend = fast < medium < slow
        trend_points = abs(fast - slow) / context.point
        volatility_ok = parameters.min_atr_points <= atr_points <= parameters.max_atr_points
        trend_ok = trend_points >= parameters.min_trend_points
        bullish_body = latest.close > latest.open
        bearish_body = latest.close < latest.open

        buy_pullback = latest.low <= medium + tolerance and latest.close >= fast
        sell_pullback = latest.high >= medium - tolerance and latest.close <= fast
        buy_rsi_ok = parameters.buy_rsi_min <= rsi_value <= parameters.buy_rsi_max
        sell_rsi_ok = parameters.sell_rsi_min <= rsi_value <= parameters.sell_rsi_max
        buy_body_ok = not parameters.require_reversal_candle or bullish_body
        sell_body_ok = not parameters.require_reversal_candle or bearish_body

        inputs.update(
            fast_ema=str(fast),
            medium_ema=str(medium),
            slow_ema=str(slow),
            trend_points=str(trend_points),
            atr_points=str(atr_points),
            rsi=str(rsi_value),
            buy_pullback=buy_pullback,
            sell_pullback=sell_pullback,
            bullish_body=bullish_body,
            bearish_body=bearish_body,
        )

        if volatility_ok and trend_ok:
            if bullish_trend and buy_pullback and buy_rsi_ok and buy_body_ok:
                return self._finish(
                    SignalType.BUY,
                    "EMA_ATR_PULLBACK_CONTINUATION_BUY",
                    context,
                    config,
                    guard,
                )
            if bearish_trend and sell_pullback and sell_rsi_ok and sell_body_ok:
                return self._finish(
                    SignalType.SELL,
                    "EMA_ATR_PULLBACK_CONTINUATION_SELL",
                    context,
                    config,
                    guard,
                )
        return self._finish(
            SignalType.NO_TRADE,
            "EMA_ATR_PULLBACK_CONTINUATION_CONDITIONS_NOT_MET",
            context,
            config,
            guard,
        )


class _FastEmaAtrPullbackContinuationEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: EmaAtrPullbackContinuationParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.slow_ema_period,
            parameters.atr_period + 1,
            parameters.rsi_period + 1,
        )
        super().__init__(guards=guards, required=required)
        self.parameters = parameters
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
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.rsi = FastRollingRsi(period=parameters.rsi_period)
        self.min_atr_points = float(parameters.min_atr_points)
        self.max_atr_points = float(parameters.max_atr_points)
        self.min_trend_points = float(parameters.min_trend_points)
        self.pullback_tolerance = float(parameters.pullback_tolerance_points) * self.point
        self.buy_rsi_min = float(parameters.buy_rsi_min)
        self.buy_rsi_max = float(parameters.buy_rsi_max)
        self.sell_rsi_min = float(parameters.sell_rsi_min)
        self.sell_rsi_max = float(parameters.sell_rsi_max)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        open_price = float(candle.open)
        high = float(candle.high)
        low = float(candle.low)
        close = float(candle.close)
        fast, _ = self.fast.update(close)
        medium, _ = self.medium.update(close)
        slow, _ = self.slow.update(close)
        atr_value = self.atr.update(candle)
        rsi_value = self.rsi.update(close)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert fast is not None and medium is not None and slow is not None
        assert atr_value is not None and rsi_value is not None

        atr_points = atr_value / self.point
        trend_points = abs(fast - slow) / self.point
        volatility_ok = self.count_condition(
            "volatility_ok",
            self.min_atr_points <= atr_points <= self.max_atr_points,
        )
        trend_ok = self.count_condition(
            "trend_ok",
            trend_points >= self.min_trend_points,
        )
        bullish_trend = self.count_condition("bullish_trend", fast > medium > slow)
        bearish_trend = self.count_condition("bearish_trend", fast < medium < slow)
        buy_pullback = self.count_condition(
            "buy_pullback",
            low <= medium + self.pullback_tolerance and close >= fast,
        )
        sell_pullback = self.count_condition(
            "sell_pullback",
            high >= medium - self.pullback_tolerance and close <= fast,
        )
        buy_rsi_ok = self.count_condition(
            "buy_rsi_ok",
            self.buy_rsi_min <= rsi_value <= self.buy_rsi_max,
        )
        sell_rsi_ok = self.count_condition(
            "sell_rsi_ok",
            self.sell_rsi_min <= rsi_value <= self.sell_rsi_max,
        )
        buy_body_ok = self.count_condition(
            "buy_body_ok",
            not self.parameters.require_reversal_candle or close > open_price,
        )
        sell_body_ok = self.count_condition(
            "sell_body_ok",
            not self.parameters.require_reversal_candle or close < open_price,
        )
        buy_signal_ready = self.count_condition(
            "buy_signal_ready",
            volatility_ok
            and trend_ok
            and bullish_trend
            and buy_pullback
            and buy_rsi_ok
            and buy_body_ok,
        )
        sell_signal_ready = self.count_condition(
            "sell_signal_ready",
            volatility_ok
            and trend_ok
            and bearish_trend
            and sell_pullback
            and sell_rsi_ok
            and sell_body_ok,
        )
        self.count_condition("signal_ready", buy_signal_ready or sell_signal_ready)

        if volatility_ok and trend_ok:
            if buy_signal_ready:
                return SignalType.BUY, "EMA_ATR_PULLBACK_CONTINUATION_BUY"
            if sell_signal_ready:
                return SignalType.SELL, "EMA_ATR_PULLBACK_CONTINUATION_SELL"
        return SignalType.NO_TRADE, "EMA_ATR_PULLBACK_CONTINUATION_CONDITIONS_NOT_MET"


FastEmaAtrPullbackContinuationEvaluator = _FastEmaAtrPullbackContinuationEvaluator
