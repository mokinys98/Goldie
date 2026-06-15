import copy
import uuid
from collections.abc import Sequence
from decimal import Decimal
from time import monotonic
from typing import Any

import optuna
from fastapi.encoders import jsonable_encoder
from goldie_domain import (
    BacktestCosts,
    BacktestEngine,
    BacktestInstrument,
    BotConfiguration,
    get_strategy,
    strategy_catalog,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .backtests import DEFAULT_BACKTEST_SPREAD_POINTS, utc_now
from .models import (
    Candle,
    InstrumentSpecification,
    OptimizationRun,
    OptimizationTrial,
    Run,
)

MIN_BALANCED_TRADES = 5
NO_TRADES_SCORE = Decimal("-99999")


def _catalog_entry(name: str) -> dict[str, Any]:
    for entry in strategy_catalog():
        if entry["name"] == name:
            return entry
    raise ValueError(f"Unknown strategy: {name}")


def _as_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compute_balanced_score(summary: dict[str, Any]) -> Decimal:
    net_pnl = _as_decimal(summary.get("net_pnl"))
    max_drawdown = _as_decimal(summary.get("max_drawdown"))
    total_trades = int(summary.get("total_trades") or 0)
    if total_trades == 0:
        return NO_TRADES_SCORE
    trade_penalty = Decimal(max(0, MIN_BALANCED_TRADES - total_trades)) * Decimal("50")
    drawdown_penalty = max_drawdown * Decimal("1.5")
    return net_pnl - drawdown_penalty - trade_penalty


def build_search_space(config: BotConfiguration) -> list[dict[str, Any]]:
    metadata = _catalog_entry(config.strategy.name)
    defaults = config.strategy.parameters
    search_space: list[dict[str, Any]] = []
    for name, field in metadata["parameters"].items():
        parameter: dict[str, Any] = {"name": name, "type": field.get("type")}
        if field.get("enum"):
            parameter["choices"] = list(field["enum"])
            search_space.append(parameter)
            continue
        if field.get("type") == "boolean":
            parameter["choices"] = [True, False]
            search_space.append(parameter)
            continue
        minimum = field.get("minimum")
        maximum = field.get("maximum")
        if (
            field.get("type") in {"integer", "number"}
            and minimum is not None
            and maximum is not None
        ):
            parameter["minimum"] = minimum
            parameter["maximum"] = maximum
            if "exclusiveMinimum" in field:
                parameter["exclusive_minimum"] = field["exclusiveMinimum"]
            if name in defaults:
                parameter["default"] = defaults[name]
            search_space.append(parameter)
    return search_space


def sample_parameters(
    trial: optuna.Trial,
    *,
    search_space: Sequence[dict[str, Any]],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    sampled = copy.deepcopy(defaults)
    for parameter in search_space:
        name = parameter["name"]
        if "choices" in parameter:
            sampled[name] = trial.suggest_categorical(name, parameter["choices"])
            continue
        lower = parameter["minimum"]
        if "exclusive_minimum" in parameter and lower <= parameter["exclusive_minimum"]:
            lower = (
                int(parameter["exclusive_minimum"]) + 1
                if parameter["type"] == "integer"
                else float(parameter["exclusive_minimum"]) + 1e-9
            )
        upper = parameter["maximum"]
        if parameter["type"] == "integer":
            sampled[name] = trial.suggest_int(name, int(lower), int(upper))
        else:
            sampled[name] = trial.suggest_float(name, float(lower), float(upper))
    return sampled


def _candidate_payload(
    trial_number: int,
    sampled_parameters: dict[str, Any],
    score: Decimal,
    metrics: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "trial_number": trial_number,
            "sampled_parameters": sampled_parameters,
            "score": score,
            "metrics": metrics,
            "summary": summary,
        }
    )


def reset_interrupted_optimizations(db: Session) -> int:
    result = db.execute(
        update(OptimizationRun)
        .where(OptimizationRun.status == "RUNNING")
        .values(
            status="PENDING",
            progress={"completed_trials": 0, "total_trials": 0},
            error="Worker restarted; optimization queued again.",
            started_at=None,
        )
    )
    db.commit()
    return result.rowcount


def claim_next_optimization(db: Session) -> uuid.UUID | None:
    optimization = db.scalar(
        select(OptimizationRun)
        .where(OptimizationRun.status == "PENDING")
        .order_by(OptimizationRun.created_at)
        .with_for_update(skip_locked=True)
    )
    if optimization is None:
        return None
    optimization.status = "RUNNING"
    optimization.started_at = utc_now()
    optimization.completed_at = None
    optimization.error = None
    optimization.progress = {
        "completed_trials": 0,
        "total_trials": optimization.n_trials,
    }
    run = db.get(Run, optimization.run_id)
    if run:
        run.status = "RUNNING"
    db.commit()
    return optimization.id


def _should_cancel(db: Session, optimization_id: uuid.UUID) -> bool:
    status = db.scalar(
        select(OptimizationRun.status).where(OptimizationRun.id == optimization_id)
    )
    return status == "CANCEL_REQUESTED"


def _top_candidates(
    db: Session,
    optimization_id: uuid.UUID,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(OptimizationTrial)
            .where(
                OptimizationTrial.optimization_run_id == optimization_id,
                OptimizationTrial.status == "SUCCEEDED",
            )
            .order_by(OptimizationTrial.score.desc(), OptimizationTrial.trial_number.asc())
            .limit(limit)
        )
    )
    return [
        jsonable_encoder(
            {
                "trial_number": row.trial_number,
                "sampled_parameters": row.sampled_parameters,
                "score": row.score,
                "metrics": row.metrics,
                "summary": row.summary,
            }
        )
        for row in rows
    ]


