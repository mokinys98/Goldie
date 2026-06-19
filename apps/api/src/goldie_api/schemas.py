import uuid
from datetime import datetime
from decimal import Decimal

from goldie_domain.config import BotConfiguration
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    market_feed_id: uuid.UUID | None = None
    initial_config: BotConfiguration | None = None


class BotRead(OrmModel):
    id: uuid.UUID
    name: str
    description: str
    mode: str
    state: str
    active_config_version_id: uuid.UUID | None
    market_feed_id: uuid.UUID | None
    strategy_profile_id: uuid.UUID | None
    config_overrides: dict
    archived_at: datetime | None
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
    strategy_profile_id: uuid.UUID | None
    config_overrides: dict


class StrategyProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    initial_config: BotConfiguration


class StrategyProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    config: BotConfiguration | None = None


class StrategyProfileRead(OrmModel):
    id: uuid.UUID
    name: str
    description: str
    status: str
    config: dict
    created_at: datetime
    updated_at: datetime
    bot_count: int = 0


class BotApplyStrategy(BaseModel):
    strategy_profile_id: uuid.UUID


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    mode: str | None = Field(default=None, pattern="^(SHADOW|PAPER)$")


class BotOverridesUpdate(BaseModel):
    overrides: dict = Field(default_factory=dict)


class BulkBotCreate(BaseModel):
    request_id: uuid.UUID
    strategy_profile_id: uuid.UUID
    market_feed_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    mode: str = Field(default="SHADOW", pattern="^(SHADOW|PAPER)$")
    name_template: str = Field(
        default="{symbol}-{strategy}-{mode}", min_length=2, max_length=120
    )
    description: str = Field(default="", max_length=1000)


class BulkBotResult(BaseModel):
    market_feed_id: uuid.UUID
    name: str
    status: str
    bot: BotRead | None = None
    error: str | None = None


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
    outcome: "SignalOutcomeRead | None" = None


class SignalOutcomeRead(OrmModel):
    id: uuid.UUID
    signal_id: uuid.UUID
    bot_id: uuid.UUID
    run_id: uuid.UUID
    config_version_id: uuid.UUID
    direction: str
    status: str
    result: str | None
    close_reason: str | None
    skip_reason: str | None
    opened_at: datetime | None
    closed_at: datetime | None
    entry_price: Decimal | None
    exit_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    volume: Decimal | None
    risk_amount: Decimal | None
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    pnl_points: Decimal | None
    r_multiple: Decimal | None
    mfe_points: Decimal
    mae_points: Decimal
    duration_seconds: int | None


class BotStatus(BaseModel):
    bot: BotRead
    agent: AgentRead | None
    agent_effective_status: str
    paper_account: dict | None
    symbol_specification: dict | None
    latest_tick: dict | None
    recent_candles: list[dict]
    latest_signal: SignalRead | None
    active_shadow_trade: SignalOutcomeRead | None
    active_run_id: uuid.UUID | None
    data_state: str


class MarketFeedRegister(BaseModel):
    provider: str = Field(pattern="^oanda$")
    environment: str = Field(default="practice", pattern="^(practice|live)$")
    canonical_symbol: str = Field(default="EURUSD", pattern="^[A-Z0-9]{3,32}$")
    provider_symbol: str = Field(
        default="EUR_USD",
        pattern="^[A-Z0-9]+_[A-Z0-9]+$",
    )
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
    canonical_symbol: str = Field(pattern="^[A-Z0-9]{3,32}$")
    provider_symbol: str = Field(pattern="^[A-Z0-9]+_[A-Z0-9]+$")
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
    event_id: uuid.UUID | None = None
    collector_id: uuid.UUID | None = None
    sent_at: datetime | None = None
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
    event_id: uuid.UUID | None = None
    collector_id: uuid.UUID | None = None
    sent_at: datetime | None = None
    agent_id: uuid.UUID
    candles: list[FeedCandle] = Field(min_length=1, max_length=5000)


class MarketFeedAssignment(BaseModel):
    market_feed_id: uuid.UUID


class CollectorSettingsValues(BaseModel):
    quote_interval_seconds: Decimal = Field(default=5, ge=1, le=60)
    candle_poll_seconds: Decimal = Field(default=15, ge=5, le=300)
    heartbeat_seconds: Decimal = Field(default=10, ge=5, le=300)
    backfill_days: int = Field(default=30, ge=1, le=365)
    backfill_batch_size: int = Field(default=250, ge=50, le=1000)
    configuration_retry_seconds: Decimal = Field(default=900, ge=60, le=86400)


class CollectorSettingsRead(CollectorSettingsValues):
    id: uuid.UUID
    version: int
    updated_at: datetime


class CollectorSettingsUpdate(CollectorSettingsValues):
    expected_version: int = Field(ge=1)


class CollectorInstrumentSettingsUpdate(BaseModel):
    enabled: bool
    overrides: dict = Field(default_factory=dict)


class CollectorInstrumentCreate(BaseModel):
    provider_symbol: str = Field(pattern="^[A-Z0-9]+_[A-Z0-9]+$")


