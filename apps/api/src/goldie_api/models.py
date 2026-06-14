import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default="ADMIN")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Bot(Base, TimestampMixin):
    __tablename__ = "bots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(20), default="SHADOW")
    state: Mapped[str] = mapped_column(String(20), default="STOPPED")
    active_config_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    market_feed_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market_feeds.id"), index=True, nullable=True
    )

    configs: Mapped[list["ConfigVersion"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="bot")


class ConfigVersion(Base, TimestampMixin):
    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("bot_id", "version", name="uq_bot_config_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    config: Mapped[dict] = mapped_column(JSON)
    validation_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bot: Mapped[Bot] = relationship(back_populates="configs")


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id"), index=True)
    config_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_versions.id"))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bot: Mapped[Bot] = relationship(back_populates="runs")


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_feed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_feeds.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    adapter: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="REGISTERED")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class MarketFeed(Base, TimestampMixin):
    __tablename__ = "market_feeds"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "environment",
            "provider_symbol",
            name="uq_market_feed_provider_symbol",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    environment: Mapped[str] = mapped_column(String(32))
    canonical_symbol: Mapped[str] = mapped_column(String(32), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="REGISTERED")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class CollectorConfiguration(Base, TimestampMixin):
    __tablename__ = "collector_configurations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, default=1)
    quote_interval_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    candle_poll_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    heartbeat_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    backfill_days: Mapped[int] = mapped_column(Integer)
    backfill_batch_size: Mapped[int] = mapped_column(Integer)
    configuration_retry_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class CollectorInstrumentConfiguration(Base, TimestampMixin):
    __tablename__ = "collector_instrument_configurations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_symbol: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)


class CollectorInstance(Base, TimestampMixin):
    __tablename__ = "collector_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="REGISTERED")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class CollectorCommand(Base, TimestampMixin):
    __tablename__ = "collector_commands"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    collector_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collector_instances.id"), index=True, nullable=True
    )
    market_feed_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market_feeds.id"), index=True, nullable=True
    )
    command: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperAccount(Base, TimestampMixin):
    __tablename__ = "paper_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bots.id"), unique=True, index=True
    )
    currency: Mapped[str] = mapped_column(String(12), default="USD")
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    available_cash: Mapped[Decimal] = mapped_column(Numeric(20, 8))


class InstrumentSpecification(Base, TimestampMixin):
    __tablename__ = "instrument_specifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_feed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_feeds.id"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    canonical_symbol: Mapped[str] = mapped_column(String(32))
    provider_symbol: Mapped[str] = mapped_column(String(64))
    display_precision: Mapped[int] = mapped_column(Integer)
    pip_location: Mapped[int] = mapped_column(Integer)
    point: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    minimum_trade_size: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    trade_units_precision: Mapped[int | None] = mapped_column(Integer)
    margin_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    source: Mapped[str] = mapped_column(String(32))
    provider_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class MarketTick(Base):
    __tablename__ = "market_ticks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_feed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_feeds.id"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="oanda")
    bid: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    ask: Mapped[Decimal] = mapped_column(Numeric(20, 8))


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "market_feed_id",
            "symbol",
            "timeframe",
            "opened_at",
            name="uq_feed_candle",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_feed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_feeds.id"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="oanda")
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    tick_volume: Mapped[int] = mapped_column(Integer, default=0)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    config_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_versions.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    signal: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(64))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    momentum_points: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    spread_points: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped["SignalOutcome | None"] = relationship(
        back_populates="signal", uselist=False
    )


class SignalOutcome(Base, TimestampMixin):
    __tablename__ = "signal_outcomes"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_signal_outcome_signal"),
        Index(
            "uq_signal_outcomes_one_open_per_bot",
            "bot_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.id"), index=True)
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    config_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("config_versions.id"), index=True
    )
    direction: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    risk_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    pnl_points: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    r_multiple: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    mfe_points: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    mae_points: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signal: Mapped[Signal] = relationship(back_populates="outcome")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
