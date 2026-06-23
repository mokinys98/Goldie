from datetime import datetime
from decimal import Decimal

from ..models import CandleInput, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator
from .combo_parameters import (
    BollingerEmaRsiParameters,
    BollingerMomentumBreakoutParameters,
    BollingerRsiParameters,
    EmaAtrTrendParameters,
    EmaMomentumBreakoutParameters,
    RangeBreakScalperParameters,
)
from .rolling import (
    FastPriorRange,
    FastRollingAtr,
    FastRollingBollinger,
    FastRollingEma,
    FastRollingMomentum,
    FastRollingRsi,
)


class FastBollingerEmaRsiEvaluator:
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


class FastBollingerRsiEvaluator(FastGuardedEvaluator):
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


class FastEmaMomentumEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: EmaMomentumBreakoutParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.slow_ema_period,
            parameters.momentum_period + 1,
            parameters.atr_period + 1,
        )
        super().__init__(guards=guards, required=required)
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
        self.momentum = FastRollingMomentum(period=parameters.momentum_period)
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.min_momentum_points = float(parameters.min_momentum_points)
        self.min_atr_points = float(parameters.min_atr_points)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        fast, _ = self.fast.update(close)
        medium, _ = self.medium.update(close)
        slow, _ = self.slow.update(close)
        momentum_value = self.momentum.update(close)
        atr_value = self.atr.update(candle)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert fast is not None and medium is not None and slow is not None
        assert momentum_value is not None and atr_value is not None
        momentum_points = momentum_value / self.point
        if atr_value / self.point >= self.min_atr_points:
            if fast > medium > slow and momentum_points >= self.min_momentum_points:
                return SignalType.BUY, "EMA_MOMENTUM_BREAKOUT_BUY"
            if fast < medium < slow and momentum_points <= -self.min_momentum_points:
                return SignalType.SELL, "EMA_MOMENTUM_BREAKOUT_SELL"
        return SignalType.NO_TRADE, "EMA_MOMENTUM_BREAKOUT_CONDITIONS_NOT_MET"


class FastEmaAtrTrendEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: EmaAtrTrendParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        required = max(
            parameters.slow_ema_period + (1 if parameters.require_crossover else 0),
            parameters.atr_period + 1,
        )
        super().__init__(guards=guards, required=required)
        self.parameters = parameters
        self.point = float(point)
        self.fast = FastRollingEma(
            period=parameters.fast_ema_period,
            window_size=required,
            track_previous=parameters.require_crossover,
        )
        self.slow = FastRollingEma(
            period=parameters.slow_ema_period,
            window_size=required,
            track_previous=parameters.require_crossover,
        )
        self.atr = FastRollingAtr(period=parameters.atr_period)
        self.min_atr_points = float(parameters.min_atr_points)
        self.max_atr_points = float(parameters.max_atr_points)
        self.min_trend_points = float(parameters.min_trend_points)

    def evaluate(
        self, candle: CandleInput, observed_at: datetime
    ) -> tuple[SignalType, str]:
        self.count += 1
        close = float(candle.close)
        fast, previous_fast = self.fast.update(close)
        slow, previous_slow = self.slow.update(close)
        atr_value = self.atr.update(candle)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        assert fast is not None and slow is not None and atr_value is not None
        trend_points = (fast - slow) / self.point
        atr_points = atr_value / self.point
        crossed_up = crossed_down = True
        if self.parameters.require_crossover:
            assert previous_fast is not None and previous_slow is not None
            crossed_up = previous_fast <= previous_slow and fast > slow
            crossed_down = previous_fast >= previous_slow and fast < slow
        volatile = self.min_atr_points <= atr_points <= self.max_atr_points
        if volatile and trend_points >= self.min_trend_points and crossed_up:
            return SignalType.BUY, "EMA_ATR_TREND_BUY"
        if volatile and trend_points <= -self.min_trend_points and crossed_down:
            return SignalType.SELL, "EMA_ATR_TREND_SELL"
        return SignalType.NO_TRADE, "EMA_ATR_TREND_CONDITIONS_NOT_MET"


class FastBollingerMomentumEvaluator(FastGuardedEvaluator):
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


class FastRangeBreakEvaluator(FastGuardedEvaluator):
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
