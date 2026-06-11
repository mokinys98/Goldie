import os
from datetime import UTC, datetime

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient

from goldie_api.db import Base, engine
from goldie_api.main import app
from goldie_api.models import Candle
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
