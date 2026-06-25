from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import atr, bollinger_bands, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter
from .rolling import FastRollingBollinger, FastRollingRsi


class BollingerRsiParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bollinger_period: int = Field(default=20, ge=2, le=500)
    bollinger_deviations: Decimal = decimal_parameter(
        "2",
        gt=0,
        le=10,
        description="Bollinger band width.",
        unit="standard deviations",
        impact="Lower values create more signals.",
    )
    rsi_period: int = Field(default=14, ge=2, le=200)
    buy_rsi_max: Decimal = decimal_parameter(
        "45",
        ge=0,
        le=100,
        description="Maximum RSI for BUY.",
        unit="RSI",
        impact="Lower values require stronger oversold conditions.",
    )
    sell_rsi_min: Decimal = decimal_parameter(
        "55",
        ge=0,
        le=100,
        description="Minimum RSI for SELL.",
        unit="RSI",
        impact="Higher values require stronger overbought conditions.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    atr_stop_multiplier: Decimal = decimal_parameter(
        "1.5",
        gt=0,
        le=20,
        description="ATR stop recommendation multiplier.",
        unit="ATR",
        impact="Higher values recommend a wider volatility-adjusted stop.",
    )
    require_touch_band: bool = Field(
        default=True,
        description="Use candle high/low for a band touch instead of requiring the close outside.",
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "BollingerRsiParameters":
        if self.buy_rsi_max > self.sell_rsi_min:
            raise ValueError("buy_rsi_max must not exceed sell_rsi_min")
        return self


class BollingerRsiMeanReversionStrategy(PreparedStrategy):
    name = "bb_rsi_mean_reversion"
    description = "Bollinger and RSI mean reversion with ATR stop diagnostics."
    parameters_model = BollingerRsiParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastBollingerRsiEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _FastBollingerRsiEvaluator(
            parameters=parameters,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def required_candles(self, parameters: BaseModel) -> int:
        values = BollingerRsiParameters.model_validate(parameters)
        return max(values.bollinger_period, values.rsi_period + 1, values.atr_period + 1)

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = BollingerRsiParameters.model_validate(raw)
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
        assert bands is not None and rsi_value is not None and atr_value is not None
        latest = candles[-1]
        buy_price = latest.low if parameters.require_touch_band else latest.close
        sell_price = latest.high if parameters.require_touch_band else latest.close
        inputs.update(
            lower_band=str(bands.lower),
            upper_band=str(bands.upper),
            rsi=str(rsi_value),
            atr=str(atr_value),
            recommended_stop_points=str(atr_value * parameters.atr_stop_multiplier / context.point),
        )
        if buy_price <= bands.lower and rsi_value <= parameters.buy_rsi_max:
            return self._finish(SignalType.BUY, "BB_RSI_BUY", context, config, guard)
        if sell_price >= bands.upper and rsi_value >= parameters.sell_rsi_min:
            return self._finish(SignalType.SELL, "BB_RSI_SELL", context, config, guard)
        return self._finish(
            SignalType.NO_TRADE, "BB_RSI_CONDITIONS_NOT_MET", context, config, guard
        )


class _FastBollingerRsiEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: BollingerRsiParameters,
        guards: BacktestGuards,
    ) -> None:
        super().__init__(
            guards=guards,
            required=max(
                parameters.bollinger_period,
                parameters.rsi_period + 1,
                parameters.atr_period + 1,
            ),
        )
        self.parameters = parameters
        self.bollinger = FastRollingBollinger(
            period=parameters.bollinger_period,
            deviations=float(parameters.bollinger_deviations),
        )
        self.rsi = FastRollingRsi(period=parameters.rsi_period)
        self.buy_rsi_max = float(parameters.buy_rsi_max)
        self.sell_rsi_min = float(parameters.sell_rsi_min)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        bands = self.bollinger.update(close)
        rsi_value = self.rsi.update(close)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert bands is not None and rsi_value is not None
        lower, upper = bands
        buy_price = float(candle.low) if self.parameters.require_touch_band else close
        sell_price = float(candle.high) if self.parameters.require_touch_band else close
        if buy_price <= lower and rsi_value <= self.buy_rsi_max:
            return SignalType.BUY, "BB_RSI_BUY"
        if sell_price >= upper and rsi_value >= self.sell_rsi_min:
            return SignalType.SELL, "BB_RSI_SELL"
        return SignalType.NO_TRADE, "BB_RSI_CONDITIONS_NOT_MET"


FastBollingerRsiEvaluator = _FastBollingerRsiEvaluator
