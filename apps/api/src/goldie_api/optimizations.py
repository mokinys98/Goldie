import copy
import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

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
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from .backtests import DEFAULT_BACKTEST_SPREAD_POINTS, utc_now
from .models import (
    Candle,
    InstrumentSpecification,
    OptimizationRun,
    OptimizationTrial,
    OptimizationTrialTrade,
    Run,
)
from .optimization_diagnostics import (
    build_run_decision_sections,
    build_trial_metrics,
)

MIN_BALANCED_TRADES = 30
NO_TRADES_SCORE = Decimal("-99999")
OPTIMIZATION_COMMIT_INTERVAL = 5
OPTIMIZATION_CANCEL_CHECK_INTERVAL = 5
STRATEGY_SEARCH_PHASE = "STRATEGY_SEARCH"
FIXED_CONFIG_VALIDATION_PHASE = "FIXED_CONFIG_VALIDATION"
CANDIDATE_VALIDATION_PHASE = "CANDIDATE_VALIDATION"
VALIDATION_PHASES = (CANDIDATE_VALIDATION_PHASE, FIXED_CONFIG_VALIDATION_PHASE)
VALIDATION_CANDIDATE_LIMIT = 5
MAX_ABS_EXPECTANCY_R = Decimal("10")
MIN_REWARD_RISK_RATIO = Decimal("1.5")
MAX_REWARD_RISK_RATIO = Decimal("4.0")
MAX_AMBIGUOUS_EXIT_PCT = Decimal("5")

logger = logging.getLogger(__name__)


def _seconds(value: float) -> float:
    return round(value, 6)


def _timings_payload(timings: dict[str, float], started: float) -> dict[str, float]:
    return {
        "candle_load_seconds": _seconds(timings["candle_load_seconds"]),
        "optuna_sampling_seconds": _seconds(timings["optuna_sampling_seconds"]),
        "backtest_seconds": _seconds(timings["backtest_seconds"]),
        "database_commit_seconds": _seconds(timings["database_commit_seconds"]),
        "total_seconds": _seconds(monotonic() - started),
    }


def _is_commit_checkpoint(completed: int, total: int) -> bool:
    return completed % OPTIMIZATION_COMMIT_INTERVAL == 0 and completed < total


def _is_cancellation_checkpoint(trial_index: int) -> bool:
    return trial_index % OPTIMIZATION_CANCEL_CHECK_INTERVAL == 0


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


def validate_trial_summary(summary: dict[str, Any]) -> None:
    ambiguous_exit_pct = _as_decimal(summary.get("ambiguous_exit_pct"))
    if ambiguous_exit_pct > MAX_AMBIGUOUS_EXIT_PCT:
        raise ValueError(
            "Invalid optimization candidate: "
            f"ambiguous_exit_pct={ambiguous_exit_pct} exceeds {MAX_AMBIGUOUS_EXIT_PCT}%"
        )
    expectancy_r = summary.get("expectancy_r")
    if expectancy_r is None:
        return
    value = _as_decimal(expectancy_r)
    if abs(value) > MAX_ABS_EXPECTANCY_R:
        raise ValueError(
            "Invalid optimization trial: "
            f"abs(expectancy_r)={abs(value)} exceeds {MAX_ABS_EXPECTANCY_R}"
        )


def validate_reward_risk_ratio(config: BotConfiguration) -> None:
    stop_loss = config.theoretical_trade.stop_loss_points
    take_profit = config.theoretical_trade.take_profit_points
    ratio = take_profit / stop_loss
    if not MIN_REWARD_RISK_RATIO <= ratio <= MAX_REWARD_RISK_RATIO:
        raise ValueError(
            "Invalid optimization trial: "
            f"take_profit_points / stop_loss_points={ratio} must be between "
            f"{MIN_REWARD_RISK_RATIO} and {MAX_REWARD_RISK_RATIO}"
        )


def split_optimization_period(date_from, date_to):
    split_at = date_from + (date_to - date_from) * 4 / 5
    return (date_from, split_at), (split_at, date_to)


