import uuid
from datetime import datetime
from decimal import Decimal

from goldie_domain.config import BotConfiguration
from pydantic import BaseModel, ConfigDict, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BotCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    mode: str = Field(default="SHADOW", pattern="^(SHADOW|PAPER)$")
    initial_config: BotConfiguration | None = None


class BotRead(OrmModel):
    id: uuid.UUID
    name: str
    description: str
    mode: str
    state: str
    active_config_version_id: uuid.UUID | None
    market_feed_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ConfigCreate(BaseModel):
    config: BotConfiguration


class ConfigRead(OrmModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    version: int
    status: str
    config: dict
    validation_errors: list | None
    created_at: datetime
    activated_at: datetime | None


class AgentRead(OrmModel):
    id: uuid.UUID
    market_feed_id: uuid.UUID
    name: str
    adapter: str
    status: str
    last_heartbeat_at: datetime | None
    details: dict


class HeartbeatRequest(BaseModel):
    status: str = Field(pattern="^(ONLINE|DEGRADED|ERROR|MARKET_CLOSED)$")
    details: dict = Field(default_factory=dict)
    observed_at: datetime


class SignalRead(OrmModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    run_id: uuid.UUID
    config_version_id: uuid.UUID
    observed_at: datetime
    signal: str
    reason_code: str
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    momentum_points: Decimal | None
    spread_points: Decimal | None
    inputs: dict


class BotStatus(BaseModel):
    bot: BotRead
    agent: AgentRead | None
    agent_effective_status: str
    paper_account: dict | None
    symbol_specification: dict | None
    latest_tick: dict | None
    recent_candles: list[dict]
    latest_signal: SignalRead | None
    active_run_id: uuid.UUID | None
    data_state: str


class MarketFeedRegister(BaseModel):
    provider: str = Field(pattern="^oanda$")
    environment: str = Field(default="practice", pattern="^(practice|live)$")
    canonical_symbol: str = Field(default="XAUUSD", pattern="^XAUUSD$")
    provider_symbol: str = Field(default="XAU_USD", pattern="^XAU_USD$")
    agent_name: str = Field(default="railway-oanda-collector", min_length=1, max_length=120)
    details: dict = Field(default_factory=dict)


class MarketFeedRead(OrmModel):
    id: uuid.UUID
    provider: str
    environment: str
    canonical_symbol: str
    provider_symbol: str
    status: str
    last_heartbeat_at: datetime | None
    details: dict


class MarketFeedRegistration(BaseModel):
    feed: MarketFeedRead
    agent: AgentRead
    latest_candle_at: datetime | None


class FeedHeartbeatRequest(HeartbeatRequest):
    agent_id: uuid.UUID


class InstrumentSpecificationIn(BaseModel):
    agent_id: uuid.UUID
    canonical_symbol: str = Field(pattern="^XAUUSD$")
    provider_symbol: str = Field(pattern="^XAU_USD$")
    display_precision: int = Field(ge=0, le=10)
    pip_location: int = Field(ge=-10, le=10)
    minimum_trade_size: Decimal | None = Field(default=None, gt=0)
    trade_units_precision: int | None = Field(default=None, ge=0, le=10)
    margin_rate: Decimal | None = Field(default=None, gt=0)
    provider_metadata: dict = Field(default_factory=dict)


class FeedQuote(BaseModel):
    observed_at: datetime
    bid: Decimal
    ask: Decimal


class FeedQuoteBatch(BaseModel):
    agent_id: uuid.UUID
    quotes: list[FeedQuote] = Field(min_length=1, max_length=1000)


class FeedCandle(BaseModel):
    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(default=0, ge=0)
    complete: bool = True


class FeedCandleBatch(BaseModel):
    agent_id: uuid.UUID
    candles: list[FeedCandle] = Field(min_length=1, max_length=5000)


class MarketFeedAssignment(BaseModel):
    market_feed_id: uuid.UUID
