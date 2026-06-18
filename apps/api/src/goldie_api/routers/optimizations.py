import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Bot,
    ConfigVersion,
    MarketFeed,
    OptimizationRun,
    OptimizationTrial,
    Run,
    User,
)
from ..schemas import (
    OptimizationCreate,
    OptimizationRunRead,
    OptimizationTrialPage,
    OptimizationTrialRead,
)
from ..security import get_current_user
from ..settings import get_settings

router = APIRouter(prefix="/api/v1/optimizations", tags=["optimizations"])


def get_optimization(db: Session, optimization_id: uuid.UUID) -> OptimizationRun:
    optimization = db.get(OptimizationRun, optimization_id)
    if optimization is None:
        raise HTTPException(status_code=404, detail="Optimization not found")
    return optimization


def get_optimization_trial(
    db: Session,
    optimization_id: uuid.UUID,
    trial_id: uuid.UUID,
) -> OptimizationTrial:
    trial = db.get(OptimizationTrial, trial_id)
    if trial is None or trial.optimization_run_id != optimization_id:
        raise HTTPException(status_code=404, detail="Optimization trial not found")
    return trial


@router.post("", response_model=OptimizationRunRead, status_code=status.HTTP_201_CREATED)
def create_optimization(
    payload: OptimizationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OptimizationRun:
    date_from = (
        payload.date_from.replace(tzinfo=UTC)
        if payload.date_from.tzinfo is None
        else payload.date_from
    )
    date_to = (
        payload.date_to.replace(tzinfo=UTC)
        if payload.date_to.tzinfo is None
        else payload.date_to
    )
    if date_to <= date_from:
        raise HTTPException(status_code=422, detail="date_to must be after date_from")
    if date_to - date_from > timedelta(days=365):
        raise HTTPException(
            status_code=422,
            detail="Optimization period cannot exceed 365 days",
        )
    bot = db.get(Bot, payload.bot_id)
    config = db.get(ConfigVersion, payload.config_version_id)
    feed = db.get(MarketFeed, payload.market_feed_id)
    if bot is None or config is None or feed is None:
        raise HTTPException(status_code=404, detail="Bot, config version or feed not found")
    if config.bot_id != bot.id:
        raise HTTPException(status_code=409, detail="Config version does not belong to bot")
    if bot.market_feed_id != feed.id:
        raise HTTPException(status_code=409, detail="Market feed does not belong to bot")
    if config.status not in {"ACTIVE", "SUPERSEDED", "VALIDATED"}:
        raise HTTPException(status_code=409, detail="Config version must be validated")

    run = Run(
        bot_id=bot.id,
        config_version_id=config.id,
        mode="OPTIMIZATION",
        status="QUEUED",
    )
    db.add(run)
    db.flush()
    optimization = OptimizationRun(
        bot_id=bot.id,
        config_version_id=config.id,
        market_feed_id=feed.id,
        run_id=run.id,
        requested_by=user.id,
        status="PENDING",
        date_from=date_from,
        date_to=date_to,
        n_trials=payload.n_trials,
        objective=payload.objective,
        initial_capital=payload.initial_capital,
        fill_mode=payload.fill_mode,
        fee_maker=payload.fee_maker,
        fee_taker=payload.fee_taker,
        taker_slippage=payload.taker_slippage,
        slippage_small=payload.slippage_small,
        slippage_medium=payload.medium_impact,
        medium_impact=payload.medium_impact,
        impact_model=payload.impact_model,
        model_sqrt_limit=payload.model_sqrt_limit,
        limit_fill_timeout_s=payload.limit_fill_timeout_s,
        min_qty_threshold=payload.min_qty_threshold,
        min_qty_check=payload.min_qty_check,
        config_snapshot=config.config,
        progress={"completed_trials": 0, "total_trials": payload.n_trials},
        best_candidate={},
        summary={},
    )
    db.add(optimization)
    db.commit()
    db.refresh(optimization)
    try:
        Redis.from_url(get_settings().redis_url).publish(
            "goldie:optimizations",
            str(optimization.id),
        )
    except Exception:
        pass
    return optimization


@router.get("", response_model=list[OptimizationRunRead])
def list_optimizations(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[OptimizationRun]:
    return list(
        db.scalars(
            select(OptimizationRun)
            .order_by(OptimizationRun.created_at.desc())
            .limit(limit)
        )
    )


@router.get("/{optimization_id}", response_model=OptimizationRunRead)
def read_optimization(
    optimization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> OptimizationRun:
    return get_optimization(db, optimization_id)


@router.get("/{optimization_id}/trials", response_model=OptimizationTrialPage)
def list_optimization_trials(
    optimization_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    get_optimization(db, optimization_id)
    total = db.scalar(
        select(func.count(OptimizationTrial.id)).where(
            OptimizationTrial.optimization_run_id == optimization_id
        )
    )
    items = list(
        db.scalars(
            select(OptimizationTrial)
            .where(OptimizationTrial.optimization_run_id == optimization_id)
            .order_by(
                OptimizationTrial.score.desc().nullslast(),
                OptimizationTrial.trial_number.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return {"items": items, "total": total or 0}


@router.get("/{optimization_id}/trials/{trial_id}", response_model=OptimizationTrialRead)
def read_optimization_trial(
    optimization_id: uuid.UUID,
    trial_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> OptimizationTrial:
    get_optimization(db, optimization_id)
    return get_optimization_trial(db, optimization_id, trial_id)


@router.post("/{optimization_id}/cancel", response_model=OptimizationRunRead)
def cancel_optimization(
    optimization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> OptimizationRun:
    optimization = get_optimization(db, optimization_id)
    if optimization.status == "PENDING":
        optimization.status = "CANCELLED"
        optimization.completed_at = datetime.now(UTC)
        run = db.get(Run, optimization.run_id)
        if run:
            run.status = "CANCELLED"
            run.ended_at = optimization.completed_at
    elif optimization.status == "RUNNING":
        optimization.status = "CANCEL_REQUESTED"
    elif optimization.status not in {"CANCELLED", "SUCCEEDED", "FAILED"}:
        raise HTTPException(status_code=409, detail="Optimization cannot be cancelled")
    db.commit()
    db.refresh(optimization)
    return optimization