def execute_optimization(db: Session, optimization_id: uuid.UUID) -> None:
    optimization = db.get(OptimizationRun, optimization_id)
    if optimization is None:
        return
    try:
        spec = db.scalar(
            select(InstrumentSpecification)
            .where(InstrumentSpecification.market_feed_id == optimization.market_feed_id)
            .order_by(InstrumentSpecification.updated_at.desc())
        )
        if spec is None:
            raise ValueError("Instrument specification is missing")
        db.execute(
            delete(OptimizationTrial).where(
                OptimizationTrial.optimization_run_id == optimization.id
            )
        )
        optimization.best_candidate = {}
        optimization.summary = {}
        optimization.progress = {
            "completed_trials": 0,
            "successful_trials": 0,
            "failed_trials": 0,
            "total_trials": optimization.n_trials,
        }
        db.commit()
        candle_filter = (
            Candle.market_feed_id == optimization.market_feed_id,
            Candle.timeframe == "M1",
            Candle.is_complete.is_(True),
            Candle.opened_at >= optimization.date_from,
            Candle.opened_at < optimization.date_to,
        )
        total_candles = db.scalar(select(func.count(Candle.id)).where(*candle_filter)) or 0
        config = BotConfiguration.model_validate(optimization.config_snapshot)
        strategy = get_strategy(config.strategy.name)
        parameters_model = strategy.parameters_model.model_validate(
            config.strategy.parameters
        )
        minimum = strategy.required_candles(parameters_model) + 1
        if total_candles < minimum:
            raise ValueError(f"At least {minimum} completed M1 candles are required")
        search_space = build_search_space(config)
        if not search_space:
            raise ValueError("No searchable strategy parameters were found")
        statement = (
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
        instrument = BacktestInstrument(
            point=spec.point,
            tick_size=spec.point,
            tick_value=spec.point,
            volume_min=spec.minimum_trade_size
            or Decimal(1).scaleb(-(spec.trade_units_precision or 0)),
            volume_max=Decimal("1000000000"),
            volume_step=Decimal(1).scaleb(-(spec.trade_units_precision or 0)),
        )
        costs = BacktestCosts(
            spread_points=DEFAULT_BACKTEST_SPREAD_POINTS,
            fee_maker=optimization.fee_maker,
            fee_taker=optimization.fee_taker,
            slippage_small=optimization.slippage_small,
            slippage_medium=optimization.slippage_medium,
            impact_model=optimization.impact_model,
            limit_fill_timeout_s=optimization.limit_fill_timeout_s,
            min_qty_check=optimization.min_qty_check,
        )
        study = optuna.create_study(direction="maximize")
        succeeded = 0
        failed = 0
        best_payload: dict[str, Any] = optimization.best_candidate or {}
        started = monotonic()

        for _ in range(optimization.n_trials):
            if _should_cancel(db, optimization.id):
                optimization = db.get(OptimizationRun, optimization.id)
                if optimization:
                    optimization.status = "CANCELLED"
                    optimization.completed_at = utc_now()
                    optimization.summary = jsonable_encoder(
                        {
                            "completed_trials": succeeded,
                            "failed_trials": failed,
                            "duration_seconds": int(monotonic() - started),
                            "search_space": search_space,
                            "top_candidates": _top_candidates(db, optimization.id),
                        }
                    )
                    run = db.get(Run, optimization.run_id)
                    if run:
                        run.status = "CANCELLED"
                        run.ended_at = optimization.completed_at
                    db.commit()
                return

            optuna_trial = study.ask()
            sampled_parameters = sample_parameters(
                optuna_trial,
                search_space=search_space,
                defaults=config.strategy.parameters,
            )
            trial_row = OptimizationTrial(
                optimization_run_id=optimization.id,
                trial_number=optuna_trial.number,
                status="RUNNING",
                sampled_parameters=jsonable_encoder(sampled_parameters),
                metrics={},
                summary={},
                started_at=utc_now(),
            )
            db.add(trial_row)
            db.commit()
            db.refresh(trial_row)

            try:
                trial_config = copy.deepcopy(optimization.config_snapshot)
                trial_config["strategy"]["parameters"] = sampled_parameters
                result = BacktestEngine().run_stream(
                    candles=stream_candles(db, statement),
                    total_candles=total_candles,
                    config=BotConfiguration.model_validate(trial_config),
                    instrument=instrument,
                    costs=costs,
                    initial_capital=optimization.initial_capital,
                )
                score = compute_balanced_score(result.summary)
                metrics = jsonable_encoder(
                    {
                        "net_pnl": result.summary.get("net_pnl"),
                        "max_drawdown": result.summary.get("max_drawdown"),
                        "total_trades": result.summary.get("total_trades"),
                    }
                )
                trial_row.status = "SUCCEEDED"
                trial_row.score = score
                trial_row.metrics = metrics
                trial_row.summary = jsonable_encoder(result.summary)
                trial_row.completed_at = utc_now()
                study.tell(optuna_trial, float(score))
                succeeded += 1
                candidate = _candidate_payload(
                    optuna_trial.number,
                    trial_row.sampled_parameters,
                    score,
                    trial_row.metrics,
                    trial_row.summary,
                )
                if (
                    not best_payload
                    or float(candidate["score"]) > float(best_payload["score"])
                ):
                    best_payload = candidate
                    optimization.best_candidate = candidate
            except Exception as exc:
                failed += 1
                trial_row.status = "FAILED"
                trial_row.error = str(exc)[:4000]
                trial_row.completed_at = utc_now()
                study.tell(optuna_trial, state=optuna.trial.TrialState.FAIL)

            optimization.progress = {
                "completed_trials": succeeded + failed,
                "successful_trials": succeeded,
                "failed_trials": failed,
                "total_trials": optimization.n_trials,
            }
            optimization.best_candidate = best_payload
            db.commit()

        optimization.status = "SUCCEEDED"
        optimization.completed_at = utc_now()
        optimization.summary = jsonable_encoder(
            {
                "completed_trials": succeeded,
                "failed_trials": failed,
                "duration_seconds": int(monotonic() - started),
                "search_space": search_space,
                "top_candidates": _top_candidates(db, optimization.id),
            }
        )
        run = db.get(Run, optimization.run_id)
        if run:
            run.status = "COMPLETED"
            run.ended_at = optimization.completed_at
        db.commit()
    except Exception as exc:
        db.rollback()
        optimization = db.get(OptimizationRun, optimization_id)
        if optimization:
            optimization.status = "FAILED"
            optimization.error = str(exc)[:4000]
            optimization.completed_at = utc_now()
            run = db.get(Run, optimization.run_id)
            if run:
                run.status = "FAILED"
                run.ended_at = optimization.completed_at
            db.commit()


def stream_candles(db: Session, statement):
    rows = db.execute(statement).yield_per(2000)
    for row in rows:
        from goldie_domain import BacktestCandle

        yield BacktestCandle(
            opened_at=row.opened_at,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            tick_volume=row.tick_volume,
            is_complete=row.is_complete,
        )