def build_search_space(
    config: BotConfiguration,
    optimization_ranges: dict[str, dict[str, Any]] | None = None,
    trade_ranges: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
        configured_range = (optimization_ranges or {}).get(name)
        uses_optimization_minimum = "optimization_minimum" in field
        minimum = (
            configured_range["minimum"]
            if configured_range is not None
            else (
                field["optimization_minimum"]
                if uses_optimization_minimum
                else field.get("minimum", field.get("exclusiveMinimum"))
            )
        )
        maximum = (
            configured_range["maximum"]
            if configured_range is not None
            else field.get("optimization_maximum", field.get("maximum"))
        )
        if (
            field.get("type") in {"integer", "number"}
            and minimum is not None
            and maximum is not None
        ):
            parameter["minimum"] = minimum
            parameter["maximum"] = maximum
            if (
                "exclusiveMinimum" in field
                and not uses_optimization_minimum
                and configured_range is None
            ):
                parameter["exclusive_minimum"] = field["exclusiveMinimum"]
            if name in defaults:
                parameter["default"] = defaults[name]
            search_space.append(parameter)
    for name, configured_range in (trade_ranges or {}).items():
        search_space.append(
            {
                "name": f"theoretical_trade.{name}",
                "type": "number",
                "minimum": configured_range["minimum"],
                "maximum": configured_range["maximum"],
                "step": configured_range["step"],
                "default": float(getattr(config.theoretical_trade, name)),
            }
        )
    return search_space


def sample_parameters(
    trial: optuna.Trial,
    *,
    search_space: Sequence[dict[str, Any]],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    sampled = copy.deepcopy(defaults)
    strategy_space = [
        parameter
        for parameter in search_space
        if not parameter["name"].startswith("theoretical_trade.")
    ]
    parameter_names = {parameter["name"] for parameter in strategy_space}
    dependencies = {
        "medium_ema_period": "fast_ema_period",
        "slow_ema_period": "medium_ema_period",
        "max_atr_points": "min_atr_points",
        "rsi_overbought": "rsi_oversold",
        "stochastic_overbought": "stochastic_oversold",
    }
    if {"buy_rsi_min", "buy_rsi_max"} <= parameter_names:
        dependencies["buy_rsi_max"] = "buy_rsi_min"
    if {"sell_rsi_min", "sell_rsi_max"} <= parameter_names:
        dependencies["sell_rsi_max"] = "sell_rsi_min"
    elif {"buy_rsi_max", "sell_rsi_min"} <= parameter_names:
        dependencies["sell_rsi_min"] = "buy_rsi_max"
    if {"sell_rsi_max", "buy_rsi_min"} <= parameter_names and "sell_rsi_min" not in parameter_names:
        dependencies["sell_rsi_max"] = "buy_rsi_min"
    positions = {parameter["name"]: index for index, parameter in enumerate(strategy_space)}

    def dependency_order(parameter: dict[str, Any]) -> tuple[int, int]:
        depth = 0
        name = parameter["name"]
        seen: set[str] = set()
        while name in dependencies and name not in seen:
            seen.add(name)
            name = dependencies[name]
            depth += 1
        return depth, positions[parameter["name"]]

    # Catalog property order is not an API guarantee. Sample constrained lower/upper
    # values before the parameters whose ranges depend on them.
    ordered_search_space = sorted(strategy_space, key=dependency_order)
    for parameter in ordered_search_space:
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
            lower = int(lower)
            upper = int(upper)
        else:
            lower = float(lower)
            upper = float(upper)
        if name == "medium_ema_period" and "fast_ema_period" in sampled:
            lower = max(lower, int(sampled["fast_ema_period"]) + 1)
        elif name == "slow_ema_period":
            preceding_period = sampled.get("medium_ema_period", sampled.get("fast_ema_period"))
            if preceding_period is not None:
                lower = max(lower, int(preceding_period) + 1)
        elif (
            name == "buy_rsi_max" and "buy_rsi_min" in sampled and "buy_rsi_min" in parameter_names
        ):
            lower = max(lower, sampled["buy_rsi_min"])
        elif (
            name == "sell_rsi_min"
            and "buy_rsi_max" in sampled
            and "sell_rsi_max" not in parameter_names
        ):
            lower = max(lower, sampled["buy_rsi_max"])
        elif (
            name == "sell_rsi_max"
            and "sell_rsi_min" in sampled
            and "sell_rsi_min" in parameter_names
        ):
            lower = max(lower, sampled["sell_rsi_min"])
        elif (
            name == "sell_rsi_max"
            and "buy_rsi_min" in sampled
            and "sell_rsi_min" not in parameter_names
        ):
            upper = min(upper, sampled["buy_rsi_min"])
        elif name == "max_atr_points" and "min_atr_points" in sampled:
            lower = max(lower, sampled["min_atr_points"])
        elif name == "rsi_overbought" and "rsi_oversold" in sampled:
            lower = max(lower, sampled["rsi_oversold"])
        elif name == "stochastic_overbought" and "stochastic_oversold" in sampled:
            lower = max(lower, sampled["stochastic_oversold"])
        if parameter["type"] == "integer":
            sampled[name] = trial.suggest_int(name, int(lower), int(upper))
        else:
            sampled[name] = trial.suggest_float(name, float(lower), float(upper))
    return sampled


def sample_trade_overrides(
    trial: optuna.Trial,
    *,
    search_space: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    sampled: dict[str, Any] = {}
    prefix = "theoretical_trade."
    for parameter in search_space:
        name = parameter["name"]
        if not name.startswith(prefix):
            continue
        field_name = name.removeprefix(prefix)
        sampled[field_name] = trial.suggest_float(
            name,
            float(parameter["minimum"]),
            float(parameter["maximum"]),
            step=float(parameter["step"]),
        )
    return {"theoretical_trade": sampled} if sampled else {}


def _candidate_payload(
    trial_number: int,
    sampled_parameters: dict[str, Any],
    config_overrides: dict[str, Any],
    score: Decimal,
    metrics: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "trial_number": trial_number,
            "sampled_parameters": sampled_parameters,
            "config_overrides": config_overrides,
            "score": score,
            "metrics": metrics,
            "summary": summary,
        }
    )


def _execution_model_payload(optimization: OptimizationRun) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "fill_mode": optimization.fill_mode,
            "fee_maker": optimization.fee_maker,
            "fee_taker": optimization.fee_taker,
            "taker_slippage": optimization.taker_slippage,
            "slippage_small": optimization.slippage_small,
            "medium_impact": optimization.medium_impact,
            "impact_model": optimization.impact_model,
            "model_sqrt_limit": optimization.model_sqrt_limit,
            "limit_fill_timeout_s": optimization.limit_fill_timeout_s,
            "min_qty_threshold": optimization.min_qty_threshold,
            "min_qty_check": optimization.min_qty_check,
        }
    )


