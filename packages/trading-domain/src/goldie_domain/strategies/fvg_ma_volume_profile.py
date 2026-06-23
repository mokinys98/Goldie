from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import sma
from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import FastGuardedEvaluator, PreparedStrategy
from .fields import decimal_parameter


class FvgMaVolumeProfileParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fvg_lookback: int = Field(
        default=5,
        ge=3,
        le=100,
        description="Candles to scan for the latest fair value gap.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values allow older gaps to trigger retrace entries.",
            "optimization_minimum": 3,
            "optimization_maximum": 8,
        },
    )
    sma_period: int = Field(
        default=50,
        ge=2,
        le=500,
        description="Trend-bias SMA period.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make the trend filter slower.",
            "optimization_minimum": 20,
            "optimization_maximum": 100,
        },
    )
    volume_profile_lookback: int = Field(
        default=50,
        ge=2,
        le=500,
        description="Candles used for the OHLCV volume profile proxy.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values make POC and HVN levels more stable.",
        },
    )
    volume_profile_bins: int = Field(
        default=24,
        ge=2,
        le=200,
        description="Number of price bins for the OHLCV volume profile proxy.",
        json_schema_extra={
            "unit": "bins",
            "impact": "Higher values make profile levels more granular.",
        },
    )
    volume_spike_period: int = Field(
        default=20,
        ge=2,
        le=500,
        description="Average tick-volume period for spike confirmation.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Higher values smooth the volume baseline.",
        },
    )
    volume_spike_multiplier: Decimal = decimal_parameter(
        "1.5",
        gt=0,
        le=20,
        description="Tick-volume multiplier required for a spike.",
        unit="x average volume",
        impact="Higher values require stronger volume expansion.",
        optimization_minimum="1.2",
        optimization_maximum="2.0",
    )
    poc_tolerance_points: Decimal = decimal_parameter(
        "20",
        ge=0,
        le=100000,
        description="Maximum distance from close to POC or HVN.",
        unit="points",
        impact="Higher values make volume-profile confirmation less strict.",
    )
    require_volume_spike: bool = Field(
        default=False,
        description="Require the latest candle to exceed the volume spike threshold.",
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
    def validate_profile_window(self) -> "FvgMaVolumeProfileParameters":
        if self.volume_profile_bins > self.volume_profile_lookback * 10:
            raise ValueError("volume_profile_bins is too high for volume_profile_lookback")
        return self


@dataclass(frozen=True)
class _FvgZone:
    direction: SignalType
    lower: Decimal
    upper: Decimal


@dataclass(frozen=True)
class _VolumeProfile:
    poc: Decimal
    hvn: tuple[Decimal, ...]
    lvn: tuple[Decimal, ...]


def _required_candles(parameters: FvgMaVolumeProfileParameters) -> int:
    return max(
        parameters.sma_period,
        parameters.volume_profile_lookback,
        parameters.volume_spike_period + 1,
        parameters.fvg_lookback + 2,
    )


def _latest_fvg(candles: list[CandleInput], lookback: int) -> _FvgZone | None:
    start = max(2, len(candles) - 1 - lookback)
    for index in range(len(candles) - 2, start - 1, -1):
        left = candles[index - 2]
        right = candles[index]
        if left.high < right.low:
            return _FvgZone(direction=SignalType.BUY, lower=left.high, upper=right.low)
        if left.low > right.high:
            return _FvgZone(direction=SignalType.SELL, lower=right.high, upper=left.low)
    return None


def _volume_profile(candles: list[CandleInput], bins: int) -> _VolumeProfile | None:
    profile_low = min(candle.low for candle in candles)
    profile_high = max(candle.high for candle in candles)
    width = profile_high - profile_low
    if width <= 0:
        return None
    bin_width = width / Decimal(bins)
    volumes = [Decimal("0") for _ in range(bins)]
    for candle in candles:
        volume = Decimal(candle.tick_volume)
        if volume <= 0:
            continue
        first = int(
            ((candle.low - profile_low) / bin_width).to_integral_value(rounding=ROUND_FLOOR)
        )
        last = int(
            ((candle.high - profile_low) / bin_width).to_integral_value(rounding=ROUND_FLOOR)
        )
        first = max(0, min(bins - 1, first))
        last = max(0, min(bins - 1, last))
        touched = last - first + 1
        share = volume / Decimal(touched)
        for index in range(first, last + 1):
            volumes[index] += share
    poc_volume = max(volumes)
    if poc_volume <= 0:
        return None
    poc_index = volumes.index(poc_volume)

    def center(index: int) -> Decimal:
        return profile_low + bin_width * (Decimal(index) + Decimal("0.5"))

    hvn_threshold = poc_volume * Decimal("0.7")
    lvn_threshold = poc_volume * Decimal("0.3")
    return _VolumeProfile(
        poc=center(poc_index),
        hvn=tuple(center(index) for index, volume in enumerate(volumes) if volume >= hvn_threshold),
        lvn=tuple(
            center(index)
            for index, volume in enumerate(volumes)
            if Decimal("0") < volume <= lvn_threshold
        ),
    )


def _volume_spike(candles: list[CandleInput], period: int, multiplier: Decimal) -> bool:
    baseline = candles[-(period + 1) : -1]
    average = sum((Decimal(candle.tick_volume) for candle in baseline), Decimal("0")) / Decimal(
        period
    )
    return average > 0 and Decimal(candles[-1].tick_volume) >= average * multiplier


def _zone_touched(candle: CandleInput, zone: _FvgZone) -> bool:
    return candle.low <= zone.upper and candle.high >= zone.lower


def _near_profile_level(
    close: Decimal, profile: _VolumeProfile | None, tolerance: Decimal
) -> bool:
    if profile is None:
        return False
    return any(abs(close - level) <= tolerance for level in (profile.poc, *profile.hvn))


def _decision(
    *,
    candles: list[CandleInput],
    parameters: FvgMaVolumeProfileParameters,
    point: Decimal,
    inputs: dict[str, Any] | None = None,
) -> tuple[SignalType, str]:
    closes = [candle.close for candle in candles]
    latest = candles[-1]
    trend_sma = sma(closes, parameters.sma_period)
    zone = _latest_fvg(candles, parameters.fvg_lookback)
    profile = _volume_profile(
        candles[-parameters.volume_profile_lookback :],
        parameters.volume_profile_bins,
    )
    spike = _volume_spike(
        candles,
        parameters.volume_spike_period,
        parameters.volume_spike_multiplier,
    )
    tolerance = parameters.poc_tolerance_points * point
    near_profile = _near_profile_level(latest.close, profile, tolerance)
    confirmed = spike if parameters.require_volume_spike else near_profile or spike
    if inputs is not None:
        inputs.update(
            sma=str(trend_sma) if trend_sma is not None else None,
            fvg_direction=zone.direction.value if zone else None,
            fvg_lower=str(zone.lower) if zone else None,
            fvg_upper=str(zone.upper) if zone else None,
            poc=str(profile.poc) if profile else None,
            hvn_count=len(profile.hvn) if profile else 0,
            lvn_count=len(profile.lvn) if profile else 0,
            volume_spike=spike,
            near_volume_profile=near_profile,
        )
    if trend_sma is None or zone is None or not _zone_touched(latest, zone) or not confirmed:
        return SignalType.NO_TRADE, "FVG_MA_VOLUME_PROFILE_CONDITIONS_NOT_MET"
    if zone.direction == SignalType.BUY and latest.close > trend_sma:
        if parameters.trade_direction == "SELL_ONLY":
            return SignalType.NO_TRADE, "FVG_MA_VOLUME_PROFILE_BUY_DISABLED"
        return SignalType.BUY, "FVG_MA_VOLUME_PROFILE_BUY"
    if zone.direction == SignalType.SELL and latest.close < trend_sma:
        if parameters.trade_direction == "BUY_ONLY":
            return SignalType.NO_TRADE, "FVG_MA_VOLUME_PROFILE_SELL_DISABLED"
        return SignalType.SELL, "FVG_MA_VOLUME_PROFILE_SELL"
    return SignalType.NO_TRADE, "FVG_MA_VOLUME_PROFILE_CONDITIONS_NOT_MET"


class FvgMaVolumeProfileStrategy(PreparedStrategy):
    name = "fvg_ma_volume_profile"
    description = "FVG retrace strategy filtered by SMA trend and an OHLCV volume-profile proxy."
    parameters_model = FvgMaVolumeProfileParameters

    def required_candles(self, parameters: BaseModel) -> int:
        return _required_candles(FvgMaVolumeProfileParameters.model_validate(parameters))

    def create_fast_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> "FastFvgMaVolumeProfileEvaluator":
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return FastFvgMaVolumeProfileEvaluator(
            parameters=parameters,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        if isinstance(guard, SignalDecision):
            return guard
        parameters = FvgMaVolumeProfileParameters.model_validate(raw)
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES", context, config, guard
            )
        signal, reason = _decision(
            candles=candles,
            parameters=parameters,
            point=context.point,
            inputs=inputs,
        )
        return self._finish(signal, reason, context, config, guard)


class FastFvgMaVolumeProfileEvaluator(FastGuardedEvaluator):
    def __init__(
        self,
        *,
        parameters: FvgMaVolumeProfileParameters,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        super().__init__(guards=guards, required=_required_candles(parameters))
        self.parameters = parameters
        self.point = point
        self.candles: deque[CandleInput] = deque(maxlen=self.required)

    def evaluate(self, candle: CandleInput, observed_at: datetime) -> tuple[SignalType, str]:
        self.count += 1
        self.candles.append(candle)
        rejection = self.rejection(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if self.count < self.required:
            return SignalType.NO_TRADE, "INSUFFICIENT_COMPLETED_CANDLES"
        return _decision(
            candles=list(self.candles),
            parameters=self.parameters,
            point=self.point,
        )
