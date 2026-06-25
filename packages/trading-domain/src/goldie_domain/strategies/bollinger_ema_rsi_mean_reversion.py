from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..indicators import atr, bollinger_bands, ema_series, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import PreparedStrategy
from .bollinger_rsi_mean_reversion import BollingerRsiParameters
from .fields import decimal_parameter
from .rolling import FastRollingBollinger, FastRollingEma, FastRollingRsi


class BollingerEmaRsiParameters(BollingerRsiParameters):
    fast_ema_period: int = Field(default=9, ge=2, le=200)
    slow_ema_period: int = Field(default=21, ge=3, le=500)
    max_trend_points: Decimal = decimal_parameter(
        "30",
        ge=0,
        le=10000,
        description="Maximum EMA separation.",
        unit="points",
        impact="Lower values restrict mean reversion to flatter markets.",
    )

    @model_validator(mode="after")
    def validate_ema_periods(self) -> "BollingerEmaRsiParameters":
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be lower than slow_ema_period")
        return self


class BollingerEmaRsiMeanReversionStrategy(PreparedStrategy):
    name = "bb_ema_rsi_mean_reversion"
    description = "Bollinger and RSI mean reversion limited to weak EMA trends."
    parameters_model = BollingerEmaRsiParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastBollingerEmaRsiEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastBollingerEmaRsiEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = BollingerEmaRsiParameters.model_validate(parameters)
        return max(
            values.bollinger_period,
            values.rsi_period + 1,
            values.atr_period + 1,
            values.slow_ema_period,
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = BollingerEmaRsiParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )
        closes = [item.close for item in candles]
        bands = bollinger_bands(
            closes, parameters.bollinger_period, parameters.bollinger_deviations
        )
        rsi_value = rsi(closes, parameters.rsi_period)
        atr_value = atr(candles, parameters.atr_period)
        fast = ema_series(closes, parameters.fast_ema_period)[-1]
        slow = ema_series(closes, parameters.slow_ema_period)[-1]
        assert bands is not None and rsi_value is not None and atr_value is not None
        trend_points = abs(fast - slow) / context.point
        latest = candles[-1]
        buy_price = latest.low if parameters.require_touch_band else latest.close
        sell_price = latest.high if parameters.require_touch_band else latest.close
        inputs.update(
            lower_band=str(bands.lower),
            upper_band=str(bands.upper),
            rsi=str(rsi_value),
            trend_points=str(trend_points),
            atr=str(atr_value),
            recommended_stop_points=str(atr_value * parameters.atr_stop_multiplier / context.point),
        )
        if trend_points <= parameters.max_trend_points:
            if buy_price <= bands.lower and rsi_value <= parameters.buy_rsi_max:
                return self._finish(SignalType.BUY, "BB_EMA_RSI_BUY", context, config, guard)
            if sell_price >= bands.upper and rsi_value >= parameters.sell_rsi_min:
                return self._finish(SignalType.SELL, "BB_EMA_RSI_SELL", context, config, guard)
        return self._finish(
            SignalType.NO_TRADE, "BB_EMA_RSI_CONDITIONS_NOT_MET", context, config, guard
        )


class _FastBollingerEmaRsiEvaluator:
    def __init__(
        self,
        *,
        parameters: BollingerEmaRsiParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        self.parameters = parameters
        self.point = float(point)
        self.guards = guards
        self.skip_guards = (
            guards.spread_points <= guards.max_spread_points
            and guards.timezone.key == "UTC"
            and guards.start_time == datetime.min.time()
            and guards.end_time >= datetime.max.time().replace(microsecond=0)
        )
        self.required = max(
            parameters.bollinger_period,
            parameters.rsi_period + 1,
            parameters.atr_period + 1,
            parameters.slow_ema_period,
        )
        self.count = 0
        self.bollinger = FastRollingBollinger(
            period=parameters.bollinger_period,
            deviations=float(parameters.bollinger_deviations),
        )
        self.rsi = FastRollingRsi(period=parameters.rsi_period)
        self.fast_ema = FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=self.required,
            track_previous=False,
        )
        self.slow_ema = FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=self.required,
            track_previous=False,
        )
        self.buy_rsi_max = float(parameters.buy_rsi_max)
        self.sell_rsi_min = float(parameters.sell_rsi_min)
        self.max_trend_points = float(parameters.max_trend_points)

    def evaluate(
        self,
        candle: CandleInput,
        observed_at: datetime,
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        bands = self.bollinger.update(close)
        rsi_value = self.rsi.update(close)
        fast, _ = self.fast_ema.update(close)
        slow, _ = self.slow_ema.update(close)
        rejection = None if self.skip_guards else self.guards.rejection_reason(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert bands is not None and rsi_value is not None
        assert fast is not None and slow is not None
        lower, upper = bands
        trend_points = abs(fast - slow) / self.point
        buy_price = float(candle.low) if self.parameters.require_touch_band else close
        sell_price = float(candle.high) if self.parameters.require_touch_band else close
        if trend_points <= self.max_trend_points:
            if buy_price <= lower and rsi_value <= self.buy_rsi_max:
                return SignalType.BUY, "BB_EMA_RSI_BUY"
            if sell_price >= upper and rsi_value >= self.sell_rsi_min:
                return SignalType.SELL, "BB_EMA_RSI_SELL"
        return SignalType.NO_TRADE, "BB_EMA_RSI_CONDITIONS_NOT_MET"


FastBollingerEmaRsiEvaluator = _FastBollingerEmaRsiEvaluator