def _trade_session_payload(trade, config: BotConfiguration) -> dict[str, Any]:
    timezone = ZoneInfo(config.session.timezone)
    opened_at = trade.opened_at
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=ZoneInfo("UTC"))
    return {
        "timezone": config.session.timezone,
        "local_opened_at": opened_at.astimezone(timezone),
        "window_start": config.session.start_time.isoformat(),
        "window_end": config.session.end_time.isoformat(),
    }


def insert_optimization_trial_trades(
    db: Session,
    trial_id: uuid.UUID,
    trades: list,
    config: BotConfiguration,
) -> None:
    rows = []
    for trade in trades:
        rows.append(
            {
                "trial_id": trial_id,
                "direction": trade.direction,
                "signal_reason": trade.signal_reason,
                "signal_at": trade.signal_at,
                "opened_at": trade.opened_at,
                "closed_at": trade.closed_at,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "close_reason": trade.close_reason,
                "gross_pnl": trade.gross_pnl,
                "commission": trade.commission,
                "net_pnl": trade.net_pnl,
                "pnl_points": trade.pnl_points,
                "r_multiple": trade.r_multiple,
                "mfe_points": trade.mfe_points,
                "mae_points": trade.mae_points,
                "duration_seconds": trade.duration_seconds,
                "session": jsonable_encoder(_trade_session_payload(trade, config)),
            }
        )
        if len(rows) == 1000:
            db.execute(insert(OptimizationTrialTrade), rows)
            rows.clear()
    if rows:
        db.execute(insert(OptimizationTrialTrade), rows)


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
    status = db.scalar(select(OptimizationRun.status).where(OptimizationRun.id == optimization_id))
    return status == "CANCEL_REQUESTED"


