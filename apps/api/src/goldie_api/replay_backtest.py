import argparse
import json
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from .backtests import execute_backtest, utc_now
from .db import SessionLocal
from .models import BacktestExperiment, Run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a stored backtest from run_id or experiment_id.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id", type=uuid.UUID)
    group.add_argument("--experiment-id", type=uuid.UUID)
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the result JSON.",
    )
    return parser


def resolve_experiment(
    *,
    run_id: uuid.UUID | None,
    experiment_id: uuid.UUID | None,
) -> BacktestExperiment:
    with SessionLocal() as db:
        if experiment_id is not None:
            experiment = db.get(BacktestExperiment, experiment_id)
        else:
            experiment = db.scalar(
                select(BacktestExperiment).where(BacktestExperiment.run_id == run_id)
            )
        if experiment is None:
            identifier = experiment_id or run_id
            raise SystemExit(f"Backtest not found for identifier {identifier}")
        db.expunge(experiment)
        return experiment


def replay_experiment(experiment_id: uuid.UUID) -> dict[str, Any]:
    with SessionLocal() as db:
        experiment = db.get(BacktestExperiment, experiment_id)
        if experiment is None:
            raise SystemExit(f"Backtest experiment {experiment_id} not found")

        experiment.status = "RUNNING"
        experiment.started_at = utc_now()
        experiment.completed_at = None
        experiment.error = None
        experiment.progress = {"processed": 0, "total": 0}
        run = db.get(Run, experiment.run_id)
        if run is not None:
            run.status = "RUNNING"
            run.started_at = experiment.started_at
            run.ended_at = None
        db.commit()

        execute_backtest(db, experiment.id)

        db.refresh(experiment)
        return {
            "experiment_id": str(experiment.id),
            "run_id": str(experiment.run_id),
            "status": experiment.status,
            "error": experiment.error,
            "summary": experiment.summary,
            "reason_counts": experiment.reason_counts,
        }


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    experiment = resolve_experiment(
        run_id=args.run_id,
        experiment_id=args.experiment_id,
    )
    payload = replay_experiment(experiment.id)
    print(
        json.dumps(
            payload,
            default=_json_default,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if payload["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
