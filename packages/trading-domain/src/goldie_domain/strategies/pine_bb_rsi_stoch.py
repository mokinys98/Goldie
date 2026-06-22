from collections import deque
from datetime import datetime
from decimal import Decimal
from math import sqrt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import bollinger_bands, sma
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
    optimization_minimum: str | int | None = None,
    optimization_maximum: str | int | None = None,
) -> Any:
    extra: dict[str, Any] = {"unit": unit, "impact": impact}
    if optimization_minimum is not None:
        extra["optimization_minimum"] = optimization_minimum
    if optimization_maximum is not None:
        extra["optimization_maximum"] = optimization_maximum
    return Field(
        default=Decimal(default),
        ge=ge,
        gt=gt,
        le=le,
        description=description,
        json_schema_extra=extra,
    )


class PineBollingerRsiStochParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bollinger_period: int = Field(
        default=20,
        ge=2,
        le=500,
        description="Bollinger SMA period.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth and delay band changes.",
            "optimization_minimum": 20,
            "optimization_maximum": 120,
        },
    )
    bollinger_deviations: Decimal = _decimal_field(
        "2",
        gt=0,
        le=10,
        description="Bollinger standard-deviation multiplier.",
        unit="standard deviations",
        impact="Higher values widen the bands and reduce crossings.",
        optimization_minimum="1.5",
        optimization_maximum="3.2",
    )
    rsi_period: int = Field(
        default=14,
        ge=2,
        le=200,
        description="Goldie rolling RSI period.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make RSI less responsive.",
            "optimization_minimum": 7,
            "optimization_maximum": 35,
        },
    )
    rsi_overbought: Decimal = _decimal_field(
        "63",
        ge=0,
        le=100,
        description="Minimum RSI for a top signal.",
        unit="RSI",
        impact="Higher values make RSI sell confirmation stricter.",
        optimization_minimum="60",
        optimization_maximum="80",
    )
    rsi_oversold: Decimal = _decimal_field(
        "30",
        ge=0,
        le=100,
        description="Maximum RSI for a bottom signal.",
        unit="RSI",
        impact="Lower values make RSI buy confirmation stricter.",
        optimization_minimum="20",
        optimization_maximum="40",
    )
    stochastic_period: int = Field(
        default=14,
        ge=1,
        le=200,
        description="Stochastic lookback period.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values compare price with a longer range.",
            "optimization_minimum": 7,
            "optimization_maximum": 40,
        },
    )
    stochastic_overbought: Decimal = _decimal_field(
        "80",
        ge=0,
        le=100,
        description="Minimum smoothed %K for bearish crossover confirmation.",
        unit="stochastic",
        impact="Higher values make sell confirmation stricter.",
        optimization_minimum="70",
        optimization_maximum="90",
    )
    stochastic_oversold: Decimal = _decimal_field(
        "20",
        ge=0,
        le=100,
        description="Maximum smoothed %K for bullish crossover confirmation.",
        unit="stochastic",
        impact="Lower values make buy confirmation stricter.",
        optimization_minimum="10",
        optimization_maximum="30",
    )
    smooth_k: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Stochastic %K SMA smoothing.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth stochastic signals.",
            "optimization_minimum": 2,
            "optimization_maximum": 8,
        },
    )
    smooth_d: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Stochastic %D SMA smoothing.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values delay stochastic crossovers.",
            "optimization_minimum": 2,
            "optimization_maximum": 8,
        },
    )
    trade_direction: Literal["BOTH", "BUY_ONLY", "SELL_ONLY"] = Field(
        default="BOTH",
        description="Allowed signal direction for directional robustness tests.",
        json_schema_extra={
            "unit": "mode",
            "impact": "Use BUY_ONLY or SELL_ONLY to isolate asymmetric edge.",
        },
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "PineBollingerRsiStochParameters":
        if self.rsi_oversold > self.rsi_overbought:
            raise ValueError("rsi_oversold must not exceed rsi_overbought")
        if self.stochastic_oversold > self.stochastic_overbought:
            raise ValueError("stochastic_oversold must not exceed stochastic_overbought")
        return self


def _rolling_rsi(values: list[Decimal], period: int) -> Decimal | None:
    if len(values) < period + 1:
        return None
    changes = [right - left for left, right in zip(values, values[1:], strict=False)]
    gains = [max(change, Decimal("0")) for change in changes]
    losses = [max(-change, Decimal("0")) for change in changes]
    average_gain = sum(gains[-period:], Decimal("0")) / Decimal(period)
    average_loss = sum(losses[-period:], Decimal("0")) / Decimal(period)
    return _rsi_from_averages(average_gain, average_loss)


def _rsi_from_averages(gain: Decimal, loss: Decimal) -> Decimal:
    if loss == 0:
        return Decimal("100") if gain > 0 else Decimal("50")
    strength = gain / loss
    return Decimal("100") - Decimal("100") / (Decimal("1") + strength)


def _stochastic_kd(
    candles: list[CandleInput], parameters: PineBollingerRsiStochParameters
) -> tuple[list[Decimal], list[Decimal]]:
    raw: list[Decimal] = []
    for end in range(parameters.stochastic_period - 1, len(candles)):
        window = candles[end - parameters.stochastic_period + 1 : end + 1]
        lowest = min(c.low for c in window)
        highest = max(c.high for c in window)
        width = highest - lowest
        raw.append(
            (candles[end].close - lowest) / width * Decimal("100") if width else Decimal("50")
        )
    k_values = [
        value
        for end in range(parameters.smooth_k - 1, len(raw))
        if (value := sma(raw[: end + 1], parameters.smooth_k)) is not None
    ]
    d_values = [
        value
        for end in range(parameters.smooth_d - 1, len(k_values))
        if (value := sma(k_values[: end + 1], parameters.smooth_d)) is not None
    ]
    return k_values, d_values


class PineBollingerRsiStochStrategy:
    name = "pine_bb_rsi_stoch"
    description = (
        "Pine-inspired Bollinger, rolling RSI and stochastic signal port. BUY and "
        "SELL are directional Goldie signals, not Pine position commands."
    )
    parameters_model = PineBollingerRsiStochParameters

    def required_candles(self, parameters: BaseModel) -> int:
        values = PineBollingerRsiStochParameters.model_validate(parameters)
        return max(
            values.bollinger_period + 1,
            values.rsi_period + 1,
            values.stochastic_period + values.smooth_k + values.smooth_d - 1,
        )

    def create_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_PreparedPineEvaluator":
        return _PreparedPineEvaluator(
            parameters=PineBollingerRsiStochParameters.model_validate(config.strategy.parameters),
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "_FastPineEvaluator":
        return _FastPineEvaluator(
            parameters=PineBollingerRsiStochParameters.model_validate(config.strategy.parameters),
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles = completed(context)
        parameters = PineBollingerRsiStochParameters.model_validate(config.strategy.parameters)
        inputs: dict[str, str | int | bool | None] = {
            "strategy": self.name,
            "complete_candles": len(candles),
        }
        guard = common_guard(context, config, inputs)
        if isinstance(guard, SignalDecision):
            return guard
        if len(candles) < self.required_candles(parameters):
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                reason_code="INSUFFICIENT_COMPLETED_CANDLES",
                **guard,
            )

        closes = [c.close for c in candles]
        current_bands = bollinger_bands(
            closes, parameters.bollinger_period, parameters.bollinger_deviations
        )
        previous_bands = bollinger_bands(
            closes[:-1], parameters.bollinger_period, parameters.bollinger_deviations
        )
        rsi_value = _rolling_rsi(closes, parameters.rsi_period)
        k_values, d_values = _stochastic_kd(candles, parameters)
        assert current_bands and previous_bands and rsi_value is not None
        current_k, previous_k = k_values[-1], k_values[-2]
        current_d, previous_d = d_values[-1], d_values[-2]
        signal, reason = _decision(
            previous_close=candles[-2].close,
            current_close=candles[-1].close,
            previous_open=candles[-2].open,
            current_open=candles[-1].open,
            previous_lower=previous_bands.lower,
            previous_upper=previous_bands.upper,
            current_lower=current_bands.lower,
            current_upper=current_bands.upper,
            rsi_value=rsi_value,
            previous_k=previous_k,
            current_k=current_k,
            previous_d=previous_d,
            current_d=current_d,
            parameters=parameters,
        )
        inputs.update(
            {
                "rsi": str(rsi_value),
                "stochastic_k": str(current_k),
                "stochastic_d": str(current_d),
                "upper_band": str(current_bands.upper),
                "lower_band": str(current_bands.lower),
            }
        )
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


def _decision(
    *,
    previous_close: Any,
    current_close: Any,
    previous_open: Any,
    current_open: Any,
    previous_lower: Any,
    previous_upper: Any,
    current_lower: Any,
    current_upper: Any,
    rsi_value: Any,
    previous_k: Any,
    current_k: Any,
    previous_d: Any,
    current_d: Any,
    parameters: PineBollingerRsiStochParameters,
) -> tuple[SignalType, str]:
    top_cross = previous_close <= previous_upper and current_close > current_upper
    bottom_cross = previous_open >= previous_lower and current_open < current_lower
    cross_up = previous_k <= previous_d and current_k > current_d
    cross_down = previous_k >= previous_d and current_k < current_d
    top = top_cross and (
        rsi_value > parameters.rsi_overbought
        or (cross_down and current_k > parameters.stochastic_overbought)
    )
    bottom = bottom_cross and (
        rsi_value < parameters.rsi_oversold
        or (cross_up and current_k < parameters.stochastic_oversold)
    )
    if bottom:
        if parameters.trade_direction == "SELL_ONLY":
            return SignalType.NO_TRADE, "PINE_BB_RSI_STOCH_BUY_DISABLED"
        return SignalType.BUY, "PINE_BB_RSI_STOCH_BUY"
    if top:
        if parameters.trade_direction == "BUY_ONLY":
            return SignalType.NO_TRADE, "PINE_BB_RSI_STOCH_SELL_DISABLED"
        return SignalType.SELL, "PINE_BB_RSI_STOCH_SELL"
    return SignalType.NO_TRADE, "PINE_BB_RSI_STOCH_CONDITIONS_NOT_MET"


class _DecimalRollingMean:
    def __init__(self, period: int) -> None:
        self.period = period
        self.values: deque[Decimal] = deque(maxlen=period)
        self.total = Decimal("0")

    def update(self, value: Decimal) -> Decimal | None:
        if len(self.values) == self.period:
            self.total -= self.values[0]
        self.values.append(value)
        self.total += value
        return self.total / self.period if len(self.values) == self.period else None


class _DecimalRollingBollinger:
    def __init__(self, period: int, deviations: Decimal) -> None:
        self.period = period
        self.deviations = deviations
        self.values: deque[Decimal] = deque(maxlen=period)
        self.total = Decimal("0")
        self.total_squared = Decimal("0")

    def update(self, value: Decimal) -> tuple[Decimal, Decimal] | None:
        if len(self.values) == self.period:
            removed = self.values[0]
            self.total -= removed
            self.total_squared -= removed * removed
        self.values.append(value)
        self.total += value
        self.total_squared += value * value
        if len(self.values) < self.period:
            return None
        middle = self.total / self.period
        variance = self.total_squared / self.period - middle * middle
        width = self.deviations * max(variance, Decimal("0")).sqrt()
        return middle - width, middle + width


class _DecimalRollingRsi:
    def __init__(self, period: int) -> None:
        self.period = period
        self.previous: Decimal | None = None
        self.gains: deque[Decimal] = deque(maxlen=period)
        self.losses: deque[Decimal] = deque(maxlen=period)
        self.gain = Decimal("0")
        self.loss = Decimal("0")

    def update(self, value: Decimal) -> Decimal | None:
        if self.previous is None:
            self.previous = value
            return None
        change = value - self.previous
        self.previous = value
        gain = max(change, Decimal("0"))
        loss = max(-change, Decimal("0"))
        if len(self.gains) == self.period:
            self.gain -= self.gains[0]
            self.loss -= self.losses[0]
        self.gains.append(gain)
        self.losses.append(loss)
        self.gain += gain
        self.loss += loss
        if len(self.gains) < self.period:
            return None
        return _rsi_from_averages(self.gain / self.period, self.loss / self.period)


class _DecimalRollingStochastic:
    def __init__(self, parameters: PineBollingerRsiStochParameters) -> None:
        self.period = parameters.stochastic_period
        self.index = 0
        self.highs: deque[tuple[int, Decimal]] = deque()
        self.lows: deque[tuple[int, Decimal]] = deque()
        self.k_mean = _DecimalRollingMean(parameters.smooth_k)
        self.d_mean = _DecimalRollingMean(parameters.smooth_d)

    def update(self, candle: CandleInput) -> tuple[Decimal | None, Decimal | None]:
        cutoff = self.index - self.period + 1
        while self.highs and self.highs[0][0] < cutoff:
            self.highs.popleft()
        while self.lows and self.lows[0][0] < cutoff:
            self.lows.popleft()
        while self.highs and self.highs[-1][1] <= candle.high:
            self.highs.pop()
        while self.lows and self.lows[-1][1] >= candle.low:
            self.lows.pop()
        self.highs.append((self.index, candle.high))
        self.lows.append((self.index, candle.low))
        self.index += 1
        if self.index < self.period:
            return None, None
        width = self.highs[0][1] - self.lows[0][1]
        raw = (candle.close - self.lows[0][1]) / width * Decimal("100") if width else Decimal("50")
        k = self.k_mean.update(raw)
        d = self.d_mean.update(k) if k is not None else None
        return k, d


class _PreparedPineEvaluator:
    def __init__(
        self, *, parameters: PineBollingerRsiStochParameters, guards: BacktestGuards
    ) -> None:
        self.parameters = parameters
        self.guards = guards
        self.required = PineBollingerRsiStochStrategy().required_candles(parameters)
        self.count = 0
        self.bands = _DecimalRollingBollinger(
            parameters.bollinger_period, parameters.bollinger_deviations
        )
        self.rsi = _DecimalRollingRsi(parameters.rsi_period)
        self.stochastic = _DecimalRollingStochastic(parameters)
        self.previous_close: Decimal | None = None
        self.previous_open: Decimal | None = None
        self.previous_bands: tuple[Decimal, Decimal] | None = None
        self.previous_k: Decimal | None = None
        self.previous_d: Decimal | None = None

    def evaluate(self, candle: CandleInput, observed_at: datetime) -> tuple[SignalType, str]:
        self.count += 1
        bands = self.bands.update(candle.close)
        rsi_value = self.rsi.update(candle.close)
        k, d = self.stochastic.update(candle)
        rejection = self.guards.rejection_reason(observed_at)
        if rejection:
            result = SignalType.NO_TRADE, rejection
        elif self.count < self.required:
            result = SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        elif all(
            value is not None
            for value in (
                bands,
                self.previous_bands,
                rsi_value,
                k,
                d,
                self.previous_k,
                self.previous_d,
            )
        ):
            assert bands and self.previous_bands
            result = _decision(
                previous_close=self.previous_close,
                current_close=candle.close,
                previous_open=self.previous_open,
                current_open=candle.open,
                previous_lower=self.previous_bands[0],
                previous_upper=self.previous_bands[1],
                current_lower=bands[0],
                current_upper=bands[1],
                rsi_value=rsi_value,
                previous_k=self.previous_k,
                current_k=k,
                previous_d=self.previous_d,
                current_d=d,
                parameters=self.parameters,
            )
        else:
            result = SignalType.NO_TRADE, "PINE_BB_RSI_STOCH_CONDITIONS_NOT_MET"
        self.previous_close = candle.close
        self.previous_open = candle.open
        self.previous_bands = bands
        if k is not None:
            self.previous_k = k
        if d is not None:
            self.previous_d = d
        return result


class _FloatRollingMean:
    def __init__(self, period: int) -> None:
        self.period = period
        self.values: deque[float] = deque(maxlen=period)
        self.total = 0.0

    def update(self, value: float) -> float | None:
        if len(self.values) == self.period:
            self.total -= self.values[0]
        self.values.append(value)
        self.total += value
        return self.total / self.period if len(self.values) == self.period else None


class _FastPineEvaluator:
    def __init__(
        self, *, parameters: PineBollingerRsiStochParameters, guards: BacktestGuards
    ) -> None:
        self.parameters = parameters
        self.guards = guards
        self.required = PineBollingerRsiStochStrategy().required_candles(parameters)
        self.count = 0
        self.period = parameters.bollinger_period
        self.deviations = float(parameters.bollinger_deviations)
        self.band_values: deque[float] = deque(maxlen=self.period)
        self.band_total = self.band_squared = 0.0
        self.rsi_period = parameters.rsi_period
        self.previous_rsi_close: float | None = None
        self.rsi_gains: deque[float] = deque(maxlen=self.rsi_period)
        self.rsi_losses: deque[float] = deque(maxlen=self.rsi_period)
        self.rsi_gain = self.rsi_loss = 0.0
        self.stoch_period = parameters.stochastic_period
        self.index = 0
        self.highs: deque[tuple[int, float]] = deque()
        self.lows: deque[tuple[int, float]] = deque()
        self.k_mean = _FloatRollingMean(parameters.smooth_k)
        self.d_mean = _FloatRollingMean(parameters.smooth_d)
        self.previous_close: float | None = None
        self.previous_open: float | None = None
        self.previous_bands: tuple[float, float] | None = None
        self.previous_k: float | None = None
        self.previous_d: float | None = None

    def _update_bands(self, value: float) -> tuple[float, float] | None:
        if len(self.band_values) == self.period:
            removed = self.band_values[0]
            self.band_total -= removed
            self.band_squared -= removed * removed
        self.band_values.append(value)
        self.band_total += value
        self.band_squared += value * value
        if len(self.band_values) < self.period:
            return None
        middle = self.band_total / self.period
        variance = max(0.0, self.band_squared / self.period - middle * middle)
        width = self.deviations * sqrt(variance)
        return middle - width, middle + width

    def _update_rsi(self, value: float) -> float | None:
        if self.previous_rsi_close is None:
            self.previous_rsi_close = value
            return None
        change = value - self.previous_rsi_close
        self.previous_rsi_close = value
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if len(self.rsi_gains) == self.rsi_period:
            self.rsi_gain -= self.rsi_gains[0]
            self.rsi_loss -= self.rsi_losses[0]
        self.rsi_gains.append(gain)
        self.rsi_losses.append(loss)
        self.rsi_gain += gain
        self.rsi_loss += loss
        if len(self.rsi_gains) < self.rsi_period:
            return None
        if self.rsi_loss == 0:
            return 100.0 if self.rsi_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + self.rsi_gain / self.rsi_loss)

    def _update_stochastic(self, candle: CandleInput) -> tuple[float | None, float | None]:
        cutoff = self.index - self.stoch_period + 1
        high, low, close = float(candle.high), float(candle.low), float(candle.close)
        while self.highs and self.highs[0][0] < cutoff:
            self.highs.popleft()
        while self.lows and self.lows[0][0] < cutoff:
            self.lows.popleft()
        while self.highs and self.highs[-1][1] <= high:
            self.highs.pop()
        while self.lows and self.lows[-1][1] >= low:
            self.lows.pop()
        self.highs.append((self.index, high))
        self.lows.append((self.index, low))
        self.index += 1
        if self.index < self.stoch_period:
            return None, None
        width = self.highs[0][1] - self.lows[0][1]
        raw = (close - self.lows[0][1]) / width * 100.0 if width else 50.0
        k = self.k_mean.update(raw)
        d = self.d_mean.update(k) if k is not None else None
        return k, d

    def evaluate(self, candle: CandleInput, observed_at: datetime) -> tuple[SignalType, str]:
        self.count += 1
        close, open_price = float(candle.close), float(candle.open)
        bands = self._update_bands(close)
        rsi_value = self._update_rsi(close)
        k, d = self._update_stochastic(candle)
        rejection = self.guards.rejection_reason(observed_at)
        if rejection:
            result = SignalType.NO_TRADE, rejection
        elif self.count < self.required:
            result = SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        elif all(
            value is not None
            for value in (
                bands,
                self.previous_bands,
                rsi_value,
                k,
                d,
                self.previous_k,
                self.previous_d,
            )
        ):
            assert bands and self.previous_bands
            result = _decision(
                previous_close=self.previous_close,
                current_close=close,
                previous_open=self.previous_open,
                current_open=open_price,
                previous_lower=self.previous_bands[0],
                previous_upper=self.previous_bands[1],
                current_lower=bands[0],
                current_upper=bands[1],
                rsi_value=rsi_value,
                previous_k=self.previous_k,
                current_k=k,
                previous_d=self.previous_d,
                current_d=d,
                parameters=self.parameters,
            )
        else:
            result = SignalType.NO_TRADE, "PINE_BB_RSI_STOCH_CONDITIONS_NOT_MET"
        self.previous_close = close
        self.previous_open = open_price
        self.previous_bands = bands
        if k is not None:
            self.previous_k = k
        if d is not None:
            self.previous_d = d
        return result