class CollectorInstanceRegister(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    defaults: CollectorSettingsValues
    instruments: list[str] = Field(min_length=1, max_length=20)


class CollectorInstanceHeartbeat(BaseModel):
    status: str = Field(pattern="^(ONLINE|PAUSED|DEGRADED|ERROR)$")
    applied_config_version: int | None = None
    details: dict = Field(default_factory=dict)
    observed_at: datetime


class CollectorCommandCreate(BaseModel):
    command: str = Field(pattern="^(PAUSE|RESUME|RECONNECT|BACKFILL)$")
    market_feed_id: uuid.UUID | None = None
    payload: dict = Field(default_factory=dict)


class CollectorCommandUpdate(BaseModel):
    status: str = Field(pattern="^(RUNNING|SUCCEEDED|FAILED)$")
    progress: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=4000)


class ExecutionModelFields(BaseModel):
    fill_mode: str = Field(default="simulated", pattern="^(perfect|simulated)$")
    fee_maker: Decimal = Field(default=Decimal("0.001"), ge=0)
    fee_taker: Decimal = Field(default=Decimal("0.001"), ge=0)
    taker_slippage: Decimal = Field(default=Decimal("0"), ge=0)
    slippage_small: Decimal = Field(default=Decimal("0.0005"), ge=0)
    medium_impact: Decimal = Field(default=Decimal("0.001"), ge=0)
    slippage_medium: Decimal | None = Field(default=None, ge=0)
    impact_model: str = Field(default="sqrt", pattern="^(sqrt)$")
    model_sqrt_limit: Decimal = Field(default=Decimal("1.0"), ge=0)
    limit_fill_timeout_s: int = Field(default=30, ge=0)
    min_qty_threshold: Decimal = Field(default=Decimal("0"), ge=0)
    min_qty_check: bool = True

    @model_validator(mode="before")
    @classmethod
    def support_legacy_slippage_medium(cls, data):
        if isinstance(data, dict):
            values = dict(data)
            if "medium_impact" not in values and "slippage_medium" in values:
                values["medium_impact"] = values["slippage_medium"]
            if "slippage_medium" not in values and "medium_impact" in values:
                values["slippage_medium"] = values["medium_impact"]
            return values
        return data

    @model_validator(mode="after")
    def mirror_legacy_slippage_medium(self):
        if self.slippage_medium is None:
            self.slippage_medium = self.medium_impact
        return self


class BacktestCreate(ExecutionModelFields):
    bot_id: uuid.UUID
    config_version_id: uuid.UUID
    market_feed_id: uuid.UUID
    date_from: datetime
    date_to: datetime
    initial_capital: Decimal = Field(default=Decimal("10000"), gt=0)


class BatchBacktestCreate(ExecutionModelFields):
    bot_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    date_from: datetime
    date_to: datetime
    initial_capital: Decimal = Field(default=Decimal("10000"), gt=0)


class BatchBacktestResult(BaseModel):
    bot_id: uuid.UUID
    status: str
    experiment: "BacktestRead | None" = None
    error: str | None = None


class BacktestRead(OrmModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    config_version_id: uuid.UUID
    market_feed_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    date_from: datetime
    date_to: datetime
    initial_capital: Decimal
    fill_mode: str
    fee_maker: Decimal
    fee_taker: Decimal
    taker_slippage: Decimal
    slippage_small: Decimal
    slippage_medium: Decimal
    medium_impact: Decimal
    impact_model: str
    model_sqrt_limit: Decimal
    limit_fill_timeout_s: int
    min_qty_threshold: Decimal
    min_qty_check: bool
    config_snapshot: dict
    progress: dict
    summary: dict
    reason_counts: dict
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BacktestTradeRead(OrmModel):
    id: uuid.UUID
    experiment_id: uuid.UUID
    direction: str
    signal_at: datetime
    opened_at: datetime
    closed_at: datetime
    entry_price: Decimal
    exit_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    volume: Decimal
    risk_amount: Decimal
    close_reason: str
    gross_pnl: Decimal
    commission: Decimal
    net_pnl: Decimal
    pnl_points: Decimal
    r_multiple: Decimal
    mfe_points: Decimal
    mae_points: Decimal
    duration_seconds: int


class BacktestTradePage(BaseModel):
    items: list[BacktestTradeRead]
    total: int


class OptimizationCreate(ExecutionModelFields):
    bot_id: uuid.UUID
    config_version_id: uuid.UUID
    market_feed_id: uuid.UUID
    date_from: datetime
    date_to: datetime
    n_trials: int = Field(ge=1, le=500, default=25)
    objective: str = Field(default="BALANCED", pattern="^(BALANCED)$")
    initial_capital: Decimal = Field(default=Decimal("10000"), gt=0)


class OptimizationTrialRead(OrmModel):
    id: uuid.UUID
    optimization_run_id: uuid.UUID
    trial_number: int
    phase: str = "STRATEGY_SEARCH"
    config_overrides: dict = Field(default_factory=dict)
    status: str
    sampled_parameters: dict
    score: Decimal | None
    metrics: dict
    summary: dict
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OptimizationTrialPage(BaseModel):
    items: list[OptimizationTrialRead]
    total: int


class OptimizationRunRead(OrmModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    config_version_id: uuid.UUID
    market_feed_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    date_from: datetime
    date_to: datetime
    n_trials: int
    objective: str
    initial_capital: Decimal
    fill_mode: str
    fee_maker: Decimal
    fee_taker: Decimal
    taker_slippage: Decimal
    slippage_small: Decimal
    slippage_medium: Decimal
    medium_impact: Decimal
    impact_model: str
    model_sqrt_limit: Decimal
    limit_fill_timeout_s: int
    min_qty_threshold: Decimal
    min_qty_check: bool
    config_snapshot: dict
    progress: dict
    best_candidate: dict
    summary: dict
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
