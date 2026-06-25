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
from .services import as_utc

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

MIN_VALIDATION_TRADES_WARN = 30
MIN_VALIDATION_TRADES_BLOCK = 10
DEGRADATION_WARN_PCT = 35
DEGRADATION_BLOCK_PCT = 75
FAILED_TRIAL_WARN_RATIO = 0.25
FAILED_TRIAL_BLOCK_RATIO = 0.50
MIN_VALIDATED_CANDIDATES_WARN = 5
MIN_VALIDATED_CANDIDATES_BLOCK = 3
DRAWDOWN_WARN_PCT = 10
DRAWDOWN_BLOCK_PCT = 20
CONSECUTIVE_LOSSES_WARN = 5
CONSECUTIVE_LOSSES_BLOCK = 8
GAP_SAMPLE_LIMIT = 10


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
            "note": (
                "Full MFE/MAE values are available in persisted backtest trades, "
                "but optimization trials store compact summaries only."
            ),
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


def _oanda_market_is_closed(value: datetime) -> bool:
    timestamp = as_utc(value)
    weekday = timestamp.weekday()
    return weekday == 5 or (weekday == 4 and timestamp.hour >= 22) or (
        weekday == 6 and timestamp.hour < 22
    )


def _is_expected_market_closure(value: datetime, feed: MarketFeed | None) -> bool:
    if feed is None or feed.provider != "oanda":
        return False
    return _oanda_market_is_closed(value)