def _top_candidates(
    db: Session,
    optimization_id: uuid.UUID,
    limit: int = 5,
    phase: str | Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    filters = [
        OptimizationTrial.optimization_run_id == optimization_id,
        OptimizationTrial.status == "SUCCEEDED",
    ]
    if phase is not None:
        filters.append(
            OptimizationTrial.phase.in_(phase)
            if not isinstance(phase, str)
            else OptimizationTrial.phase == phase
        )
    rows = list(
        db.scalars(
            select(OptimizationTrial)
            .where(*filters)
            .order_by(OptimizationTrial.score.desc(), OptimizationTrial.trial_number.asc())
            .limit(limit)
        )
    )
    return [
        jsonable_encoder(
            {
                "trial_number": row.trial_number,
                "phase": row.phase,
                "sampled_parameters": row.sampled_parameters,
                "config_overrides": row.config_overrides,
                "score": row.score,
                "metrics": row.metrics,
                "summary": row.summary,
            }
        )
        for row in rows
    ]


def _terminal_summary_payload(
    db: Session,
    optimization: OptimizationRun,
    *,
    completed_trials: int,
    failed_trials: int,
    strategy_completed_trials: int,
    strategy_failed_trials: int,
    validation_completed_trials: int,
    validation_failed_trials: int,
    duration_seconds: int,
    search_period,
    validation_period,
    search_space: list[dict[str, Any]],
    fixed_config_grid: list[dict[str, Any]] | None,
    search_total_candles: int,
    validation_total_candles: int,
    execution_model: dict[str, Any],
    timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "completed_trials": completed_trials,
        "failed_trials": failed_trials,
        "strategy_completed_trials": strategy_completed_trials,
        "strategy_failed_trials": strategy_failed_trials,
        "validation_completed_trials": validation_completed_trials,
        "validation_failed_trials": validation_failed_trials,
        "duration_seconds": duration_seconds,
        "search_period": (
            {"date_from": search_period[0], "date_to": search_period[1]} if search_period else None
        ),
        "validation_period": (
            {"date_from": validation_period[0], "date_to": validation_period[1]}
            if validation_period
            else None
        ),
        "search_space": search_space,
        "execution_model": execution_model,
        "top_candidates": _top_candidates(db, optimization.id, phase=STRATEGY_SEARCH_PHASE),
        "validation_candidates": _top_candidates(
            db, optimization.id, phase=VALIDATION_PHASES
        ),
    }
    if timings is not None:
        payload["timings"] = timings
    payload.update(
        build_run_decision_sections(
            db,
            optimization,
            search_period=search_period,
            validation_period=validation_period,
            search_total_candles=search_total_candles,
            validation_total_candles=validation_total_candles,
            search_space=search_space,
            fixed_config_grid=fixed_config_grid,
            execution_model=execution_model,
        )
    )
    return jsonable_encoder(payload)


def _commit_timed(db: Session, timings: dict[str, float]) -> None:
    started = monotonic()
    db.commit()
    timings["database_commit_seconds"] += monotonic() - started


def _persist_terminal_timings(
    db: Session,
    optimization: OptimizationRun,
    *,
    timings: dict[str, float],
    started: float,
    succeeded: int,
    failed: int,
) -> None:
    """Commit terminal state, then persist timing for that commit separately."""
    optimization_id = optimization.id
    terminal_status = optimization.status
    summary = dict(optimization.summary or {})
    _commit_timed(db, timings)
    summary["timings"] = _timings_payload(timings, started)
    optimization.summary = summary
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "optimization_timing_persist_failed optimization_id=%s",
            optimization_id,
        )
    timing_values = summary["timings"]
    logger.info(
        "optimization_terminal optimization_id=%s status=%s succeeded=%s failed=%s "
        "candle_load_seconds=%.6f optuna_sampling_seconds=%.6f "
        "backtest_seconds=%.6f database_commit_seconds=%.6f total_seconds=%.6f",
        optimization_id,
        terminal_status,
        succeeded,
        failed,
        timing_values["candle_load_seconds"],
        timing_values["optuna_sampling_seconds"],
        timing_values["backtest_seconds"],
        timing_values["database_commit_seconds"],
        timing_values["total_seconds"],
    )


