import os
import uuid
from datetime import UTC, datetime

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient

from goldie_api.db import Base, engine
from goldie_api.main import app
from goldie_api.models import Candle, ConfigVersion, Run, Signal, SignalOutcome
from sqlalchemy import select
from sqlalchemy.orm import Session


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_bot_config_lifecycle() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        created = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "API lifecycle bot", "description": "test", "mode": "SHADOW"},
        )
        assert created.status_code == 201
        bot = created.json()

        versions = client.get(f"/api/v1/bots/{bot['id']}/config-versions", headers=headers).json()
        assert versions[0]["status"] == "DRAFT"

        validated = client.post(
            f"/api/v1/config-versions/{versions[0]['id']}/validate", headers=headers
        )
        assert validated.status_code == 200
        assert validated.json()["status"] == "VALIDATED"

        activated = client.post(
            f"/api/v1/config-versions/{versions[0]['id']}/activate", headers=headers
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "ACTIVE"

        runs = client.get(f"/api/v1/bots/{bot['id']}/runs", headers=headers).json()
        assert len(runs) == 1
        assert runs[0]["status"] == "ACTIVE"


def test_agent_token_is_required() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agents/register",
            json={
                "bot_id": "00000000-0000-0000-0000-000000000000",
                "name": "unauthorized",
                "adapter": "fake",
            },
        )
        assert response.status_code == 401


def test_duplicate_candle_is_idempotent() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        bot = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Candle idempotency bot", "mode": "SHADOW"},
        ).json()
        agent = client.post(
            "/api/v1/agents/register",
            headers={"X-Agent-Token": "test-agent-token"},
            json={
                "bot_id": bot["id"],
                "name": "test-agent",
                "adapter": "fake",
            },
        ).json()
        candle = {
            "agent_id": agent["id"],
            "bot_id": bot["id"],
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "opened_at": datetime(2026, 6, 11, 10, 0, tzinfo=UTC).isoformat(),
            "open": "2350.00",
            "high": "2351.00",
            "low": "2349.00",
            "close": "2350.50",
            "tick_volume": 100,
            "is_complete": True,
        }

        first = client.post(
            "/api/v1/market/candles",
            headers={"X-Agent-Token": "test-agent-token"},
            json=candle,
        )
        duplicate = client.post(
            "/api/v1/market/candles",
            headers={"X-Agent-Token": "test-agent-token"},
            json=candle,
        )

        assert first.status_code == 202
        assert duplicate.status_code == 202
        assert duplicate.json() == {"accepted": True, "duplicate": True}
        with Session(engine) as db:
            rows = list(db.scalars(select(Candle)))
        assert len(rows) == 1


def test_shadow_trade_and_performance_endpoints() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        bot = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Performance bot", "mode": "SHADOW"},
        ).json()
        bot_id = uuid.UUID(bot["id"])
        with Session(engine) as db:
            config = db.scalar(
                select(ConfigVersion).where(ConfigVersion.bot_id == bot_id)
            )
            run = Run(
                bot_id=bot_id,
                config_version_id=config.id,
                mode="SHADOW",
            )
            db.add(run)
            db.flush()
            signal = Signal(
                bot_id=bot_id,
                run_id=run.id,
                config_version_id=config.id,
                observed_at=datetime(2026, 6, 11, 10, 0, tzinfo=UTC),
                signal="BUY",
                reason_code="MOMENTUM_UP",
                entry_price="2350.20",
                stop_loss="2349.50",
                take_profit="2351.20",
                inputs={},
            )
            db.add(signal)
            db.flush()
            db.add(
                SignalOutcome(
                    signal_id=signal.id,
                    bot_id=bot_id,
                    run_id=run.id,
                    config_version_id=config.id,
                    direction="BUY",
                    status="CLOSED",
                    result="WIN",
                    close_reason="TAKE_PROFIT",
                    opened_at=datetime(2026, 6, 11, 10, 0, tzinfo=UTC),
                    closed_at=datetime(2026, 6, 11, 10, 2, tzinfo=UTC),
                    entry_price="2350.20",
                    exit_price="2351.20",
                    stop_loss="2349.50",
                    take_profit="2351.20",
                    volume="0.08",
                    risk_amount="5.60",
                    gross_pnl="8.00",
                    net_pnl="8.00",
                    pnl_points="100",
                    r_multiple="1.42857143",
                    mfe_points="110",
                    mae_points="10",
                    duration_seconds=120,
                )
            )
            db.commit()
            run_id = run.id

        trades = client.get(
            f"/api/v1/bots/{bot['id']}/shadow-trades?result=WIN&direction=BUY",
            headers=headers,
        )
        performance = client.get(
            f"/api/v1/runs/{run_id}/performance",
            headers=headers,
        )

        assert trades.status_code == 200
        assert len(trades.json()) == 1
        assert performance.status_code == 200
        assert performance.json()["closed_trades"] == 1
        assert performance.json()["win_rate"] == "100"
        assert performance.json()["net_pnl"] == "8.00000000"
