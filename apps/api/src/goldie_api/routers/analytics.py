import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, Run, SignalOutcome, User
from ..schemas import SignalOutcomeRead
from ..security import get_current_user
from ..shadow import performance_summary

router = APIRouter(prefix="/api/v1", tags=["analytics"])


def filtered_outcomes(
    db: Session,
    *,
    bot_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    result: str | None = None,
    direction: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SignalOutcome]:
    query = select(SignalOutcome)
    if bot_id:
        query = query.where(SignalOutcome.bot_id == bot_id)
    if run_id:
        query = query.where(SignalOutcome.run_id == run_id)
    if result:
        query = query.where(SignalOutcome.result == result)
    if direction:
        query = query.where(SignalOutcome.direction == direction)
    occurred_at = func.coalesce(
        SignalOutcome.closed_at,
        SignalOutcome.opened_at,
        SignalOutcome.created_at,
    )
    if date_from:
        query = query.where(occurred_at >= date_from)
    if date_to:
        query = query.where(occurred_at < date_to)
    return list(db.scalars(query.order_by(SignalOutcome.created_at.desc())))


@router.get("/bots/{bot_id}/shadow-trades", response_model=list[SignalOutcomeRead])
def list_shadow_trades(
    bot_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    result: str | None = Query(default=None, pattern="^(WIN|LOSS|BREAKEVEN)$"),
    direction: str | None = Query(default=None, pattern="^(BUY|SELL)$"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[SignalOutcome]:
    if db.get(Bot, bot_id) is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return filtered_outcomes(
        db,
        bot_id=bot_id,
        run_id=run_id,
        result=result,
        direction=direction,
        date_from=date_from,
        date_to=date_to,
    )[: min(max(limit, 1), 500)]


@router.get("/bots/{bot_id}/performance")
def bot_performance(
    bot_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if db.get(Bot, bot_id) is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return performance_summary(filtered_outcomes(db, bot_id=bot_id, run_id=run_id))


@router.get("/runs/{run_id}/performance")
def run_performance(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return performance_summary(filtered_outcomes(db, run_id=run_id))


@router.get("/bots/performance")
def bots_performance(
    date_from: datetime,
    date_to: datetime,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if date_to <= date_from:
        raise HTTPException(status_code=422, detail="date_to must be after date_from")
    bots = list(
        db.scalars(
            select(Bot)
            .where(Bot.archived_at.is_(None))
            .order_by(Bot.name)
        )
    )
    items = []
    combined: list[SignalOutcome] = []
    for bot in bots:
        outcomes = filtered_outcomes(
            db,
            bot_id=bot.id,
            date_from=date_from,
            date_to=date_to,
        )
        combined.extend(outcomes)
        items.append(
            {
                "bot": {
                    "id": bot.id,
                    "name": bot.name,
                    "mode": bot.mode,
                    "state": bot.state,
                },
                "performance": performance_summary(outcomes),
            }
        )
    return {
        "date_from": date_from,
        "date_to": date_to,
        "total": performance_summary(combined),
        "items": items,
    }
