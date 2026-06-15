import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    BacktestExperiment,
    BacktestTrade,
    Bot,
    ConfigVersion,
    MarketFeed,
    Run,
    User,
)
from ..schemas import (
    BacktestCreate,
    BacktestRead,
    BacktestTradePage,
    BacktestTradeRead,
    BatchBacktestCreate,
    BatchBacktestResult,
)
from ..security import get_current_user
from ..settings import get_settings

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])


def get_experiment(db: Session, experiment_id: uuid.UUID) -> BacktestExperiment:
    experiment = db.get(BacktestExperiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return experiment


@router.post("", response_model=BacktestRead, status_code=status.HTTP_201_CREATED)
def create_backtest(
    payload: BacktestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BacktestExperiment:
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
        raise HTTPException(status_code=422, detail="Backtest period cannot exceed 365 days")
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
        mode="BACKTEST",
        status="QUEUED",
    )
    db.add(run)
    db.flush()
    experiment = BacktestExperiment(
        bot_id=bot.id,
        config_version_id=config.id,
        market_feed_id=feed.id,
        run_id=run.id,
        requested_by=user.id,
        status="PENDING",
        date_from=date_from,
        date_to=date_to,
        initial_capital=payload.initial_capital,
        spread_points=payload.spread_points,
        slippage_points=payload.slippage_points,
        commission_per_trade=payload.commission_per_trade,
        config_snapshot=config.config,
        progress={"processed": 0, "total": 0},
        summary={},
        reason_counts={},
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    try:
        Redis.from_url(get_settings().redis_url).publish("goldie:backtests", str(experiment.id))
    except Exception:
        pass
    return experiment


@router.post("/batch", response_model=list[BatchBacktestResult])
def create_backtests_batch(
    payload: BatchBacktestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BatchBacktestResult]:
    results: list[BatchBacktestResult] = []
    for bot_id in dict.fromkeys(payload.bot_ids):
        bot = db.get(Bot, bot_id)
        if bot is None or bot.archived_at is not None:
            results.append(
                BatchBacktestResult(
                    bot_id=bot_id,
                    status="FAILED",
                    error="Active bot not found",
                )
            )
            continue
        if bot.active_config_version_id is None:
            results.append(
                BatchBacktestResult(
                    bot_id=bot.id,
                    status="FAILED",
                    error="Bot has no active configuration",
                )
            )
            continue
        if bot.market_feed_id is None:
            results.append(
                BatchBacktestResult(
                    bot_id=bot.id,
                    status="FAILED",
                    error="Bot has no market feed",
                )
            )
            continue
        try:
            experiment = create_backtest(
                BacktestCreate(
                    bot_id=bot.id,
                    config_version_id=bot.active_config_version_id,
                    market_feed_id=bot.market_feed_id,
                    date_from=payload.date_from,
                    date_to=payload.date_to,
                    initial_capital=payload.initial_capital,
                    spread_points=payload.spread_points,
                    slippage_points=payload.slippage_points,
                    commission_per_trade=payload.commission_per_trade,
                ),
                db,
                user,
            )
            results.append(
                BatchBacktestResult(
                    bot_id=bot.id,
                    status="CREATED",
                    experiment=BacktestRead.model_validate(experiment),
                )
            )
        except HTTPException as exc:
            db.rollback()
            results.append(
                BatchBacktestResult(
                    bot_id=bot.id,
                    status="FAILED",
                    error=str(exc.detail),
                )
            )
    return results


@router.get("", response_model=list[BacktestRead])
def list_backtests(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[BacktestExperiment]:
    return list(
        db.scalars(
            select(BacktestExperiment)
            .order_by(BacktestExperiment.created_at.desc())
            .limit(limit)
        )
    )


@router.get("/{experiment_id}", response_model=BacktestRead)
def read_backtest(
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BacktestExperiment:
    return get_experiment(db, experiment_id)


@router.get("/{experiment_id}/trades", response_model=BacktestTradePage)
def list_backtest_trades(
    experiment_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    get_experiment(db, experiment_id)
    total = db.scalar(
        select(func.count(BacktestTrade.id)).where(
            BacktestTrade.experiment_id == experiment_id
        )
    )
    items = list(
        db.scalars(
            select(BacktestTrade)
            .where(BacktestTrade.experiment_id == experiment_id)
            .order_by(BacktestTrade.opened_at)
            .offset(offset)
            .limit(limit)
        )
    )
    return {"items": items, "total": total or 0}


@router.post("/{experiment_id}/cancel", response_model=BacktestRead)
def cancel_backtest(
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BacktestExperiment:
    experiment = get_experiment(db, experiment_id)
    if experiment.status == "PENDING":
        experiment.status = "CANCELLED"
        experiment.completed_at = datetime.now(UTC)
        run = db.get(Run, experiment.run_id)
        if run:
            run.status = "CANCELLED"
            run.ended_at = experiment.completed_at
    elif experiment.status == "RUNNING":
        experiment.status = "CANCEL_REQUESTED"
    elif experiment.status not in {"CANCELLED", "SUCCEEDED", "FAILED"}:
        raise HTTPException(status_code=409, detail="Backtest cannot be cancelled")
    db.commit()
    db.refresh(experiment)
    return experiment


@router.get("/{experiment_id}/export")
def export_backtest(
    experiment_id: uuid.UUID,
    format: str = Query(pattern="^(csv|json)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    experiment = get_experiment(db, experiment_id)
    trades = list(
        db.scalars(
            select(BacktestTrade)
            .where(BacktestTrade.experiment_id == experiment_id)
            .order_by(BacktestTrade.opened_at)
        )
    )
    rows = [
        jsonable_encoder(BacktestTradeRead.model_validate(item).model_dump())
        for item in trades
    ]
    if format == "json":
        payload = {
            "experiment": jsonable_encoder(BacktestRead.model_validate(experiment)),
            "trades": rows,
        }
        return Response(
            json.dumps(payload),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="backtest-{experiment_id}.json"'
            },
        )
    output = io.StringIO()
    fieldnames = list(rows[0]) if rows else [
        "direction",
        "signal_at",
        "opened_at",
        "closed_at",
        "entry_price",
        "exit_price",
        "close_reason",
        "gross_pnl",
        "commission",
        "net_pnl",
        "r_multiple",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="backtest-{experiment_id}.csv"'
        },
    )
