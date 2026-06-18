import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic

from fastapi.encoders import jsonable_encoder
from goldie_domain import (
    BacktestCancelled,
    BacktestCandle,
    BacktestCosts,
    BacktestEngine,
    BacktestInstrument,
    BotConfiguration,
    get_strategy,
)
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from .models import (
    BacktestExperiment,
    BacktestTrade,
    Candle,
    InstrumentSpecification,
    Run,
)

DEFAULT_BACKTEST_SPREAD_POINTS = Decimal("2")


def utc_now() -> datetime:
    return datetime.now(UTC)


class BacktestProgressReporter:
    def __init__(
        self,
        db: Session,
        experiment_id: uuid.UUID,
        *,
        clock: Callable[[], float] = monotonic,
        candle_interval: int = 2000,
        seconds_interval: float = 1.0,
    ) -> None:
        self.db = db
        self.experiment_id = experiment_id
        self.clock = clock
        self.candle_interval = candle_interval
        self.seconds_interval = seconds_interval
        self.last_processed = 0
        self.last_reported_at = clock()
        self.use_current_session = db.get_bind().dialect.name == "sqlite"

    def __call__(self, processed: int, total: int) -> bool:
        now = self.clock()
        final = processed == total
        if (
            not final
            and processed - self.last_processed < self.candle_interval
            and now - self.last_reported_at < self.seconds_interval
        ):
            return True
        if self.use_current_session:
            active = self._write(self.db, processed, total)
        else:
            with Session(bind=self.db.get_bind(), expire_on_commit=False) as progress_db:
                active = self._write(progress_db, processed, total)
        self.last_processed = processed
        self.last_reported_at = now
        return active

    def _write(self, db: Session, processed: int, total: int) -> bool:
        status = db.scalar(
            select(BacktestExperiment.status).where(
                BacktestExperiment.id == self.experiment_id
            )
        )
        if status == "CANCEL_REQUESTED":
            return False
        db.execute(
            update(BacktestExperiment)
            .where(BacktestExperiment.id == self.experiment_id)
            .values(progress={"processed": processed, "total": total})
        )
        db.commit()
        return True


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
        candle_filter = (
            Candle.market_feed_id == experiment.market_feed_id,
            Candle.timeframe == "M1",
            Candle.is_complete.is_(True),
            Candle.opened_at >= experiment.date_from,
            Candle.opened_at < experiment.date_to,
        )
        total_candles = db.scalar(
            select(func.count(Candle.id)).where(*candle_filter)
        ) or 0
        candle_statement = (
            select(
                Candle.opened_at,
                Candle.open,
                Candle.high,
                Candle.low,
                Candle.close,
                Candle.tick_volume,
                Candle.is_complete,
            )
            .where(*candle_filter)
            .order_by(Candle.opened_at)
            .execution_options(stream_results=True, yield_per=2000)
        )
        config = BotConfiguration.model_validate(experiment.config_snapshot)
        strategy = get_strategy(config.strategy.name)
        minimum = strategy.required_candles(
            strategy.parameters_model.model_validate(config.strategy.parameters)
        ) + 1
        if total_candles < minimum:
            raise ValueError(f"At least {minimum} completed M1 candles are required")
        step = Decimal(1).scaleb(-(spec.trade_units_precision or 0))
        progress = BacktestProgressReporter(db, experiment.id)

        result = BacktestEngine().run_stream(
            candles=stream_candles(db, candle_statement),
            total_candles=total_candles,
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
                spread_points=DEFAULT_BACKTEST_SPREAD_POINTS,
                fill_mode=experiment.fill_mode,
                fee_maker=experiment.fee_maker,
                fee_taker=experiment.fee_taker,
                taker_slippage=experiment.taker_slippage,
                slippage_small=experiment.slippage_small,
                slippage_medium=experiment.medium_impact,
                medium_impact=experiment.medium_impact,
                impact_model=experiment.impact_model,
                model_sqrt_limit=experiment.model_sqrt_limit,
                limit_fill_timeout_s=experiment.limit_fill_timeout_s,
                min_qty_threshold=experiment.min_qty_threshold,
                min_qty_check=experiment.min_qty_check,
            ),
            initial_capital=experiment.initial_capital,
            progress_callback=progress,
        )
        insert_trades(db, experiment.id, result.trades)
        experiment.summary = jsonable_encoder(result.summary)
        experiment.reason_counts = result.reason_counts
        experiment.status = "SUCCEEDED"
        experiment.completed_at = utc_now()
        experiment.progress = {"processed": total_candles, "total": total_candles}
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


def stream_candles(db: Session, statement) -> Iterator[BacktestCandle]:
    rows = db.execute(statement).yield_per(2000)
    for row in rows:
        yield BacktestCandle(
            opened_at=row.opened_at,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            tick_volume=row.tick_volume,
            is_complete=row.is_complete,
        )


def insert_trades(db: Session, experiment_id: uuid.UUID, trades: list) -> None:
    rows = []
    for trade in trades:
        rows.append(
            {
                "experiment_id": experiment_id,
                "direction": trade.direction,
                "signal_at": trade.signal_at,
                "opened_at": trade.opened_at,
                "closed_at": trade.closed_at,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "volume": trade.volume,
                "risk_amount": trade.risk_amount,
                "close_reason": trade.close_reason,
                "gross_pnl": trade.gross_pnl,
                "commission": trade.commission,
                "net_pnl": trade.net_pnl,
                "pnl_points": trade.pnl_points,
                "r_multiple": trade.r_multiple,
                "mfe_points": trade.mfe_points,
                "mae_points": trade.mae_points,
                "duration_seconds": trade.duration_seconds,
            }
        )
        if len(rows) == 1000:
            db.execute(insert(BacktestTrade), rows)
            rows.clear()
    if rows:
        db.execute(insert(BacktestTrade), rows)
