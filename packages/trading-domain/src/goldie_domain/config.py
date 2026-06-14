from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(default="EURUSD", min_length=1, max_length=32)
    timeframe: str = Field(default="M1", pattern="^M1$")


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "basic_momentum"
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {
            "lookback_candles": 5,
            "min_momentum_points": "50",
        }
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_parameters(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        parameters = dict(data.get("parameters") or {})
        for key in ("lookback_candles", "min_momentum_points"):
            if key in data:
                parameters[key] = data.pop(key)
        data["parameters"] = parameters
        return data

    @model_validator(mode="after")
    def validate_parameters(self) -> "StrategyConfig":
        from .registry import validate_strategy_parameters

        validated = validate_strategy_parameters(self.name, self.parameters)
        self.parameters = validated.model_dump(mode="json")
        return self


class FilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_spread_points: Decimal = Field(default=Decimal("30"), gt=0, le=10000)
    stale_after_seconds: int = Field(default=15, ge=2, le=300)


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = "Europe/Vilnius"
    start_time: time = time(10, 0)
    end_time: time = time(18, 0)

    @model_validator(mode="after")
    def validate_session(self) -> "SessionConfig":
        ZoneInfo(self.timezone)
        if self.start_time == self.end_time:
            raise ValueError("Session start and end must differ")
        return self


class TheoreticalTradeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_loss_points: Decimal = Field(default=Decimal("70"), gt=0, le=100000)
    take_profit_points: Decimal = Field(default=Decimal("100"), gt=0, le=100000)
    risk_per_trade_pct: Decimal = Field(default=Decimal("0.25"), gt=0, le=100)
    max_trade_duration_minutes: int = Field(default=5, ge=1, le=1440)
    max_open_shadow_positions: int = Field(default=1, ge=1, le=1)


class BotConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: MarketConfig = Field(default_factory=MarketConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    theoretical_trade: TheoreticalTradeConfig = Field(default_factory=TheoreticalTradeConfig)


DEFAULT_BOT_CONFIGURATION = BotConfiguration().model_dump(mode="json")