def execute_optimization(db: Session, optimization_id: uuid.UUID) -> None:
    started = monotonic()
    timings = {
        "candle_load_seconds": 0.0,
        "optuna_sampling_seconds": 0.0,
        "backtest_seconds": 0.0,
        "database_commit_seconds": 0.0,
    }
    succeeded = 0
    failed = 0
    validation_succeeded = 0
    validation_failed = 0
    search_space: list[dict[str, Any]] = []
    search_period = None
    validation_period = None
    search_total_candles = 0
    validation_total_candles = 0
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
        existing_trial_ids = select(OptimizationTrial.id).where(
            OptimizationTrial.optimization_run_id == optimization.id
        )
        db.execute(
            delete(OptimizationTrialTrade).where(
                OptimizationTrialTrade.trial_id.in_(existing_trial_ids)
            )
        )
        db.execute(
            delete(OptimizationTrial).where(
                OptimizationTrial.optimization_run_id == optimization.id
            )
        )
        optimization.best_candidate = {}
        optimization.summary = {}
        optimization.progress = {
            "phase": STRATEGY_SEARCH_PHASE,
            "completed_trials": 0,
            "successful_trials": 0,
            "failed_trials": 0,
            "total_trials": optimization.n_trials,
            "strategy_trials_completed": 0,
            "strategy_trials_total": optimization.n_trials,
            "validation_trials_completed": 0,
            "validation_trials_total": 0,
        }
        _commit_timed(db, timings)
        search_period, validation_period = split_optimization_period(
            optimization.date_from,
            optimization.date_to,
        )
        base_candle_filter = (
            Candle.market_feed_id == optimization.market_feed_id,
            Candle.timeframe == "M1",
            Candle.is_complete.is_(True),
        )
        search_candle_filter = base_candle_filter + (
            Candle.opened_at >= search_period[0],
            Candle.opened_at < search_period[1],
        )
        validation_candle_filter = base_candle_filter + (
            Candle.opened_at >= validation_period[0],
            Candle.opened_at < validation_period[1],
        )
        candle_load_started = monotonic()
        search_total_candles = (
            db.scalar(select(func.count(Candle.id)).where(*search_candle_filter)) or 0
        )
        validation_total_candles = (
            db.scalar(select(func.count(Candle.id)).where(*validation_candle_filter)) or 0
        )
        timings["candle_load_seconds"] += monotonic() - candle_load_started
        config = BotConfiguration.model_validate(optimization.config_snapshot)
        strategy = get_strategy(config.strategy.name)
        parameters_model = strategy.parameters_model.model_validate(config.strategy.parameters)
        minimum = strategy.required_candles(parameters_model) + 1
        if search_total_candles < minimum or validation_total_candles < minimum:
            raise ValueError(
                f"At least {minimum} completed M1 candles are required in both "
                "search and validation periods"
            )
        search_space = optimization.search_space_snapshot or build_search_space(config)
        if not search_space:
            raise ValueError("No searchable strategy parameters were found")

        def candle_statement(filters):
            return (
                select(
                    Candle.opened_at,
                    Candle.open,
                    Candle.high,
                    Candle.low,
                    Candle.close,
                    Candle.tick_volume,
                    Candle.is_complete,
                )
                .where(*filters)
                .order_by(Candle.opened_at)
                .execution_options(stream_results=True, yield_per=2000)
            )

        candle_load_started = monotonic()
        search_candles = list(stream_candles(db, candle_statement(search_candle_filter)))
        validation_candles = list(stream_candles(db, candle_statement(validation_candle_filter)))
        timings["candle_load_seconds"] += monotonic() - candle_load_started
        raw_tick_size = (spec.provider_metadata or {}).get("tick_size")
        tick_size = Decimal(str(raw_tick_size)) if raw_tick_size is not None else spec.point
        if spec.point <= 0 or tick_size <= 0:
            raise ValueError("Instrument point_size and tick_size must be positive")
        instrument = BacktestInstrument(
            point=spec.point,
            tick_size=tick_size,
            tick_value=tick_size,
            volume_min=spec.minimum_trade_size
            or Decimal(1).scaleb(-(spec.trade_units_precision or 0)),
            volume_max=Decimal("1000000000"),
            volume_step=Decimal(1).scaleb(-(spec.trade_units_precision or 0)),
        )
        costs = BacktestCosts(
            spread_points=DEFAULT_BACKTEST_SPREAD_POINTS,
            fill_mode=optimization.fill_mode,
            fee_maker=optimization.fee_maker,
            fee_taker=optimization.fee_taker,
            taker_slippage=optimization.taker_slippage,
            slippage_small=optimization.slippage_small,
            slippage_medium=optimization.medium_impact,
            medium_impact=optimization.medium_impact,
            impact_model=optimization.impact_model,
            model_sqrt_limit=optimization.model_sqrt_limit,
            limit_fill_timeout_s=optimization.limit_fill_timeout_s,
            min_qty_threshold=optimization.min_qty_threshold,
            min_qty_check=optimization.min_qty_check,
        )
        study = optuna.create_study(direction="maximize")
        best_payload: dict[str, Any] = optimization.best_candidate or {}

        for trial_index in range(optimization.n_trials):
            if _is_cancellation_checkpoint(trial_index) and _should_cancel(db, optimization.id):
                optimization = db.get(OptimizationRun, optimization.id)
                if optimization:
                    optimization.status = "CANCELLED"
                    optimization.completed_at = utc_now()
                    optimization.summary = _terminal_summary_payload(
                        db,
                        optimization,
                        completed_trials=succeeded,
                        failed_trials=failed,
                        strategy_completed_trials=succeeded,
                        strategy_failed_trials=failed,
                        validation_completed_trials=0,
                        validation_failed_trials=0,
                        duration_seconds=int(monotonic() - started),
                        search_period=search_period,
                        validation_period=validation_period,
                        search_space=search_space,
                        fixed_config_grid=[],
                        search_total_candles=search_total_candles,
                        validation_total_candles=validation_total_candles,
                        execution_model=_execution_model_payload(optimization),
                    )
                    run = db.get(Run, optimization.run_id)
                    if run:
                        run.status = "CANCELLED"
                        run.ended_at = optimization.completed_at
                    _persist_terminal_timings(
                        db,
                        optimization,
                        timings=timings,
                        started=started,
                        succeeded=succeeded,
                        failed=failed,
                    )
                return

            sampling_started = monotonic()
            optuna_trial = study.ask()
            sampled_parameters = sample_parameters(
                optuna_trial,
                search_space=search_space,
                defaults=config.strategy.parameters,
            )
            config_overrides = sample_trade_overrides(
                optuna_trial,
                search_space=search_space,
            )
            sampling_seconds = monotonic() - sampling_started
            timings["optuna_sampling_seconds"] += sampling_seconds
            trial_row = OptimizationTrial(
                optimization_run_id=optimization.id,
                trial_number=optuna_trial.number,
                phase=STRATEGY_SEARCH_PHASE,
                config_overrides=jsonable_encoder(config_overrides),
                status="RUNNING",
                sampled_parameters=jsonable_encoder(sampled_parameters),
                metrics={
                    "timings": {
                        "sampling_seconds": _seconds(sampling_seconds),
                        "backtest_seconds": 0.0,
                    }
                },
                summary={},
                started_at=utc_now(),
            )
            db.add(trial_row)

            backtest_started = monotonic()
            try:
                trial_config = copy.deepcopy(optimization.config_snapshot)
                trial_config["strategy"]["parameters"] = sampled_parameters
                trial_config["theoretical_trade"].update(
                    config_overrides.get("theoretical_trade", {})
                )
                trial_bot_config = BotConfiguration.model_validate(trial_config)
                if config_overrides:
                    validate_reward_risk_ratio(trial_bot_config)
                result = BacktestEngine().run_stream(
                    candles=iter(search_candles),
                    total_candles=search_total_candles,
                    config=trial_bot_config,
                    instrument=instrument,
                    costs=costs,
                    initial_capital=optimization.initial_capital,
                    use_fast_strategy=True,
                    collect_reason_counts=False,
                )
                validate_trial_summary(result.summary)
                backtest_seconds = monotonic() - backtest_started
                timings["backtest_seconds"] += backtest_seconds
                score = compute_balanced_score(result.summary)
                metrics = build_trial_metrics(
                    result.summary,
                    timings={
                        "sampling_seconds": _seconds(sampling_seconds),
                        "backtest_seconds": _seconds(backtest_seconds),
                    },
                    condition_counts=result.condition_counts,
                )
                trial_row.status = "SUCCEEDED"
                trial_row.score = score
                trial_row.metrics = metrics
                trial_row.summary = jsonable_encoder(result.summary)
                trial_row.completed_at = utc_now()
                db.flush()
                insert_optimization_trial_trades(
                    db,
                    trial_row.id,
                    result.trades,
                    trial_bot_config,
                )
                study.tell(optuna_trial, float(score))
                succeeded += 1
                candidate = _candidate_payload(
                    optuna_trial.number,
                    trial_row.sampled_parameters,
                    trial_row.config_overrides,
                    score,
                    trial_row.metrics,
                    trial_row.summary,
                )
                if not best_payload or float(candidate["score"]) > float(best_payload["score"]):
                    best_payload = candidate
                    optimization.best_candidate = candidate
            except Exception as exc:
                backtest_seconds = monotonic() - backtest_started
                timings["backtest_seconds"] += backtest_seconds
                failed += 1
                trial_row.status = "FAILED"
                trial_row.metrics = {
                    "timings": {
                        "sampling_seconds": _seconds(sampling_seconds),
                        "backtest_seconds": _seconds(backtest_seconds),
                    }
                }
                trial_row.error = str(exc)[:4000]
                trial_row.completed_at = utc_now()
                study.tell(optuna_trial, state=optuna.trial.TrialState.FAIL)

            optimization.progress = {
                "phase": STRATEGY_SEARCH_PHASE,
                "completed_trials": succeeded + failed,
                "successful_trials": succeeded,
                "failed_trials": failed,
                "total_trials": optimization.n_trials,
                "strategy_trials_completed": succeeded + failed,
                "strategy_trials_total": optimization.n_trials,
                "validation_trials_completed": 0,
                "validation_trials_total": 0,
            }
            optimization.best_candidate = best_payload
            completed = succeeded + failed
            if _is_commit_checkpoint(completed, optimization.n_trials):
                _commit_timed(db, timings)

        search_candidates = list(
            db.scalars(
                select(OptimizationTrial)
                .where(
                    OptimizationTrial.optimization_run_id == optimization.id,
                    OptimizationTrial.phase == STRATEGY_SEARCH_PHASE,
                    OptimizationTrial.status == "SUCCEEDED",
                )
                .order_by(
                    OptimizationTrial.score.desc(),
                    OptimizationTrial.trial_number.asc(),
                )
                .limit(VALIDATION_CANDIDATE_LIMIT)
            )
        )
        if not search_candidates:
            raise ValueError("No successful strategy candidates were produced")

        validation_total = len(search_candidates)
        total_trials = optimization.n_trials + validation_total
        optimization.progress = {
            "phase": CANDIDATE_VALIDATION_PHASE,
            "completed_trials": succeeded + failed,
            "successful_trials": succeeded,
            "failed_trials": failed,
            "total_trials": total_trials,
            "strategy_trials_completed": succeeded + failed,
            "strategy_trials_total": optimization.n_trials,
            "validation_trials_completed": 0,
            "validation_trials_total": validation_total,
        }
        _commit_timed(db, timings)

        validation_best: dict[str, Any] = {}
        validation_index = 0
        for search_candidate in search_candidates:
            if _is_cancellation_checkpoint(validation_index) and _should_cancel(
                db, optimization.id
            ):
                optimization = db.get(OptimizationRun, optimization.id)
                if optimization:
                    optimization.status = "CANCELLED"
                    optimization.completed_at = utc_now()
                    optimization.summary = _terminal_summary_payload(
                        db,
                        optimization,
                        completed_trials=succeeded + validation_succeeded,
                        failed_trials=failed + validation_failed,
                        strategy_completed_trials=succeeded,
                        strategy_failed_trials=failed,
                        validation_completed_trials=validation_succeeded,
                        validation_failed_trials=validation_failed,
                        duration_seconds=int(monotonic() - started),
                        search_period=search_period,
                        validation_period=validation_period,
                        search_space=search_space,
                        fixed_config_grid=[],
                        search_total_candles=search_total_candles,
                        validation_total_candles=validation_total_candles,
                        execution_model=_execution_model_payload(optimization),
                    )
                    run = db.get(Run, optimization.run_id)
                    if run:
                        run.status = "CANCELLED"
                        run.ended_at = optimization.completed_at
                    _persist_terminal_timings(
                        db,
                        optimization,
                        timings=timings,
                        started=started,
                        succeeded=succeeded + validation_succeeded,
                        failed=failed + validation_failed,
                    )
                return

            config_overrides = search_candidate.config_overrides or {}
            trial_number = optimization.n_trials + validation_index
            validation_index += 1
            trial_row = OptimizationTrial(
                optimization_run_id=optimization.id,
                trial_number=trial_number,
                phase=CANDIDATE_VALIDATION_PHASE,
                config_overrides=jsonable_encoder(config_overrides),
                status="RUNNING",
                sampled_parameters=search_candidate.sampled_parameters,
                metrics={
                    "timings": {
                        "sampling_seconds": 0.0,
                        "backtest_seconds": 0.0,
                    }
                },
                summary={},
                started_at=utc_now(),
            )
            db.add(trial_row)
            backtest_started = monotonic()
            try:
                trial_config = copy.deepcopy(optimization.config_snapshot)
                trial_config["strategy"]["parameters"] = search_candidate.sampled_parameters
                trial_config["theoretical_trade"].update(
                    config_overrides.get("theoretical_trade", {})
                )
                trial_bot_config = BotConfiguration.model_validate(trial_config)
                if config_overrides:
                    validate_reward_risk_ratio(trial_bot_config)
                result = BacktestEngine().run_stream(
                    candles=iter(validation_candles),
                    total_candles=validation_total_candles,
                    config=trial_bot_config,
                    instrument=instrument,
                    costs=costs,
                    initial_capital=optimization.initial_capital,
                    use_fast_strategy=True,
                    collect_reason_counts=True,
                )
                validate_trial_summary(result.summary)
                backtest_seconds = monotonic() - backtest_started
                timings["backtest_seconds"] += backtest_seconds
                score = compute_balanced_score(result.summary)
                metrics = build_trial_metrics(
                    result.summary,
                    timings={
                        "sampling_seconds": 0.0,
                        "backtest_seconds": _seconds(backtest_seconds),
                    },
                    reason_counts=result.reason_counts,
                    condition_counts=result.condition_counts,
                )
                trial_row.status = "SUCCEEDED"
                trial_row.score = score
                trial_row.metrics = metrics
                trial_row.summary = jsonable_encoder(result.summary)
                trial_row.completed_at = utc_now()
                db.flush()
                insert_optimization_trial_trades(
                    db,
                    trial_row.id,
                    result.trades,
                    trial_bot_config,
                )
                validation_succeeded += 1
                candidate = jsonable_encoder(
                    {
                        "trial_number": trial_number,
                        "sampled_parameters": search_candidate.sampled_parameters,
                        "config_overrides": config_overrides,
                        "fixed_config_overrides": config_overrides,
                        "score": score,
                        "metrics": metrics,
                        "summary": result.summary,
                        "search_score": search_candidate.score,
                        "search_metrics": search_candidate.metrics,
                        "validation_score": score,
                        "validation_metrics": metrics,
                    }
                )
                if not validation_best or float(candidate["score"]) > float(
                    validation_best["score"]
                ):
                    validation_best = candidate
                    optimization.best_candidate = candidate
            except Exception as exc:
                backtest_seconds = monotonic() - backtest_started
                timings["backtest_seconds"] += backtest_seconds
                validation_failed += 1
                trial_row.status = "FAILED"
                trial_row.metrics = {
                    "timings": {
                        "sampling_seconds": 0.0,
                        "backtest_seconds": _seconds(backtest_seconds),
                    }
                }
                trial_row.error = str(exc)[:4000]
                trial_row.completed_at = utc_now()

            validation_completed = validation_succeeded + validation_failed
            optimization.progress = {
                "phase": CANDIDATE_VALIDATION_PHASE,
                "completed_trials": succeeded + failed + validation_completed,
                "successful_trials": succeeded + validation_succeeded,
                "failed_trials": failed + validation_failed,
                "total_trials": total_trials,
                "strategy_trials_completed": succeeded + failed,
                "strategy_trials_total": optimization.n_trials,
                "validation_trials_completed": validation_completed,
                "validation_trials_total": validation_total,
            }
            completed = succeeded + failed + validation_completed
            if _is_commit_checkpoint(completed, total_trials):
                _commit_timed(db, timings)

        if not validation_best:
            raise ValueError("No successful candidate validation trials were produced")

        optimization.status = "SUCCEEDED"
        optimization.completed_at = utc_now()
        optimization.summary = _terminal_summary_payload(
            db,
            optimization,
            completed_trials=succeeded + validation_succeeded,
            failed_trials=failed + validation_failed,
            strategy_completed_trials=succeeded,
            strategy_failed_trials=failed,
            validation_completed_trials=validation_succeeded,
            validation_failed_trials=validation_failed,
            duration_seconds=int(monotonic() - started),
            timings=_timings_payload(timings, started),
            search_period=search_period,
            validation_period=validation_period,
            search_space=search_space,
            fixed_config_grid=[],
            search_total_candles=search_total_candles,
            validation_total_candles=validation_total_candles,
            execution_model=_execution_model_payload(optimization),
        )
        run = db.get(Run, optimization.run_id)
        if run:
            run.status = "COMPLETED"
            run.ended_at = optimization.completed_at
        _persist_terminal_timings(
            db,
            optimization,
            timings=timings,
            started=started,
            succeeded=succeeded + validation_succeeded,
            failed=failed + validation_failed,
        )
    except Exception as exc:
        db.rollback()
        optimization = db.get(OptimizationRun, optimization_id)
        if optimization:
            optimization.status = "FAILED"
            optimization.error = str(exc)[:4000]
            optimization.completed_at = utc_now()
            optimization.summary = _terminal_summary_payload(
                db,
                optimization,
                completed_trials=succeeded + validation_succeeded,
                failed_trials=failed + validation_failed,
                strategy_completed_trials=succeeded,
                strategy_failed_trials=failed,
                validation_completed_trials=validation_succeeded,
                validation_failed_trials=validation_failed,
                duration_seconds=int(monotonic() - started),
                timings=_timings_payload(timings, started),
                search_period=search_period,
                validation_period=validation_period,
                search_space=search_space,
                fixed_config_grid=[],
                search_total_candles=search_total_candles,
                validation_total_candles=validation_total_candles,
                execution_model=_execution_model_payload(optimization),
            )
            run = db.get(Run, optimization.run_id)
            if run:
                run.status = "FAILED"
                run.ended_at = optimization.completed_at
            try:
                _persist_terminal_timings(
                    db,
                    optimization,
                    timings=timings,
                    started=started,
                    succeeded=succeeded + validation_succeeded,
                    failed=failed + validation_failed,
                )
            except Exception:
                db.rollback()
                logger.exception(
                    "optimization_failure_persist_failed optimization_id=%s",
                    optimization_id,
                )


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
