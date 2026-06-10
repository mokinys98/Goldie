import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from goldie_domain.config import BotConfiguration
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    AccountSnapshot,
    Agent,
    Bot,
    Candle,
    ConfigVersion,
    MarketTick,
    Run,
    Signal,
    SymbolSpecification,
    User,
)
from ..schemas import BotRead, BotStatus, SignalRead
from ..security import get_current_user
from ..settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["status"])


def row_dict(row, fields: list[str]) -> dict | None:
    if row is None:
        return None
    return jsonable_encoder({field: getattr(row, field) for field in fields})


@router.get("/bots/{bot_id}/status", response_model=BotStatus)
def get_bot_status(
    bot_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BotStatus:
    bot = db.get(Bot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    agent = db.scalar(select(Agent).where(Agent.bot_id == bot_id).order_by(desc(Agent.created_at)))
    account = db.scalar(
        select(AccountSnapshot)
        .where(AccountSnapshot.bot_id == bot_id)
        .order_by(desc(AccountSnapshot.observed_at))
    )
    spec = db.scalar(
        select(SymbolSpecification)
        .where(SymbolSpecification.bot_id == bot_id)
        .order_by(desc(SymbolSpecification.updated_at))
    )
    tick = db.scalar(
        select(MarketTick).where(MarketTick.bot_id == bot_id).order_by(desc(MarketTick.observed_at))
    )
    candles = list(
        db.scalars(
            select(Candle)
            .where(Candle.bot_id == bot_id)
            .order_by(desc(Candle.opened_at))
            .limit(100)
        )
    )
    signal = db.scalar(
        select(Signal).where(Signal.bot_id == bot_id).order_by(desc(Signal.observed_at))
    )
    run = db.scalar(
        select(Run)
        .where(Run.bot_id == bot_id, Run.status == "ACTIVE")
        .order_by(desc(Run.created_at))
    )

    now = datetime.now(UTC)
    effective = "OFFLINE"
    if agent and agent.last_heartbeat_at:
        heartbeat = agent.last_heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        if (now - heartbeat).total_seconds() <= get_settings().agent_offline_after_seconds:
            effective = agent.status

    data_state = "MISSING"
    if tick:
        observed = tick.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        stale_limit = 15
        if bot.active_config_version_id:
            config_row = db.get(ConfigVersion, bot.active_config_version_id)
            if config_row:
                stale_limit = BotConfiguration.model_validate(
                    config_row.config
                ).filters.stale_after_seconds
        if (now - observed).total_seconds() <= stale_limit:
            data_state = "FRESH"
        else:
            data_state = "STALE"

    return BotStatus(
        bot=BotRead.model_validate(bot),
        agent=agent,
        agent_effective_status=effective,
        latest_account=row_dict(
            account,
            [
                "observed_at",
                "broker",
                "server",
                "login",
                "currency",
                "balance",
                "equity",
                "margin_free",
                "leverage",
                "is_demo",
            ],
        ),
        symbol_specification=row_dict(
            spec,
            [
                "symbol",
                "digits",
                "point",
                "tick_size",
                "tick_value",
                "contract_size",
                "volume_min",
                "volume_max",
                "volume_step",
            ],
        ),
        latest_tick=row_dict(tick, ["symbol", "observed_at", "bid", "ask"]),
        recent_candles=[
            row_dict(
                candle,
                [
                    "symbol",
                    "timeframe",
                    "opened_at",
                    "open",
                    "high",
                    "low",
                    "close",
                    "tick_volume",
                    "is_complete",
                ],
            )
            for candle in reversed(candles)
        ],
        latest_signal=SignalRead.model_validate(signal) if signal else None,
        active_run_id=run.id if run else None,
        data_state=data_state,
    )
