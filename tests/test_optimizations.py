import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient
from goldie_api.db import Base, SessionLocal, engine
from goldie_api.main import app
from goldie_api.models import OptimizationRun, OptimizationTrial
from goldie_api.optimizations import (
    OPTIMIZATION_COMMIT_INTERVAL,
    compute_balanced_score,
    execute_optimization,
    sample_parameters,
)


def test_optimization_progress_is_committed_after_every_trial() -> None:
    assert OPTIMIZATION_COMMIT_INTERVAL == 1


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def register_feed(client: TestClient, symbol: str, provider_symbol: str) -> dict:
    response = client.post(
        "/api/v1/market-feeds/register",
        headers={"X-Agent-Token": "test-agent-token"},
        json={
            "provider": "oanda",
            "environment": "practice",
            "canonical_symbol": symbol,
            "provider_symbol": provider_symbol,
            "agent_name": f"optimizer-{symbol.lower()}",
        },
    )
    assert response.status_code == 201
    return response.json()


def activate_first_config(client: TestClient, bot_id: str, headers: dict[str, str]) -> dict:
    versions = client.get(f"/api/v1/bots/{bot_id}/config-versions", headers=headers).json()
    if versions[0]["status"] != "ACTIVE":
        assert client.post(
            f"/api/v1/config-versions/{versions[0]['id']}/validate",
            headers=headers,
        ).status_code == 200
        assert client.post(
            f"/api/v1/config-versions/{versions[0]['id']}/activate",
            headers=headers,
        ).status_code == 200
        versions = client.get(f"/api/v1/bots/{bot_id}/config-versions", headers=headers).json()
    return versions[0]


def seed_market_data(client: TestClient, feed_id: str, agent_id: str) -> None:
    specification = client.post(
        f"/api/v1/market-feeds/{feed_id}/instrument-specification",
        headers={"X-Agent-Token": "test-agent-token"},
        json={
            "agent_id": agent_id,
            "canonical_symbol": "XAUUSD",
            "provider_symbol": "XAU_USD",
            "display_precision": 2,
            "pip_location": -1,
            "minimum_trade_size": "1",
            "trade_units_precision": 0,
            "margin_rate": "0.05",
            "provider_metadata": {},
        },
    )
    assert specification.status_code == 202
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        {
            "opened_at": (start + timedelta(minutes=index)).isoformat(),
            "open": str(Decimal("2300") + index * Decimal("0.2")),
            "high": str(Decimal("2300.2") + index * Decimal("0.2")),
            "low": str(Decimal("2299.9") + index * Decimal("0.2")),
            "close": str(Decimal("2300.15") + index * Decimal("0.2")),
            "volume": 100,
            "complete": True,
        }
        for index in range(400)
    ]
    stored = client.post(
        f"/api/v1/market-feeds/{feed_id}/candles/batch",
        headers={"X-Agent-Token": "test-agent-token"},
        json={"agent_id": agent_id, "candles": candles},
    )
    assert stored.status_code == 202


def test_compute_balanced_score_penalizes_drawdown_and_low_trade_count() -> None:
    summary = {"net_pnl": "120", "max_drawdown": "20", "total_trades": 2}
    assert compute_balanced_score(summary) == Decimal("-60")


def test_compute_balanced_score_rejects_candidate_without_trades() -> None:
    summary = {"net_pnl": "0", "max_drawdown": "0", "total_trades": 0}
    assert compute_balanced_score(summary) == Decimal("-99999")


class BoundaryTrial:
    def suggest_float(self, name: str, lower: float, upper: float) -> float:
        return upper if name == "buy_rsi_max" else lower

    def suggest_int(self, name: str, lower: int, upper: int) -> int:
        return upper if name in {"fast_ema_period", "medium_ema_period"} else lower


def test_sample_parameters_respects_dependent_strategy_bounds() -> None:
    sampled = sample_parameters(
        BoundaryTrial(),
        search_space=[
            {"name": "buy_rsi_max", "type": "number", "minimum": 0, "maximum": 100},
            {"name": "sell_rsi_min", "type": "number", "minimum": 0, "maximum": 100},
            {"name": "fast_ema_period", "type": "integer", "minimum": 2, "maximum": 20},
            {"name": "medium_ema_period", "type": "integer", "minimum": 3, "maximum": 30},
            {"name": "slow_ema_period", "type": "integer", "minimum": 4, "maximum": 40},
        ],
        defaults={},
    )

    assert sampled["buy_rsi_max"] <= sampled["sell_rsi_min"]
    assert (
        sampled["fast_ema_period"]
        < sampled["medium_ema_period"]
        < sampled["slow_ema_period"]
    )


