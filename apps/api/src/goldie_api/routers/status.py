import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from goldie_domain.config import BotConfiguration
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Agent,
    Bot,
    Candle,
    ConfigVersion,
    InstrumentSpecification,
    MarketFeed,
    MarketTick,
    PaperAccount,
    Run,
    Signal,
    SignalOutcome,
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
    feed = db.get(MarketFeed, bot.market_feed_id) if bot.market_feed_id else None
    agent = (
        db.scalar(
            select(Agent)
            .where(Agent.market_feed_id == bot.market_feed_id)
            .order_by(desc(Agent.created_at))
        )
        if bot.market_feed_id
        else None
    )
    paper_account = db.scalar(select(PaperAccount).where(PaperAccount.bot_id == bot_id))
    if bot.market_feed_id:
        spec = db.scalar(
            select(InstrumentSpecification)
            .where(InstrumentSpecification.market_feed_id == bot.market_feed_id)
            .order_by(desc(InstrumentSpecification.updated_at))
        )
        tick = db.scalar(
            select(MarketTick)
            .where(MarketTick.market_feed_id == bot.market_feed_id)
            .order_by(desc(MarketTick.observed_at))
        )
        candles = list(
            db.scalars(
                select(Candle)
                .where(Candle.market_feed_id == bot.market_feed_id)
                .order_by(desc(Candle.opened_at))
                .limit(100)
            )
        )
    else:
        spec = None
        tick = None
        candles = []
    signal = db.scalar(
        select(Signal).where(Signal.bot_id == bot_id).order_by(desc(Signal.observed_at))
    )
    run = db.scalar(
        select(Run)
        .where(Run.bot_id == bot_id, Run.status == "ACTIVE")
        .order_by(desc(Run.created_at))
    )
    active_shadow_trade = db.scalar(
        select(SignalOutcome).where(
            SignalOutcome.bot_id == bot_id,
            SignalOutcome.status == "OPEN",
        )
    )

    now = datetime.now(UTC)
    effective = "OFFLINE"
    heartbeat_source = feed if feed else agent
    if heartbeat_source and heartbeat_source.last_heartbeat_at:
        heartbeat = heartbeat_source.last_heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        if (now - heartbeat).total_seconds() <= get_settings().agent_offline_after_seconds:
            effective = heartbeat_source.status

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
    if effective == "MARKET_CLOSED":
        data_state = "MARKET_CLOSED"

    return BotStatus(
        bot=BotRead.model_validate(bot),
        agent=agent,
        agent_effective_status=effective,
        paper_account=row_dict(
            paper_account,
            [
                "currency",
                "initial_balance",
                "balance",
                "equity",
                "available_cash",
                "updated_at",
            ],
        ),
        symbol_specification=row_dict(
            spec,
            [
                "canonical_symbol",
                "provider_symbol",
                "display_precision",
                "pip_location",
                "point",
                "minimum_trade_size",
                "trade_units_precision",
                "margin_rate",
                "source",
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
        active_shadow_trade=active_shadow_trade,
        active_run_id=run.id if run else None,
        data_state=data_state,
    )
