import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Candle, MarketFeed, OptimizationRun, OptimizationTrial

CORE_TRIAL_METRICS = (
    "net_pnl",
    "return_pct",
    "max_drawdown",
    "max_drawdown_pct",
    "total_trades",
    "win_rate",
    "profit_factor",
    "expectancy",
    "expectancy_r",
    "total_r",
    "trade_sharpe",
    "trade_sortino",
    "commission",
    "max_consecutive_losses",
    "average_duration_seconds",
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score(value: Any) -> float:
    number = _number(value)
    return number if number is not None else float("-inf")


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _range(values: list[float]) -> dict[str, float | None]:
    return {
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
        "average": _average(values),
        "p25": _percentile(values, 0.25),
        "p50": _percentile(values, 0.50),
        "p75": _percentile(values, 0.75),
    }


def build_backtest_diagnostics(
    summary: dict[str, Any],
    reason_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    direction_breakdown = summary.get("direction_breakdown") or {}
    close_reason_counts = summary.get("close_reason_counts") or {}
    r_values: list[float] = []
    for key in ("expectancy_r", "total_r"):
        value = _number(summary.get(key))
        if value is not None:
            r_values.append(value)
    diagnostics = {
        "direction_breakdown": direction_breakdown,
        "close_reason_counts": close_reason_counts,
        "reason_counts": reason_counts or {},
        "trade_quality": {
            "expectancy_r": summary.get("expectancy_r"),
            "total_r": summary.get("total_r"),
            "trade_sharpe": summary.get("trade_sharpe"),
            "trade_sortino": summary.get("trade_sortino"),
            "max_consecutive_losses": summary.get("max_consecutive_losses"),
            "average_duration_seconds": summary.get("average_duration_seconds"),
        },
        "risk": {
            "max_drawdown": summary.get("max_drawdown"),
            "max_drawdown_pct": summary.get("max_drawdown_pct"),
            "profit_factor": summary.get("profit_factor"),
            "win_rate": summary.get("win_rate"),
        },
        "r_multiple_summary": {
            "average": summary.get("expectancy_r"),
            "total": summary.get("total_r"),
            "known_values": r_values,
        },
        "mfe_mae_summary": {
            "source": "not_persisted_for_optimization_trials",
            "note": "Full MFE/MAE values are available in persisted backtest trades, but optimization trials store compact summaries only.",
        },
        "duration_summary": {
            "average_seconds": summary.get("average_duration_seconds"),
        },
    }
    return jsonable_encoder(diagnostics)


def build_trial_metrics(
    summary: dict[str, Any],
    *,
    timings: dict[str, float],
    reason_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    metrics = {name: summary.get(name) for name in CORE_TRIAL_METRICS}
    metrics["timings"] = timings
    metrics["diagnostics"] = build_backtest_diagnostics(summary, reason_counts)
    return jsonable_encoder(metrics)


def build_data_profile(
    db: Session,
    optimization: OptimizationRun,
    *,
    search_period: tuple[datetime, datetime] | None,
    validation_period: tuple[datetime, datetime] | None,
    search_total_candles: int,
    validation_total_candles: int,
) -> dict[str, Any]:
    base_filter = (
        Candle.market_feed_id == optimization.market_feed_id,
        Candle.timeframe == "M1",
    )
    incomplete_count = db.scalar(
        select(func.count(Candle.id)).where(
            *base_filter,
            Candle.opened_at >= optimization.date_from,
            Candle.opened_at < optimization.date_to,
            Candle.is_complete.is_(False),
        )
    ) or 0
    ordered_times = list(
        db.scalars(
            select(Candle.opened_at)
            .where(
                *base_filter,
                Candle.opened_at >= optimization.date_from,
                Candle.opened_at < optimization.date_to,
                Candle.is_complete.is_(True),
            )
            .order_by(Candle.opened_at)
        )
    )
    expected_step = timedelta(minutes=1)
    gap_count = sum(
        1
        for previous, current in zip(ordered_times, ordered_times[1:])
        if current - previous > expected_step
    )
    feed = db.get(MarketFeed, optimization.market_feed_id)
    return jsonable_encoder(
        {
            "market_feed_id": optimization.market_feed_id,
            "symbol": feed.canonical_symbol if feed else None,
            "provider_symbol": feed.provider_symbol if feed else None,
            "timeframe": "M1",
            "date_from": optimization.date_from,
            "date_to": optimization.date_to,
            "search_period": (
                {"date_from": search_period[0], "date_to": search_period[1]}
                if search_period
                else None
            ),
            "validation_period": (
                {"date_from": validation_period[0], "date_to": validation_period[1]}
                if validation_period
                else None
            ),
            "search_candles": search_total_candles,
            "validation_candles": validation_total_candles,
            "complete_candles": len(ordered_times),
            "incomplete_candles": incomplete_count,
            "detected_m1_gap_count": gap_count,
        }
    )


def _successful_trials(trials: list[OptimizationTrial]) -> list[OptimizationTrial]:
    return [trial for trial in trials if trial.status == "SUCCEEDED"]


def build_parameter_insights(trials: list[OptimizationTrial]) -> dict[str, Any]:
    succeeded = _successful_trials(
        [trial for trial in trials if trial.phase == "STRATEGY_SEARCH"]
    )
    if not succeeded:
        return {"top_decile": {}, "bottom_decile": {}, "numeric_score_correlation": {}}
    ranked = sorted(succeeded, key=lambda trial: _score(trial.score), reverse=True)
    bucket_size = max(1, math.ceil(len(ranked) * 0.10))
    top = ranked[:bucket_size]
    bottom = ranked[-bucket_size:]

    def summarize_bucket(bucket: list[OptimizationTrial]) -> dict[str, Any]:
        values: dict[str, list[Any]] = defaultdict(list)
        for trial in bucket:
            for name, value in (trial.sampled_parameters or {}).items():
                values[name].append(value)
        result: dict[str, Any] = {}
        for name, parameter_values in sorted(values.items()):
            numeric = [_number(value) for value in parameter_values]
            if all(value is not None for value in numeric):
                result[name] = {
                    "type": "numeric",
                    "range": _range([value for value in numeric if value is not None]),
                }
            else:
                result[name] = {
                    "type": "categorical",
                    "value_counts": dict(Counter(str(value) for value in parameter_values)),
                }
        return result

    correlations: dict[str, float] = {}
    parameter_names = sorted(
        {
            name
            for trial in succeeded
            for name in (trial.sampled_parameters or {}).keys()
        }
    )
    scores = [_score(trial.score) for trial in succeeded]
    mean_score = _average(scores)
    for name in parameter_names:
        values = [_number((trial.sampled_parameters or {}).get(name)) for trial in succeeded]
        if not values or any(value is None for value in values):
            continue
        numeric_values = [value for value in values if value is not None]
        mean_value = _average(numeric_values)
        if mean_value is None or mean_score is None:
            continue
        value_variance = sum((value - mean_value) ** 2 for value in numeric_values)
        score_variance = sum((score - mean_score) ** 2 for score in scores)
        if value_variance == 0 or score_variance == 0:
            continue
        covariance = sum(
            (value - mean_value) * (score - mean_score)
            for value, score in zip(numeric_values, scores)
        )
        correlations[name] = covariance / math.sqrt(value_variance * score_variance)

    return jsonable_encoder(
        {
            "top_decile": summarize_bucket(top),
            "bottom_decile": summarize_bucket(bottom),
            "numeric_score_correlation": correlations,
        }
    )


def build_robustness(trials: list[OptimizationTrial]) -> dict[str, Any]:
    search_by_parameters: dict[str, OptimizationTrial] = {}
    for trial in _successful_trials(trials):
        if trial.phase != "STRATEGY_SEARCH":
            continue
        key = json.dumps(
            jsonable_encoder(trial.sampled_parameters or {}),
            sort_keys=True,
            separators=(",", ":"),
        )
        search_by_parameters[key] = trial

    candidates = []
    for trial in _successful_trials(trials):
        if trial.phase != "FIXED_CONFIG_VALIDATION":
            continue
        key = json.dumps(
            jsonable_encoder(trial.sampled_parameters or {}),
            sort_keys=True,
            separators=(",", ":"),
        )
        search_trial = search_by_parameters.get(key)
        search_score = _number(search_trial.score if search_trial else None)
        validation_score = _number(trial.score)
        degradation = (
            search_score - validation_score
            if search_score is not None and validation_score is not None
            else None
        )
        degradation_pct = (
            degradation * 100 / abs(search_score)
            if degradation is not None and search_score not in (None, 0)
            else None
        )
        candidates.append(
            {
                "trial_number": trial.trial_number,
                "search_trial_number": search_trial.trial_number if search_trial else None,
                "sampled_parameters": trial.sampled_parameters,
                "config_overrides": trial.config_overrides,
                "search_score": search_score,
                "validation_score": validation_score,
                "score_degradation": degradation,
                "score_degradation_pct": degradation_pct,
                "validation_metrics": trial.metrics,
            }
        )
    stable = sorted(
        candidates,
        key=lambda item: (
            abs(item["score_degradation"] or 0),
            -_score(item["validation_score"]),
        ),
    )[:5]
    best_validation = sorted(
        candidates,
        key=lambda item: _score(item["validation_score"]),
        reverse=True,
    )[:5]
    degradations = [
        item["score_degradation_pct"]
        for item in candidates
        if item["score_degradation_pct"] is not None
    ]
    return jsonable_encoder(
        {
            "validated_candidate_count": len(candidates),
            "average_score_degradation_pct": _average(degradations),
            "stable_candidates": stable,
            "best_validation_candidates": best_validation,
        }
    )


def build_run_decision_sections(
    db: Session,
    optimization: OptimizationRun,
    *,
    search_period: tuple[datetime, datetime] | None,
    validation_period: tuple[datetime, datetime] | None,
    search_total_candles: int,
    validation_total_candles: int,
    search_space: list[dict[str, Any]],
    fixed_config_grid: list[dict[str, Any]] | None,
    execution_model: dict[str, Any],
) -> dict[str, Any]:
    trials = list(
        db.scalars(
            select(OptimizationTrial)
            .where(OptimizationTrial.optimization_run_id == optimization.id)
            .order_by(OptimizationTrial.phase.asc(), OptimizationTrial.trial_number.asc())
        )
    )
    return {
        "data_profile": build_data_profile(
            db,
            optimization,
            search_period=search_period,
            validation_period=validation_period,
            search_total_candles=search_total_candles,
            validation_total_candles=validation_total_candles,
        ),
        "robustness": build_robustness(trials),
        "parameter_insights": build_parameter_insights(trials),
        "decision_context": jsonable_encoder(
            {
                "search_space": search_space,
                "fixed_config_grid": fixed_config_grid or [],
                "objective": optimization.objective,
                "objective_formula": "BALANCED = net_pnl - 1.5 * max_drawdown - 50 * missing_trades_below_5; no-trade trials score -99999",
                "execution_model": execution_model,
            }
        ),
    }


def build_llm_context(db: Session, optimization: OptimizationRun) -> dict[str, Any]:
    trials = list(
        db.scalars(
            select(OptimizationTrial)
            .where(OptimizationTrial.optimization_run_id == optimization.id)
            .order_by(OptimizationTrial.phase.asc(), OptimizationTrial.trial_number.asc())
        )
    )
    succeeded = _successful_trials(trials)
    ranked = sorted(succeeded, key=lambda trial: _score(trial.score), reverse=True)
    worst = sorted(succeeded, key=lambda trial: _score(trial.score))[:10]
    validation = [
        trial for trial in ranked if trial.phase == "FIXED_CONFIG_VALIDATION"
    ][:10]

    def compact_trial(trial: OptimizationTrial) -> dict[str, Any]:
        metrics = trial.metrics or {}
        return {
            "trial_number": trial.trial_number,
            "phase": trial.phase,
            "score": trial.score,
            "sampled_parameters": trial.sampled_parameters,
            "config_overrides": trial.config_overrides,
            "metrics": {
                key: metrics.get(key)
                for key in (
                    "net_pnl",
                    "return_pct",
                    "max_drawdown",
                    "max_drawdown_pct",
                    "total_trades",
                    "win_rate",
                    "profit_factor",
                    "expectancy_r",
                    "trade_sortino",
                    "max_consecutive_losses",
                )
            },
            "diagnostics": metrics.get("diagnostics", {}),
        }

    summary = optimization.summary or {}
    data_profile = summary.get("data_profile") or {}
    return jsonable_encoder(
        {
            "schema_version": "goldie.optimization-llm-context.v1",
            "optimization": {
                "id": optimization.id,
                "status": optimization.status,
                "objective": optimization.objective,
                "date_from": optimization.date_from,
                "date_to": optimization.date_to,
                "n_trials": optimization.n_trials,
                "best_candidate": optimization.best_candidate,
            },
            "run_context": {
                "data_profile": data_profile,
                "decision_context": summary.get("decision_context", {}),
                "progress": optimization.progress,
                "error": optimization.error,
            },
            "top_trials": [compact_trial(trial) for trial in ranked[:10]],
            "worst_trials": [compact_trial(trial) for trial in worst],
            "validation_winners": [compact_trial(trial) for trial in validation],
            "parameter_insights": summary.get("parameter_insights", {}),
            "robustness": summary.get("robustness", {}),
            "data_quality_notes": {
                "detected_m1_gap_count": data_profile.get("detected_m1_gap_count"),
                "incomplete_candles": data_profile.get("incomplete_candles"),
                "search_candles": data_profile.get("search_candles"),
                "validation_candles": data_profile.get("validation_candles"),
            },
        }
    )
