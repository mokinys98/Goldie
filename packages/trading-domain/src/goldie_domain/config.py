from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(default="XAUUSD", min_length=1, max_length=32)
    timeframe: str = Field(default="M1", pattern="^M1$")


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="basic_momentum", pattern="^basic_momentum$")
    lookback_candles: int = Field(default=5, ge=2, le=100)
    min_momentum_points: Decimal = Field(default=Decimal("50"), gt=0, le=10000)


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


class BotConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: MarketConfig = Field(default_factory=MarketConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    theoretical_trade: TheoreticalTradeConfig = Field(default_factory=TheoreticalTradeConfig)


DEFAULT_BOT_CONFIGURATION = BotConfiguration().model_dump(mode="json")
