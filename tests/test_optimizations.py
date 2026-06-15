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
from goldie_api.optimizations import compute_balanced_score, execute_optimization


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
    assert compute_balanced_score(summary) == Decimal("20")


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
                "fee_maker": "0.001",
                "fee_taker": "0.001",
                "slippage_small": "0.0005",
                "slippage_medium": "0.001",
                "impact_model": "sqrt",
                "limit_fill_timeout_s": 30,
                "min_qty_check": True,
            },
        )
        assert created.status_code == 201
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
        assert trials.status_code == 200
        assert trials.json()["total"] == 3
        trial_id = trials.json()["items"][0]["id"]
        trial_detail = client.get(
            f"/api/v1/optimizations/{optimization_id}/trials/{trial_id}",
            headers=headers,
        )
        assert trial_detail.status_code == 200
        assert trial_detail.json()["sampled_parameters"]
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
