import json
import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from goldie_api.db import Base, SessionLocal, engine
from goldie_api.main import app
from goldie_api.models import BacktestExperiment, BacktestTrade
from goldie_api.replay_backtest import main


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def activate_first_config(client: TestClient, bot_id: str, headers: dict[str, str]) -> None:
    versions = client.get(
        f"/api/v1/bots/{bot_id}/config-versions",
        headers=headers,
    ).json()
    if versions[0]["status"] == "ACTIVE":
        return
    validated = client.post(
        f"/api/v1/config-versions/{versions[0]['id']}/validate",
        headers=headers,
    )
    assert validated.status_code == 200
    activated = client.post(
        f"/api/v1/config-versions/{versions[0]['id']}/activate",
        headers=headers,
    )
    assert activated.status_code == 200


def test_replay_backtest_command_recreates_experiment_from_run_id(
    capsys,
) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    agent_headers = {"X-Agent-Token": "test-agent-token"}

    with TestClient(app) as client:
        registration = client.post(
            "/api/v1/market-feeds/register",
            headers=agent_headers,
            json={
                "provider": "oanda",
                "environment": "practice",
                "canonical_symbol": "XAUUSD",
                "provider_symbol": "XAU_USD",
                "agent_name": "replay-agent",
            },
        )
        assert registration.status_code == 201
        feed = registration.json()["feed"]
        agent = registration.json()["agent"]

        headers = login(client)
        bot = client.post(
            "/api/v1/bots",
            headers=headers,
            json={
                "name": "Replay bot",
                "mode": "SHADOW",
                "market_feed_id": feed["id"],
            },
        )
        assert bot.status_code == 201
        bot_id = bot.json()["id"]
        activate_first_config(client, bot_id, headers)
        config = client.get(
            f"/api/v1/bots/{bot_id}/config-versions",
            headers=headers,
        ).json()[0]

        specification = client.post(
            f"/api/v1/market-feeds/{feed['id']}/instrument-specification",
            headers=agent_headers,
            json={
                "agent_id": agent["id"],
                "canonical_symbol": "XAUUSD",
                "provider_symbol": "XAU_USD",
                "display_precision": 2,
                "pip_location": -1,
                "minimum_trade_size": "1",
                "trade_units_precision": 0,
                "margin_rate": "0.05",
                "provider_metadata": {"type": "METAL"},
            },
        )
        assert specification.status_code == 202

        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        candle_count = 200
        candles = [
            {
                "opened_at": (start + timedelta(minutes=index)).isoformat(),
                "open": str(2300 + index),
                "high": str(2301.5 + index),
                "low": str(2299.5 + index),
                "close": str(2301 + index),
                "volume": 100,
                "complete": True,
            }
            for index in range(candle_count)
        ]
        stored = client.post(
            f"/api/v1/market-feeds/{feed['id']}/candles/batch",
            headers=agent_headers,
            json={"agent_id": agent["id"], "candles": candles},
        )
        assert stored.status_code == 202

        created = client.post(
            "/api/v1/backtests",
            headers=headers,
            json={
                "bot_id": bot_id,
                "config_version_id": config["id"],
                "market_feed_id": feed["id"],
                "date_from": start.isoformat(),
                "date_to": (start + timedelta(minutes=candle_count)).isoformat(),
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
        experiment = created.json()

    exit_code = main(["--run-id", experiment["run_id"]])
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == experiment["run_id"]
    assert payload["status"] == "SUCCEEDED"

    with SessionLocal() as db:
        stored_experiment = db.get(BacktestExperiment, uuid.UUID(experiment["id"]))
        assert stored_experiment is not None
        assert stored_experiment.status == "SUCCEEDED"
        assert stored_experiment.progress == {
            "processed": candle_count,
            "total": candle_count,
        }
        trade_count = db.scalar(
            select(func.count(BacktestTrade.id)).where(
                BacktestTrade.experiment_id == stored_experiment.id
            )
        )
        assert trade_count == stored_experiment.summary["total_trades"]