def _gap_breakdown(
    previous: datetime,
    current: datetime,
    *,
    feed: MarketFeed | None,
) -> dict[str, Any] | None:
    previous = as_utc(previous)
    current = as_utc(current)
    total_minutes = int((current - previous).total_seconds() // 60)
    missing_minutes = max(0, total_minutes - 1)
    if missing_minutes == 0:
        return None

    market_closed_minutes = 0
    unexpected_minutes = 0
    missing_at = previous + timedelta(minutes=1)
    while missing_at < current:
        if _is_expected_market_closure(missing_at, feed):
            market_closed_minutes += 1
        else:
            unexpected_minutes += 1
        missing_at += timedelta(minutes=1)

    return {
        "from": previous + timedelta(minutes=1),
        "to": current - timedelta(minutes=1),
        "missing_minutes": missing_minutes,
        "unexpected_missing_minutes": unexpected_minutes,
        "market_closed_missing_minutes": market_closed_minutes,
    }


def _summarize_m1_gaps(
    ordered_times: list[datetime],
    *,
    feed: MarketFeed | None,
) -> dict[str, Any]:
    raw_gap_count = 0
    raw_missing_minutes = 0
    unexpected_gap_count = 0
    unexpected_missing_minutes = 0
    market_closed_gap_count = 0
    market_closed_missing_minutes = 0
    unexpected_examples = []
    market_closed_examples = []

    for previous, current in zip(ordered_times, ordered_times[1:], strict=False):
        gap = _gap_breakdown(previous, current, feed=feed)
        if gap is None:
            continue

        raw_gap_count += 1
        raw_missing_minutes += int(gap["missing_minutes"])

        if gap["unexpected_missing_minutes"]:
            unexpected_gap_count += 1
            unexpected_missing_minutes += int(gap["unexpected_missing_minutes"])
            if len(unexpected_examples) < GAP_SAMPLE_LIMIT:
                unexpected_examples.append(gap)

        if gap["market_closed_missing_minutes"]:
            market_closed_gap_count += 1
            market_closed_missing_minutes += int(gap["market_closed_missing_minutes"])
            if len(market_closed_examples) < GAP_SAMPLE_LIMIT:
                market_closed_examples.append(gap)

    return {
        "raw_m1_gap_count": raw_gap_count,
        "raw_m1_missing_minutes": raw_missing_minutes,
        "detected_m1_gap_count": unexpected_gap_count,
        "detected_m1_missing_minutes": unexpected_missing_minutes,
        "market_closed_m1_gap_count": market_closed_gap_count,
        "market_closed_m1_missing_minutes": market_closed_missing_minutes,
        "gap_examples": unexpected_examples,
        "market_closed_gap_examples": market_closed_examples,
    }


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
    feed = db.get(MarketFeed, optimization.market_feed_id)
    gap_summary = _summarize_m1_gaps(ordered_times, feed=feed)
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
            "gap_detection_policy": (
                "OANDA weekend market-closed minutes are reported separately and "
                "excluded from detected_m1_gap_count."
                if feed and feed.provider == "oanda"
                else "Calendar M1 continuity; no provider market-closed calendar was applied."
            ),
            **gap_summary,
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
            for value, score in zip(numeric_values, scores, strict=False)
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


def _gate(
    gate_id: str,
    status: str,
    severity: str,
    message: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "status": status,
        "severity": severity,
        "message": message,
        "evidence": evidence,
    }


def _gate_status(gates: list[dict[str, Any]]) -> str:
    if any(gate["status"] == "BLOCK" for gate in gates):
        return "BLOCK"
    if any(gate["status"] == "WARN" for gate in gates):
        return "WARN"
    return "PASS"


def _quality_recommendation(overall_status: str) -> str:
    if overall_status == "PASS":
        return (
            "Research gates passed for V1 review. Candidate can be considered for "
            "shadow validation, while still requiring forward monitoring."
        )
    if overall_status == "WARN":
        return (
            "Research gates produced warnings. Treat the candidate as investigational "
            "and review the warning evidence before applying it."
        )
    return (
        "Research gates block promotion. Do not treat this candidate as robust until "
        "the blocked evidence is resolved with a cleaner or broader run."
    )


def _best_validation_metrics(robustness: dict[str, Any]) -> dict[str, Any]:
    candidates = robustness.get("best_validation_candidates") or []
    if not candidates:
        return {}
    return candidates[0].get("validation_metrics") or {}


def build_research_quality_gates(
    trials: list[OptimizationTrial],
    *,
    data_profile: dict[str, Any],
    robustness: dict[str, Any],
) -> dict[str, Any]:
    succeeded = _successful_trials(trials)
    validation_trials = [
        trial for trial in succeeded if trial.phase == "FIXED_CONFIG_VALIDATION"
    ]
    total_trials = len(trials)
    failed_trials = len([trial for trial in trials if trial.status == "FAILED"])
    failed_ratio = failed_trials / total_trials if total_trials else 0
    validation_trade_counts = [
        value
        for trial in validation_trials
        if (value := _number((trial.summary or {}).get("total_trades"))) is not None
    ]
    validation_trades = int(sum(validation_trade_counts))
    average_degradation = _number(robustness.get("average_score_degradation_pct"))
    validated_candidate_count = int(robustness.get("validated_candidate_count") or 0)
    stable_candidate_count = len(robustness.get("stable_candidates") or [])
    best_metrics = _best_validation_metrics(robustness)
    drawdown_pct = _number(best_metrics.get("max_drawdown_pct"))
    consecutive_losses = _number(best_metrics.get("max_consecutive_losses"))

    gates: list[dict[str, Any]] = []
    if validation_trades < MIN_VALIDATION_TRADES_BLOCK:
        gates.append(
            _gate(
                "validation_trade_sample",
                "BLOCK",
                "HIGH",
                "Validation sample is too small for a V1 promotion decision.",
                {
                    "validation_trades": validation_trades,
                    "minimum_required": MIN_VALIDATION_TRADES_BLOCK,
                    "warning_threshold": MIN_VALIDATION_TRADES_WARN,
                },
            )
        )
    elif validation_trades < MIN_VALIDATION_TRADES_WARN:
        gates.append(
            _gate(
                "validation_trade_sample",
                "WARN",
                "MEDIUM",
                "Validation sample is thin; conclusions may be unstable.",
                {
                    "validation_trades": validation_trades,
                    "warning_threshold": MIN_VALIDATION_TRADES_WARN,
                },
            )
        )
    else:
        gates.append(
            _gate(
                "validation_trade_sample",
                "PASS",
                "INFO",
                "Validation sample has enough trades for a first V1 review.",
                {"validation_trades": validation_trades},
            )
        )

    if average_degradation is None:
        gates.append(
            _gate(
                "search_validation_degradation",
                "WARN",
                "MEDIUM",
                "Search-to-validation degradation could not be calculated.",
                {"average_score_degradation_pct": None},
            )
        )
    elif average_degradation > DEGRADATION_BLOCK_PCT:
        gates.append(
            _gate(
                "search_validation_degradation",
                "BLOCK",
                "HIGH",
                "Validation score degraded heavily versus search.",
                {
                    "average_score_degradation_pct": average_degradation,
                    "block_threshold_pct": DEGRADATION_BLOCK_PCT,
                },
            )
        )
    elif average_degradation > DEGRADATION_WARN_PCT:
        gates.append(
            _gate(
                "search_validation_degradation",
                "WARN",
                "MEDIUM",
                "Validation score degraded materially versus search.",
                {
                    "average_score_degradation_pct": average_degradation,
                    "warning_threshold_pct": DEGRADATION_WARN_PCT,
                },
            )
        )
    else:
        gates.append(
            _gate(
                "search_validation_degradation",
                "PASS",
                "INFO",
                "Search-to-validation degradation is within the V1 tolerance.",
                {"average_score_degradation_pct": average_degradation},
            )
        )

    gap_count = int(data_profile.get("detected_m1_gap_count") or 0)
    missing_minutes = int(data_profile.get("detected_m1_missing_minutes") or 0)
    incomplete_count = int(data_profile.get("incomplete_candles") or 0)
    if gap_count > 0 or incomplete_count > 0:
        gates.append(
            _gate(
                "data_quality",
                "WARN",
                "MEDIUM",
                "Input candles contain unexpected M1 gaps or incomplete records.",
                {
                    "detected_m1_gap_count": gap_count,
                    "detected_m1_missing_minutes": missing_minutes,
                    "incomplete_candles": incomplete_count,
                    "market_closed_m1_gap_count": int(
                        data_profile.get("market_closed_m1_gap_count") or 0
                    ),
                    "market_closed_m1_missing_minutes": int(
                        data_profile.get("market_closed_m1_missing_minutes") or 0
                    ),
                },
            )
        )
    else:
        gates.append(
            _gate(
                "data_quality",
                "PASS",
                "INFO",
                "No unexpected M1 gaps or incomplete candles were detected in the run window.",
                {
                    "detected_m1_gap_count": gap_count,
                    "detected_m1_missing_minutes": missing_minutes,
                    "incomplete_candles": incomplete_count,
                    "market_closed_m1_gap_count": int(
                        data_profile.get("market_closed_m1_gap_count") or 0
                    ),
                    "market_closed_m1_missing_minutes": int(
                        data_profile.get("market_closed_m1_missing_minutes") or 0
                    ),
                },
            )
        )

    if failed_ratio > FAILED_TRIAL_BLOCK_RATIO:
        status, severity, message = (
            "BLOCK",
            "HIGH",
            "Too many optimization trials failed.",
        )
    elif failed_ratio > FAILED_TRIAL_WARN_RATIO:
        status, severity, message = (
            "WARN",
            "MEDIUM",
            "Optimization had an elevated failed-trial rate.",
        )
    else:
        status, severity, message = (
            "PASS",
            "INFO",
            "Failed-trial rate is within the V1 tolerance.",
        )
    gates.append(
        _gate(
            "failed_trial_rate",
            status,
            severity,
            message,
            {
                "failed_trials": failed_trials,
                "total_trials": total_trials,
                "failed_ratio": failed_ratio,
            },
        )
    )

    if validated_candidate_count < MIN_VALIDATED_CANDIDATES_BLOCK:
        gates.append(
            _gate(
                "validation_robustness",
                "BLOCK",
                "HIGH",
                "Too few validated candidates exist to judge robustness.",
                {
                    "validated_candidate_count": validated_candidate_count,
                    "stable_candidate_count": stable_candidate_count,
                    "minimum_required": MIN_VALIDATED_CANDIDATES_BLOCK,
                },
            )
        )
    elif validated_candidate_count < MIN_VALIDATED_CANDIDATES_WARN:
        gates.append(
            _gate(
                "validation_robustness",
                "WARN",
                "MEDIUM",
                "Validated candidate coverage is narrow.",
                {
                    "validated_candidate_count": validated_candidate_count,
                    "stable_candidate_count": stable_candidate_count,
                    "warning_threshold": MIN_VALIDATED_CANDIDATES_WARN,
                },
            )
        )
    else:
        gates.append(
            _gate(
                "validation_robustness",
                "PASS",
                "INFO",
                "Validated candidate coverage is broad enough for V1 review.",
                {
                    "validated_candidate_count": validated_candidate_count,
                    "stable_candidate_count": stable_candidate_count,
                },
            )
        )

    risk_status = "PASS"
    risk_severity = "INFO"
    risk_message = "Drawdown and consecutive-loss risk are within V1 tolerance."
    if (
        (drawdown_pct is not None and drawdown_pct > DRAWDOWN_BLOCK_PCT)
        or (
            consecutive_losses is not None
            and consecutive_losses > CONSECUTIVE_LOSSES_BLOCK
        )
    ):
        risk_status = "BLOCK"
        risk_severity = "HIGH"
        risk_message = "Best validation candidate breaches V1 risk limits."
    elif (
        (drawdown_pct is not None and drawdown_pct > DRAWDOWN_WARN_PCT)
        or (
            consecutive_losses is not None
            and consecutive_losses > CONSECUTIVE_LOSSES_WARN
        )
    ):
        risk_status = "WARN"
        risk_severity = "MEDIUM"
        risk_message = "Best validation candidate is close to V1 risk limits."
    gates.append(
        _gate(
            "risk_profile",
            risk_status,
            risk_severity,
            risk_message,
            {
                "max_drawdown_pct": drawdown_pct,
                "max_consecutive_losses": consecutive_losses,
                "drawdown_warn_pct": DRAWDOWN_WARN_PCT,
                "drawdown_block_pct": DRAWDOWN_BLOCK_PCT,
                "consecutive_losses_warn": CONSECUTIVE_LOSSES_WARN,
                "consecutive_losses_block": CONSECUTIVE_LOSSES_BLOCK,
            },
        )
    )

    overall_status = _gate_status(gates)
    return jsonable_encoder(
        {
            "overall_status": overall_status,
            "gates": gates,
            "recommendation": _quality_recommendation(overall_status),
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
    data_profile = build_data_profile(
        db,
        optimization,
        search_period=search_period,
        validation_period=validation_period,
        search_total_candles=search_total_candles,
        validation_total_candles=validation_total_candles,
    )
    robustness = build_robustness(trials)
    return {
        "data_profile": data_profile,
        "robustness": robustness,
        "parameter_insights": build_parameter_insights(trials),
        "research_quality_gates": build_research_quality_gates(
            trials,
            data_profile=data_profile,
            robustness=robustness,
        ),
        "decision_context": jsonable_encoder(
            {
                "search_space": search_space,
                "fixed_config_grid": fixed_config_grid or [],
                "objective": optimization.objective,
                "objective_formula": (
                    "BALANCED = net_pnl - 1.5 * max_drawdown - "
                    "50 * missing_trades_below_30; no-trade trials score -99999"
                ),
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
                "research_quality_gates": summary.get("research_quality_gates", {}),
                "progress": optimization.progress,
                "error": optimization.error,
            },
            "top_trials": [compact_trial(trial) for trial in ranked[:10]],
            "worst_trials": [compact_trial(trial) for trial in worst],
            "validation_winners": [compact_trial(trial) for trial in validation],
            "parameter_insights": summary.get("parameter_insights", {}),
            "robustness": summary.get("robustness", {}),
            "research_quality_gates": summary.get("research_quality_gates", {}),
            "data_quality_notes": {
                "detected_m1_gap_count": data_profile.get("detected_m1_gap_count"),
                "incomplete_candles": data_profile.get("incomplete_candles"),
                "search_candles": data_profile.get("search_candles"),
                "validation_candles": data_profile.get("validation_candles"),
            },
        }
    )
