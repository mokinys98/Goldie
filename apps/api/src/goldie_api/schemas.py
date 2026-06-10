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


class AgentRegister(BaseModel):
    bot_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    adapter: str = Field(pattern="^(fake|mt5)$")
    details: dict = Field(default_factory=dict)


class AgentRead(OrmModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    name: str
    adapter: str
    status: str
    last_heartbeat_at: datetime | None
    details: dict


class HeartbeatRequest(BaseModel):
    status: str = Field(pattern="^(ONLINE|DEGRADED|ERROR)$")
    details: dict = Field(default_factory=dict)
    observed_at: datetime


class AccountSnapshotIn(BaseModel):
    agent_id: uuid.UUID
    bot_id: uuid.UUID
    observed_at: datetime
    broker: str
    server: str
    login: str
    currency: str
    balance: Decimal
    equity: Decimal
    margin_free: Decimal
    leverage: int
    is_demo: bool


class SymbolSpecificationIn(BaseModel):
    agent_id: uuid.UUID
    bot_id: uuid.UUID
    symbol: str
    digits: int
    point: Decimal
    tick_size: Decimal
    tick_value: Decimal
    contract_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal


class MarketTickIn(BaseModel):
    agent_id: uuid.UUID
    bot_id: uuid.UUID
    symbol: str
    observed_at: datetime
    bid: Decimal
    ask: Decimal


class CandleIn(BaseModel):
    agent_id: uuid.UUID
    bot_id: uuid.UUID
    symbol: str
    timeframe: str = Field(pattern="^M1$")
    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int = 0
    is_complete: bool


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
    latest_account: dict | None
    symbol_specification: dict | None
    latest_tick: dict | None
    recent_candles: list[dict]
    latest_signal: SignalRead | None
    active_run_id: uuid.UUID | None
    data_state: str
