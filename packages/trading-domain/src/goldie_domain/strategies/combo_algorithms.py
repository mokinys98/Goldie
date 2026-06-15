from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import atr, bollinger_bands, ema_series, momentum, rsi
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards, common_guard, completed, trade_prices


def _decimal_field(
    default: str,
    *,
    ge: int | None = None,
    gt: int | None = None,
    le: int,
    description: str,
    unit: str,
    impact: str,
) -> Any:
    return Field(
        default=Decimal(default),
        ge=ge,
        gt=gt,
        le=le,
        description=description,
        json_schema_extra={"unit": unit, "impact": impact},
    )


class BollingerRsiParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bollinger_period: int = Field(default=20, ge=2, le=500)
    bollinger_deviations: Decimal = _decimal_field(
        "2",
        gt=0,
        le=10,
        description="Bollinger band width.",
        unit="standard deviations",
        impact="Lower values create more signals.",
    )
    rsi_period: int = Field(default=14, ge=2, le=200)
    buy_rsi_max: Decimal = _decimal_field(
        "45",
        ge=0,
        le=100,
        description="Maximum RSI for BUY.",
        unit="RSI",
        impact="Lower values require stronger oversold conditions.",
    )
    sell_rsi_min: Decimal = _decimal_field(
        "55",
        ge=0,
        le=100,
        description="Minimum RSI for SELL.",
        unit="RSI",
        impact="Higher values require stronger overbought conditions.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    atr_stop_multiplier: Decimal = _decimal_field(
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


class EmaMomentumBreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=5, ge=2, le=200)
    medium_ema_period: int = Field(default=13, ge=3, le=300)
    slow_ema_period: int = Field(default=34, ge=4, le=500)
    momentum_period: int = Field(default=5, ge=1, le=100)
    min_momentum_points: Decimal = _decimal_field(
        "10",
        gt=0,
        le=10000,
        description="Minimum directional momentum.",
        unit="points",
        impact="Higher values filter weak breakouts.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = _decimal_field(
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


class EmaAtrTrendParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=9, ge=2, le=200)
    slow_ema_period: int = Field(default=21, ge=3, le=500)
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = _decimal_field(
        "5",
        ge=0,
        le=10000,
        description="Minimum ATR volatility.",
        unit="points",
        impact="Higher values suppress signals in quiet markets.",
    )
    max_atr_points: Decimal = _decimal_field(
        "500",
        gt=0,
        le=100000,
        description="Maximum ATR volatility.",
        unit="points",
        impact="Lower values suppress signals in extreme volatility.",
    )
    min_trend_points: Decimal = _decimal_field(
        "0",
        ge=0,
        le=10000,
        description="Minimum EMA separation.",
        unit="points",
        impact="Higher values require a stronger trend.",
    )
    atr_stop_multiplier: Decimal = _decimal_field(
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


class BollingerMomentumBreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bollinger_period: int = Field(default=20, ge=2, le=500)
    bollinger_deviations: Decimal = _decimal_field(
        "2",
        gt=0,
        le=10,
        description="Bollinger band width.",
        unit="standard deviations",
        impact="Lower values create more breakout signals.",
    )
    momentum_period: int = Field(default=5, ge=1, le=100)
    min_momentum_points: Decimal = _decimal_field(
        "10",
        gt=0,
        le=10000,
        description="Minimum breakout momentum.",
        unit="points",
        impact="Higher values require a stronger breakout.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = _decimal_field(
        "5",
        ge=0,
        le=10000,
        description="Minimum ATR volatility.",
        unit="points",
        impact="Higher values avoid low-volatility breakouts.",
    )


class BollingerEmaRsiParameters(BollingerRsiParameters):
    fast_ema_period: int = Field(default=9, ge=2, le=200)
    slow_ema_period: int = Field(default=21, ge=3, le=500)
    max_trend_points: Decimal = _decimal_field(
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


class RangeBreakScalperParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=3, ge=2, le=50)
    slow_ema_period: int = Field(default=8, ge=3, le=100)
    rsi_period: int = Field(default=7, ge=2, le=100)
    buy_rsi_min: Decimal = _decimal_field(
        "55",
        ge=0,
        le=100,
        description="Minimum RSI for BUY.",
        unit="RSI",
        impact="Higher values require stronger upward momentum.",
    )
    sell_rsi_max: Decimal = _decimal_field(
        "45",
        ge=0,
        le=100,
        description="Maximum RSI for SELL.",
        unit="RSI",
        impact="Lower values require stronger downward momentum.",
    )
    range_lookback: int = Field(default=5, ge=2, le=100)
    min_breakout_points: Decimal = _decimal_field(
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


class _ReplayBacktestEvaluator:
    def __init__(
        self,
        *,
        strategy: Any,
        config: Any,
        required_candles: int,
        point: Decimal,
        spread_points: Decimal,
    ) -> None:
        self.strategy = strategy
        self.config = config
        self.point = point
        self.half_spread = spread_points * point / Decimal("2")
        self.guards = BacktestGuards.from_config(config, spread_points=spread_points)
        self.candles: deque[CandleInput] = deque(maxlen=required_candles)

    def evaluate(self, candle: CandleInput, observed_at: datetime) -> tuple[SignalType, str]:
        if not isinstance(candle, CandleInput):
            candle = CandleInput(
                opened_at=candle.opened_at,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                tick_volume=candle.tick_volume,
                is_complete=candle.is_complete,
            )
        self.candles.append(candle)
        rejection = self.guards.rejection_reason(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        decision = self.strategy.evaluate(
            MarketContext(
                observed_at=observed_at,
                evaluated_at=observed_at,
                bid=candle.close - self.half_spread,
                ask=candle.close + self.half_spread,
                point=self.point,
                candles=list(self.candles),
            ),
            self.config,
        )
        return decision.signal, decision.reason_code


class _ComboStrategy:
    parameters_model: type[BaseModel]

    def create_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> _ReplayBacktestEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return _ReplayBacktestEvaluator(
            strategy=self,
            config=config,
            required_candles=self.required_candles(parameters),
            point=point,
            spread_points=spread_points,
        )

    def _start(
        self, context: MarketContext, config: Any
    ) -> tuple[list[CandleInput], BaseModel, dict[str, Any], dict[str, Any] | SignalDecision]:
        candles = completed(context)
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        inputs: dict[str, Any] = {"strategy": self.name, "complete_candles": len(candles)}
        return candles, parameters, inputs, common_guard(context, config, inputs)

    def _finish(
        self,
        signal: SignalType,
        reason: str,
        context: MarketContext,
        config: Any,
        guard: dict[str, Any],
    ) -> SignalDecision:
        if signal == SignalType.NO_TRADE:
            return SignalDecision(signal=signal, reason_code=reason, **guard)
        entry, stop_loss, take_profit = trade_prices(signal, context, config)
        return SignalDecision(
            signal=signal,
            reason_code=reason,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            **guard,
        )


class BollingerRsiMeanReversionStrategy(_ComboStrategy):
    name = "bb_rsi_mean_reversion"
    description = "Bollinger and RSI mean reversion with ATR stop diagnostics."
    parameters_model = BollingerRsiParameters

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


class EmaMomentumBreakoutStrategy(_ComboStrategy):
    name = "ema_momentum_breakout"
    description = "Multi-EMA trend alignment confirmed by momentum and ATR."
    parameters_model = EmaMomentumBreakoutParameters

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


class EmaAtrTrendStrategy(_ComboStrategy):
    name = "ema_atr_trend"
    description = "EMA trend following constrained by an ATR volatility range."
    parameters_model = EmaAtrTrendParameters

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


class BollingerMomentumBreakoutStrategy(_ComboStrategy):
    name = "bb_momentum_breakout"
    description = "Bollinger close breakout confirmed by momentum and ATR."
    parameters_model = BollingerMomentumBreakoutParameters

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


class BollingerEmaRsiMeanReversionStrategy(_ComboStrategy):
    name = "bb_ema_rsi_mean_reversion"
    description = "Bollinger and RSI mean reversion limited to weak EMA trends."
    parameters_model = BollingerEmaRsiParameters

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


class RangeBreakScalperStrategy(_ComboStrategy):
    name = "range_break_scalper"
    description = "Short EMA and RSI scalper for closes breaking the recent range."
    parameters_model = RangeBreakScalperParameters

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
