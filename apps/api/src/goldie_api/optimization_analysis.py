import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from statistics import mean, median, pstdev
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import OptimizationRun, OptimizationTrial

ANALYSIS_METRICS = (
    "score",
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
    "average_duration_seconds",
    "max_consecutive_losses",
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


def _statistics(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "minimum": min(values),
        "maximum": max(values),
        "standard_deviation": pstdev(values),
    }


def _trial_metric(trial: OptimizationTrial, name: str) -> float | None:
    if name == "score":
        return _number(trial.score)
    return _number((trial.summary or {}).get(name, (trial.metrics or {}).get(name)))


def _score_for_sorting(trial: OptimizationTrial) -> float:
    score = _number(trial.score)
    return score if score is not None else float("-inf")


def _phase_analysis(trials: list[OptimizationTrial]) -> dict[str, Any]:
    statuses = Counter(trial.status for trial in trials)
    succeeded = [trial for trial in trials if trial.status == "SUCCEEDED"]
    metric_statistics = {
        metric: stats
        for metric in ANALYSIS_METRICS
        if (stats := _statistics([
            value
            for trial in succeeded
            if (value := _trial_metric(trial, metric)) is not None
        ]))
    }
    return {
        "trial_count": len(trials),
        "status_counts": dict(sorted(statuses.items())),
        "success_rate_pct": len(succeeded) * 100 / len(trials) if trials else None,
        "metric_statistics": metric_statistics,
    }


def _parameter_analysis(trials: list[OptimizationTrial]) -> dict[str, Any]:
    values: dict[str, list[Any]] = defaultdict(list)
    for trial in trials:
        if trial.status != "SUCCEEDED":
            continue
        for name, value in (trial.sampled_parameters or {}).items():
            values[name].append(value)

    result: dict[str, Any] = {}
    for name, parameter_values in sorted(values.items()):
        numeric = [_number(value) for value in parameter_values]
        if all(value is not None for value in numeric):
            result[name] = {
                "type": "numeric",
                "unique_values": len(set(parameter_values)),
                "statistics": _statistics([value for value in numeric if value is not None]),
            }
        else:
            counts = Counter(str(value) for value in parameter_values)
            result[name] = {
                "type": "categorical",
                "unique_values": len(counts),
                "value_counts": dict(counts.most_common()),
            }
    return result


def _candidate_validation_analysis(trials: list[OptimizationTrial]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for trial in trials:
        if trial.status != "SUCCEEDED":
            continue
        key = json.dumps(trial.sampled_parameters or {}, sort_keys=True, separators=(",", ":"))
        group = groups.setdefault(
            key,
            {
                "sampled_parameters": trial.sampled_parameters or {},
                "search_trials": [],
                "validation_trials": [],
            },
        )
        group[
            "search_trials"
            if trial.phase == "STRATEGY_SEARCH"
            else "validation_trials"
        ].append(trial)

    output = []
    for group in groups.values():
        search_scores = [
            score
            for trial in group["search_trials"]
            if (score := _number(trial.score)) is not None
        ]
        validation_scores = [
            score
            for trial in group["validation_trials"]
            if (score := _number(trial.score)) is not None
        ]
        best_validation = max(
            group["validation_trials"],
            key=_score_for_sorting,
            default=None,
        )
        output.append(
            {
                "sampled_parameters": group["sampled_parameters"],
                "search_score_statistics": _statistics(search_scores),
                "validation_score_statistics": _statistics(validation_scores),
                "best_validation_config_overrides": (
                    best_validation.config_overrides if best_validation else None
                ),
                "best_validation_summary": best_validation.summary if best_validation else None,
            }
        )
    return sorted(
        output,
        key=lambda item: (
            (item["validation_score_statistics"] or {}).get("maximum", float("-inf"))
        ),
        reverse=True,
    )


def build_optimization_export(
    db: Session,
    optimization: OptimizationRun,
) -> dict[str, Any]:
    trials = list(
        db.scalars(
            select(OptimizationTrial)
            .where(OptimizationTrial.optimization_run_id == optimization.id)
            .order_by(OptimizationTrial.phase.asc(), OptimizationTrial.trial_number.asc())
        )
    )
    phases = {
        phase: [trial for trial in trials if trial.phase == phase]
        for phase in ("STRATEGY_SEARCH", "FIXED_CONFIG_VALIDATION")
    }
    trial_payloads = [
        {
            "id": trial.id,
            "trial_number": trial.trial_number,
            "phase": trial.phase,
            "status": trial.status,
            "sampled_parameters": trial.sampled_parameters,
            "config_overrides": trial.config_overrides,
            "score": trial.score,
            "metrics": trial.metrics,
            "summary": trial.summary,
            "error": trial.error,
            "started_at": trial.started_at,
            "completed_at": trial.completed_at,
        }
        for trial in trials
    ]
    return jsonable_encoder(
        {
            "schema_version": "goldie.optimization-results.v2",
            "exported_at": datetime.now(UTC),
            "optimization": {
                "id": optimization.id,
                "status": optimization.status,
                "bot_id": optimization.bot_id,
                "config_version_id": optimization.config_version_id,
                "market_feed_id": optimization.market_feed_id,
                "run_id": optimization.run_id,
                "date_from": optimization.date_from,
                "date_to": optimization.date_to,
                "n_trials": optimization.n_trials,
                "objective": optimization.objective,
                "initial_capital": optimization.initial_capital,
                "config_snapshot": optimization.config_snapshot,
                "execution_model": {
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
                },
                "progress": optimization.progress,
                "best_candidate": optimization.best_candidate,
                "run_summary": optimization.summary,
                "error": optimization.error,
                "started_at": optimization.started_at,
                "completed_at": optimization.completed_at,
                "created_at": optimization.created_at,
            },
            "analysis": {
                "phases": {
                    phase: _phase_analysis(phase_trials)
                    for phase, phase_trials in phases.items()
                },
                "parameter_distributions": _parameter_analysis(
                    phases["STRATEGY_SEARCH"]
                ),
                "candidate_validation": _candidate_validation_analysis(trials),
                "parameter_insights": (optimization.summary or {}).get(
                    "parameter_insights",
                    {},
                ),
                "robustness": (optimization.summary or {}).get("robustness", {}),
                "research_quality_gates": (optimization.summary or {}).get(
                    "research_quality_gates",
                    {},
                ),
                "data_profile": (optimization.summary or {}).get("data_profile", {}),
                "decision_context": (optimization.summary or {}).get(
                    "decision_context",
                    {},
                ),
            },
            "trials": trial_payloads,
        }
    )