def test_sample_parameters_respects_atr_bounds_regardless_of_catalog_order() -> None:
    sampled = sample_parameters(
        BoundaryTrial(),
        search_space=[
            {"name": "max_atr_points", "type": "number", "minimum": 1, "maximum": 100000},
            {"name": "min_atr_points", "type": "number", "minimum": 0, "maximum": 10000},
        ],
        defaults={"min_atr_points": "5", "max_atr_points": "500"},
    )

    assert sampled["min_atr_points"] <= sampled["max_atr_points"]


def test_optimization_api_and_execution_flow() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        registration = register_feed(client, "XAUUSD", "XAU_USD")
        feed_id = registration["feed"]["id"]
        agent_id = registration["agent"]["id"]
        headers = login(client)
        bot = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Optimization bot", "mode": "SHADOW", "market_feed_id": feed_id},
        ).json()
        config = activate_first_config(client, bot["id"], headers)
        seed_market_data(client, feed_id, agent_id)

        created = client.post(
            "/api/v1/optimizations",
            headers=headers,
            json={
                "bot_id": bot["id"],
                "config_version_id": config["id"],
                "market_feed_id": feed_id,
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-01-01T06:40:00Z",
                "n_trials": 3,
                "objective": "BALANCED",
                "initial_capital": "10000",
                "fill_mode": "simulated",
                "fee_maker": "0.001",
                "fee_taker": "0.001",
                "taker_slippage": "0.0004",
                "slippage_small": "0.0005",
                "medium_impact": "0.001",
                "impact_model": "sqrt",
                "model_sqrt_limit": "0.7",
                "limit_fill_timeout_s": 30,
                "min_qty_threshold": "0.01",
                "min_qty_check": True,
            },
        )
        assert created.status_code == 201
        created_body = created.json()
        assert created_body["fill_mode"] == "simulated"
        assert Decimal(str(created_body["taker_slippage"])) == Decimal("0.0004")
        assert Decimal(str(created_body["medium_impact"])) == Decimal("0.001")
        assert Decimal(str(created_body["model_sqrt_limit"])) == Decimal("0.7")
        assert Decimal(str(created_body["min_qty_threshold"])) == Decimal("0.01")
        optimization_id = UUID(created.json()["id"])

        with SessionLocal() as db:
            optimization = db.get(OptimizationRun, optimization_id)
            optimization.status = "RUNNING"
            db.commit()
            execute_optimization(db, optimization_id)

        detail = client.get(f"/api/v1/optimizations/{optimization_id}", headers=headers)
        trials = client.get(f"/api/v1/optimizations/{optimization_id}/trials", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["status"] == "SUCCEEDED"
        assert detail.json()["best_candidate"]["sampled_parameters"]
        assert detail.json()["summary"]["execution_model"]["fill_mode"] == "simulated"
        assert trials.status_code == 200
        assert trials.json()["total"] == 3
        trial_id = trials.json()["items"][0]["id"]
        trial_detail = client.get(
            f"/api/v1/optimizations/{optimization_id}/trials/{trial_id}",
            headers=headers,
        )
        assert trial_detail.status_code == 200
        assert trial_detail.json()["sampled_parameters"]
        assert "fill_mode" not in trial_detail.json()["sampled_parameters"]
        assert "taker_slippage" not in trial_detail.json()["sampled_parameters"]
        assert "medium_impact" not in trial_detail.json()["sampled_parameters"]
        assert trial_detail.json()["optimization_run_id"] == str(optimization_id)
        with SessionLocal() as db:
            stored_trials = db.query(OptimizationTrial).filter_by(
                optimization_run_id=optimization_id
            ).count()
            assert stored_trials == 3


def test_queued_optimization_can_be_cancelled() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        registration = register_feed(client, "XAUUSD", "XAU_USD")
        feed_id = registration["feed"]["id"]
        headers = login(client)
        bot = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Queued optimization bot", "mode": "SHADOW", "market_feed_id": feed_id},
        ).json()
        config = activate_first_config(client, bot["id"], headers)
        created = client.post(
            "/api/v1/optimizations",
            headers=headers,
            json={
                "bot_id": bot["id"],
                "config_version_id": config["id"],
                "market_feed_id": feed_id,
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-01-01T01:00:00Z",
                "n_trials": 2,
            },
        )
        assert created.status_code == 201
        cancelled = client.post(
            f"/api/v1/optimizations/{created.json()['id']}/cancel",
            headers=headers,
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"
