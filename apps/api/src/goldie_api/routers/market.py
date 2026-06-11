from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    AccountSnapshot,
    Agent,
    Bot,
    Candle,
    MarketTick,
    SymbolSpecification,
)
from ..schemas import (
    AccountSnapshotIn,
    CandleIn,
    MarketTickIn,
    SymbolSpecificationIn,
)
from ..services import evaluate_latest_signal
from ..shadow import create_signal_outcome, evaluate_open_outcome
from ..websocket import manager
from .agents import require_agent_token

router = APIRouter(prefix="/api/v1/market", tags=["market"])


def validate_agent(db: Session, agent_id, bot_id) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.bot_id != bot_id:
        raise HTTPException(status_code=403, detail="Agent and bot do not match")
    return agent


@router.post("/account-snapshots", status_code=202)
async def ingest_account(
    payload: AccountSnapshotIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    validate_agent(db, payload.agent_id, payload.bot_id)
    row = AccountSnapshot(**payload.model_dump())
    db.add(row)
    db.commit()
    await manager.broadcast(
        {
            "event_type": "account.snapshot",
            "occurred_at": datetime.now(UTC).isoformat(),
            "bot_instance_id": str(payload.bot_id),
        }
    )
    return {"accepted": True}


@router.post("/symbol-specifications", status_code=202)
async def ingest_symbol(
    payload: SymbolSpecificationIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    validate_agent(db, payload.agent_id, payload.bot_id)
    row = SymbolSpecification(**payload.model_dump())
    db.add(row)
    db.commit()
    await manager.broadcast(
        {
            "event_type": "symbol.specification",
            "occurred_at": datetime.now(UTC).isoformat(),
            "bot_instance_id": str(payload.bot_id),
            "symbol": payload.symbol,
        }
    )
    return {"accepted": True}


@router.post("/ticks", status_code=202)
async def ingest_tick(
    payload: MarketTickIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    validate_agent(db, payload.agent_id, payload.bot_id)
    if payload.ask < payload.bid:
        raise HTTPException(status_code=422, detail="Ask cannot be lower than bid")
    row = MarketTick(**payload.model_dump())
    db.add(row)
    db.flush()
    outcome = evaluate_open_outcome(db, row)
    db.commit()
    await manager.broadcast(
        {
            "event_type": "market.tick",
            "occurred_at": datetime.now(UTC).isoformat(),
            "bot_instance_id": str(payload.bot_id),
            "data": jsonable_encoder(payload),
            "shadow_outcome_id": str(outcome.id) if outcome else None,
        }
    )
    return {"accepted": True}


@router.post("/candles", status_code=202)
async def ingest_candle(
    payload: CandleIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_agent_token),
) -> dict:
    validate_agent(db, payload.agent_id, payload.bot_id)
    if payload.high < max(payload.open, payload.close) or payload.low > min(
        payload.open, payload.close
    ):
        raise HTTPException(status_code=422, detail="Invalid candle OHLC values")
    existing = db.scalar(
        select(Candle).where(
            Candle.bot_id == payload.bot_id,
            Candle.symbol == payload.symbol,
            Candle.timeframe == payload.timeframe,
            Candle.opened_at == payload.opened_at,
        )
    )
    if existing is not None:
        return {"accepted": True, "duplicate": True}
    row = Candle(**payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"accepted": True, "duplicate": True}

    signal = None
    if payload.is_complete:
        bot = db.get(Bot, payload.bot_id)
        if bot:
            signal, created = evaluate_latest_signal(db, bot)
            if created and signal:
                tick = db.scalar(
                    select(MarketTick)
                    .where(MarketTick.bot_id == payload.bot_id)
                    .order_by(MarketTick.observed_at.desc())
                )
                if tick:
                    create_signal_outcome(db, signal, tick)
            db.commit()
    await manager.broadcast(
        {
            "event_type": "market.candle",
            "occurred_at": datetime.now(UTC).isoformat(),
            "bot_instance_id": str(payload.bot_id),
            "signal": jsonable_encoder(signal) if signal else None,
        }
    )
    return {
        "accepted": True,
        "signal_id": str(signal.id) if signal else None,
    }
