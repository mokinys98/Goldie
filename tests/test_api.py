import os
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from goldie_api.db import Base, SessionLocal, engine
from goldie_api.maintenance import prune_market_quotes
from goldie_api.main import app
from goldie_api.models import Candle, MarketTick


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
            "/api/v1/market-feeds/register",
            json={
                "provider": "oanda",
                "environment": "practice",
                "canonical_symbol": "XAUUSD",
                "provider_symbol": "XAU_USD",
                "agent_name": "unauthorized",
            },
        )
        assert response.status_code == 401


def activate_first_config(client: TestClient, bot_id: str, headers: dict[str, str]) -> None:
    versions = client.get(
        f"/api/v1/bots/{bot_id}/config-versions", headers=headers
    ).json()
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


def test_shared_oanda_feed_and_paper_ledger() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    agent_headers = {"X-Agent-Token": "test-agent-token"}
    with TestClient(app) as client:
        feed_registration = client.post(
            "/api/v1/market-feeds/register",
            headers=agent_headers,
            json={
                "provider": "oanda",
                "environment": "practice",
                "canonical_symbol": "XAUUSD",
                "provider_symbol": "XAU_USD",
                "agent_name": "test-oanda-collector",
            },
        )
        assert feed_registration.status_code == 201
        registration = feed_registration.json()
        feed_id = registration["feed"]["id"]
        agent_id = registration["agent"]["id"]

        headers = login(client)
        paper = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Paper bot", "mode": "PAPER"},
        ).json()
        shadow = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Shadow bot", "mode": "SHADOW"},
        ).json()
        assert paper["market_feed_id"] == feed_id
        assert shadow["market_feed_id"] == feed_id
        activate_first_config(client, paper["id"], headers)
        activate_first_config(client, shadow["id"], headers)

        specification = client.post(
            f"/api/v1/market-feeds/{feed_id}/instrument-specification",
            headers=agent_headers,
            json={
                "agent_id": agent_id,
                "canonical_symbol": "XAUUSD",
                "provider_symbol": "XAU_USD",
                "display_precision": 3,
                "pip_location": -2,
                "minimum_trade_size": "1",
                "trade_units_precision": 0,
                "margin_rate": "0.05",
                "provider_metadata": {"type": "METAL"},
            },
        )
        assert specification.status_code == 202

        now = datetime.now(UTC)
        quote = client.post(
            f"/api/v1/market-feeds/{feed_id}/quotes/batch",
            headers=agent_headers,
            json={
                "agent_id": agent_id,
                "quotes": [
                    {
                        "observed_at": now.isoformat(),
                        "bid": "2350.00",
                        "ask": "2350.20",
                    }
                ],
            },
        )
        assert quote.status_code == 202

        minute = now.replace(second=0, microsecond=0)
        candles = []
        for index in range(6):
            price = 2349 + index * 0.2
            candles.append(
                {
                    "opened_at": (minute - timedelta(minutes=6 - index)).isoformat(),
                    "open": str(price),
                    "high": str(price + 0.25),
                    "low": str(price - 0.05),
                    "close": str(price + 0.2),
                    "volume": 100 + index,
                    "complete": True,
                }
            )
        first = client.post(
            f"/api/v1/market-feeds/{feed_id}/candles/batch",
            headers=agent_headers,
            json={"agent_id": agent_id, "candles": candles},
        )
        assert first.status_code == 202
        assert first.json()["count"] == 6
        assert len(first.json()["signal_ids"]) == 2

        duplicate = client.post(
            f"/api/v1/market-feeds/{feed_id}/candles/batch",
            headers=agent_headers,
            json={"agent_id": agent_id, "candles": candles},
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["count"] == 0
        assert duplicate.json()["duplicates"] == 6

        paper_status = client.get(
            f"/api/v1/bots/{paper['id']}/status", headers=headers
        ).json()
        shadow_status = client.get(
            f"/api/v1/bots/{shadow['id']}/status", headers=headers
        ).json()
        assert paper_status["paper_account"]["balance"] == 10000.0
        assert paper_status["paper_account"]["equity"] == 10000.0
        assert shadow_status["paper_account"] is None
        assert paper_status["latest_tick"]["bid"] == 2350.0

        with SessionLocal() as db:
            assert db.scalar(select(func.count(MarketTick.id))) == 1
            assert db.scalar(select(func.count(Candle.id))) == 6
            tick = db.scalar(select(MarketTick))
            tick.received_at = now - timedelta(days=31)
            db.commit()

        assert prune_market_quotes() == 1

        heartbeat = client.post(
            f"/api/v1/market-feeds/{feed_id}/heartbeat",
            headers=agent_headers,
            json={
                "agent_id": agent_id,
                "status": "MARKET_CLOSED",
                "details": {"reason": "weekend"},
                "observed_at": now.isoformat(),
            },
        )
        assert heartbeat.status_code == 200
        closed_status = client.get(
            f"/api/v1/bots/{paper['id']}/status", headers=headers
        ).json()
        assert closed_status["agent_effective_status"] == "MARKET_CLOSED"
        assert closed_status["data_state"] == "MARKET_CLOSED"


def test_no_order_execution_api_exists() -> None:
    paths = app.openapi()["paths"]
    assert not any(
        token in path
        for path in paths
        for token in ("/orders", "/trades", "/positions", "/execution")
    )
