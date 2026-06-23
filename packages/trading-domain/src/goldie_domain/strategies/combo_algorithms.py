from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from ..indicators import atr, bollinger_bands, ema_series, momentum, rsi
from ..models import MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import PreparedStrategy
from .combo_evaluators import (
    FastBollingerEmaRsiEvaluator,
    FastBollingerMomentumEvaluator,
    FastBollingerRsiEvaluator,
    FastEmaAtrTrendEvaluator,
    FastEmaMomentumEvaluator,
    FastRangeBreakEvaluator,
)
from .combo_parameters import (
    BollingerEmaRsiParameters,
    BollingerMomentumBreakoutParameters,
    BollingerRsiParameters,
    EmaAtrTrendParameters,
    EmaMomentumBreakoutParameters,
    RangeBreakScalperParameters,
)


class BollingerRsiMeanReversionStrategy(PreparedStrategy):
    name = "bb_rsi_mean_reversion"
    description = "Bollinger and RSI mean reversion with ATR stop diagnostics."
    parameters_model = BollingerRsiParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> FastBollingerRsiEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return FastBollingerRsiEvaluator(
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


class EmaMomentumBreakoutStrategy(PreparedStrategy):
    name = "ema_momentum_breakout"
    description = "Multi-EMA trend alignment confirmed by momentum and ATR."
    parameters_model = EmaMomentumBreakoutParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> FastEmaMomentumEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return FastEmaMomentumEvaluator(
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


class EmaAtrTrendStrategy(PreparedStrategy):
    name = "ema_atr_trend"
    description = "EMA trend following constrained by an ATR volatility range."
    parameters_model = EmaAtrTrendParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> FastEmaAtrTrendEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return FastEmaAtrTrendEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

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


class BollingerMomentumBreakoutStrategy(PreparedStrategy):
    name = "bb_momentum_breakout"
    description = "Bollinger close breakout confirmed by momentum and ATR."
    parameters_model = BollingerMomentumBreakoutParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> FastBollingerMomentumEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return FastBollingerMomentumEvaluator(
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


class BollingerEmaRsiMeanReversionStrategy(PreparedStrategy):
    name = "bb_ema_rsi_mean_reversion"
    description = "Bollinger and RSI mean reversion limited to weak EMA trends."
    parameters_model = BollingerEmaRsiParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> FastBollingerEmaRsiEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return FastBollingerEmaRsiEvaluator(
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


class RangeBreakScalperStrategy(PreparedStrategy):
    name = "range_break_scalper"
    description = "Short EMA and RSI scalper for closes breaking the recent range."
    parameters_model = RangeBreakScalperParameters

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> FastRangeBreakEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return FastRangeBreakEvaluator(
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
