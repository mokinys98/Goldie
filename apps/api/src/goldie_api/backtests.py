import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.encoders import jsonable_encoder
from goldie_domain import (
    BacktestCancelled,
    BacktestCosts,
    BacktestEngine,
    BacktestInstrument,
    BotConfiguration,
    CandleInput,
    get_strategy,
)
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .models import (
    BacktestExperiment,
    BacktestTrade,
    Candle,
    InstrumentSpecification,
    Run,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def reset_interrupted_backtests(db: Session) -> int:
    result = db.execute(
        update(BacktestExperiment)
        .where(BacktestExperiment.status == "RUNNING")
        .values(
            status="PENDING",
            progress={"processed": 0, "total": 0},
            error="Worker restarted; experiment queued again.",
            started_at=None,
        )
    )
    db.commit()
    return result.rowcount


def claim_next_backtest(db: Session) -> uuid.UUID | None:
    experiment = db.scalar(
        select(BacktestExperiment)
        .where(BacktestExperiment.status == "PENDING")
        .order_by(BacktestExperiment.created_at)
        .with_for_update(skip_locked=True)
    )
    if experiment is None:
        return None
    experiment.status = "RUNNING"
    experiment.started_at = utc_now()
    experiment.completed_at = None
    experiment.error = None
    experiment.progress = {"processed": 0, "total": 0}
    run = db.get(Run, experiment.run_id)
    if run:
        run.status = "RUNNING"
    db.commit()
    return experiment.id


def execute_backtest(db: Session, experiment_id: uuid.UUID) -> None:
    experiment = db.get(BacktestExperiment, experiment_id)
    if experiment is None:
        return
    try:
        db.execute(
            delete(BacktestTrade).where(BacktestTrade.experiment_id == experiment.id)
        )
        spec = db.scalar(
            select(InstrumentSpecification)
            .where(InstrumentSpecification.market_feed_id == experiment.market_feed_id)
            .order_by(InstrumentSpecification.updated_at.desc())
        )
        if spec is None:
            raise ValueError("Instrument specification is missing")
        candle_rows = list(
            db.scalars(
                select(Candle)
                .where(
                    Candle.market_feed_id == experiment.market_feed_id,
                    Candle.timeframe == "M1",
                    Candle.is_complete.is_(True),
                    Candle.opened_at >= experiment.date_from,
                    Candle.opened_at < experiment.date_to,
                )
                .order_by(Candle.opened_at)
            )
        )
        config = BotConfiguration.model_validate(experiment.config_snapshot)
        strategy = get_strategy(config.strategy.name)
        minimum = strategy.required_candles(
            strategy.parameters_model.model_validate(config.strategy.parameters)
        ) + 1
        if len(candle_rows) < minimum:
            raise ValueError(f"At least {minimum} completed M1 candles are required")
        step = Decimal(1).scaleb(-(spec.trade_units_precision or 0))

        last_reported = -1

        def progress(processed: int, total: int) -> bool:
            nonlocal last_reported
            if processed != total and processed - last_reported < 100:
                return experiment.status != "CANCEL_REQUESTED"
            db.refresh(experiment)
            if experiment.status == "CANCEL_REQUESTED":
                return False
            experiment.progress = {"processed": processed, "total": total}
            db.commit()
            last_reported = processed
            return True

        result = BacktestEngine().run(
            candles=[
                CandleInput(
                    opened_at=row.opened_at,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    tick_volume=row.tick_volume,
                    is_complete=row.is_complete,
                )
                for row in candle_rows
            ],
            config=config,
            instrument=BacktestInstrument(
                point=spec.point,
                tick_size=spec.point,
                tick_value=spec.point,
                volume_min=spec.minimum_trade_size or step,
                volume_max=Decimal("1000000000"),
                volume_step=step,
            ),
            costs=BacktestCosts(
                spread_points=experiment.spread_points,
                slippage_points=experiment.slippage_points,
                commission_per_trade=experiment.commission_per_trade,
            ),
            initial_capital=experiment.initial_capital,
            progress_callback=progress,
        )
        db.add_all(
            [
                BacktestTrade(
                    experiment_id=experiment.id,
                    direction=trade.direction,
                    signal_at=trade.signal_at,
                    opened_at=trade.opened_at,
                    closed_at=trade.closed_at,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    stop_loss=trade.stop_loss,
                    take_profit=trade.take_profit,
                    volume=trade.volume,
                    risk_amount=trade.risk_amount,
                    close_reason=trade.close_reason,
                    gross_pnl=trade.gross_pnl,
                    commission=trade.commission,
                    net_pnl=trade.net_pnl,
                    pnl_points=trade.pnl_points,
                    r_multiple=trade.r_multiple,
                    mfe_points=trade.mfe_points,
                    mae_points=trade.mae_points,
                    duration_seconds=trade.duration_seconds,
                )
                for trade in result.trades
            ]
        )
        experiment.summary = jsonable_encoder(result.summary)
        experiment.reason_counts = result.reason_counts
        experiment.status = "SUCCEEDED"
        experiment.completed_at = utc_now()
        experiment.progress = {"processed": len(candle_rows), "total": len(candle_rows)}
        run = db.get(Run, experiment.run_id)
        if run:
            run.status = "COMPLETED"
            run.ended_at = experiment.completed_at
        db.commit()
    except BacktestCancelled:
        db.rollback()
        experiment = db.get(BacktestExperiment, experiment_id)
        if experiment:
            experiment.status = "CANCELLED"
            experiment.completed_at = utc_now()
            run = db.get(Run, experiment.run_id)
            if run:
                run.status = "CANCELLED"
                run.ended_at = experiment.completed_at
            db.commit()
    except Exception as exc:
        db.rollback()
        experiment = db.get(BacktestExperiment, experiment_id)
        if experiment:
            experiment.status = "FAILED"
            experiment.error = str(exc)[:4000]
            experiment.completed_at = utc_now()
            run = db.get(Run, experiment.run_id)
            if run:
                run.status = "FAILED"
                run.ended_at = experiment.completed_at
            db.commit()
