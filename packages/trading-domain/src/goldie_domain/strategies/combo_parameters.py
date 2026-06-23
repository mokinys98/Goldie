from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .fields import decimal_parameter


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


class EmaMomentumBreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=5, ge=2, le=200)
    medium_ema_period: int = Field(default=13, ge=3, le=300)
    slow_ema_period: int = Field(default=34, ge=4, le=500)
    momentum_period: int = Field(default=5, ge=1, le=100)
    min_momentum_points: Decimal = decimal_parameter(
        "10",
        gt=0,
        le=10000,
        description="Minimum directional momentum.",
        unit="points",
        impact="Higher values filter weak breakouts.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = decimal_parameter(
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
    min_atr_points: Decimal = decimal_parameter(
        "5",
        ge=0,
        le=10000,
        description="Minimum ATR volatility.",
        unit="points",
        impact="Higher values suppress signals in quiet markets.",
    )
    max_atr_points: Decimal = decimal_parameter(
        "500",
        gt=0,
        le=100000,
        description="Maximum ATR volatility.",
        unit="points",
        impact="Lower values suppress signals in extreme volatility.",
    )
    min_trend_points: Decimal = decimal_parameter(
        "0",
        ge=0,
        le=10000,
        description="Minimum EMA separation.",
        unit="points",
        impact="Higher values require a stronger trend.",
    )
    atr_stop_multiplier: Decimal = decimal_parameter(
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
    bollinger_deviations: Decimal = decimal_parameter(
        "2",
        gt=0,
        le=10,
        description="Bollinger band width.",
        unit="standard deviations",
        impact="Lower values create more breakout signals.",
    )
    momentum_period: int = Field(default=5, ge=1, le=100)
    min_momentum_points: Decimal = decimal_parameter(
        "10",
        gt=0,
        le=10000,
        description="Minimum breakout momentum.",
        unit="points",
        impact="Higher values require a stronger breakout.",
    )
    atr_period: int = Field(default=14, ge=2, le=200)
    min_atr_points: Decimal = decimal_parameter(
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
