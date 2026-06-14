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
from sqlalchemy.orm import Session

from goldie_api.db import Base, SessionLocal, engine
from goldie_api.backtests import execute_backtest
from goldie_api.maintenance import prune_market_quotes
from goldie_api.main import app
from goldie_api.models import (
    Candle,
    BacktestExperiment,
    ConfigVersion,
    MarketTick,
    Run,
    Signal,
    SignalOutcome,
)


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
                "canonical_symbol": "USDJPY",
                "provider_symbol": "USD_JPY",
                "agent_name": "unauthorized",
            },
        )
        assert response.status_code == 401


def test_strategy_catalog_endpoint() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        response = client.get("/api/v1/strategies", headers=headers)
        assert response.status_code == 200
        catalog = {item["name"]: item for item in response.json()}
        assert set(catalog) == {"basic_momentum", "ema_rsi"}
        assert catalog["ema_rsi"]["required_candles"] == 21
        assert "fast_ema_period" in catalog["ema_rsi"]["parameters"]


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
                "canonical_symbol": "USDJPY",
                "provider_symbol": "USD_JPY",
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
            json={
                "name": "Paper bot",
                "mode": "PAPER",
                "market_feed_id": feed_id,
            },
        ).json()
        shadow = client.post(
            "/api/v1/bots",
            headers=headers,
            json={
                "name": "Shadow bot",
                "mode": "SHADOW",
                "market_feed_id": feed_id,
            },
        ).json()
        assert paper["market_feed_id"] == feed_id
        assert shadow["market_feed_id"] == feed_id
        versions = client.get(
            f"/api/v1/bots/{paper['id']}/config-versions",
            headers=headers,
        ).json()
        assert versions[0]["config"]["market"]["symbol"] == "USDJPY"
        mismatched_config = versions[0]["config"]
        mismatched_config["market"]["symbol"] = "EURUSD"
        mismatch = client.post(
            f"/api/v1/bots/{paper['id']}/config-versions",
            headers=headers,
            json={"config": mismatched_config},
        )
        assert mismatch.status_code == 409
        activate_first_config(client, paper["id"], headers)
        activate_first_config(client, shadow["id"], headers)

        specification = client.post(
            f"/api/v1/market-feeds/{feed_id}/instrument-specification",
            headers=agent_headers,
            json={
                "agent_id": agent_id,
                "canonical_symbol": "USDJPY",
                "provider_symbol": "USD_JPY",
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
        if not path.startswith("/api/v1/backtests")
        for token in ("/orders", "/trades", "/positions", "/execution")
    )


def test_backtest_api_execution_and_exports() -> None:
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
                "agent_name": "backtest-agent",
            },
        ).json()
        feed_id = registration["feed"]["id"]
        agent_id = registration["agent"]["id"]
        headers = login(client)
        bot = client.post(
            "/api/v1/bots",
            headers=headers,
            json={
                "name": "Backtest bot",
                "mode": "SHADOW",
                "market_feed_id": feed_id,
            },
        ).json()
        activate_first_config(client, bot["id"], headers)
        config = client.get(
            f"/api/v1/bots/{bot['id']}/config-versions",
            headers=headers,
        ).json()[0]
        specification = client.post(
            f"/api/v1/market-feeds/{feed_id}/instrument-specification",
            headers=agent_headers,
            json={
                "agent_id": agent_id,
                "canonical_symbol": "XAUUSD",
                "provider_symbol": "XAU_USD",
                "display_precision": 2,
                "pip_location": -2,
                "minimum_trade_size": "1",
                "trade_units_precision": 0,
                "margin_rate": "0.05",
            },
        )
        assert specification.status_code == 202
        start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
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
            for index in range(12)
        ]
        stored = client.post(
            f"/api/v1/market-feeds/{feed_id}/candles/batch",
            headers=agent_headers,
            json={"agent_id": agent_id, "candles": candles},
        )
        assert stored.status_code == 202
        created = client.post(
            "/api/v1/backtests",
            headers=headers,
            json={
                "bot_id": bot["id"],
                "config_version_id": config["id"],
                "market_feed_id": feed_id,
                "date_from": start.isoformat(),
                "date_to": (start + timedelta(minutes=12)).isoformat(),
                "initial_capital": "10000",
                "spread_points": "2",
                "slippage_points": "1",
                "commission_per_trade": "1",
            },
        )
        assert created.status_code == 201
        experiment_id = uuid.UUID(created.json()["id"])
        with SessionLocal() as db:
            experiment = db.get(BacktestExperiment, experiment_id)
            experiment.status = "RUNNING"
            db.commit()
            execute_backtest(db, experiment_id)

        detail = client.get(f"/api/v1/backtests/{experiment_id}", headers=headers)
        trades = client.get(
            f"/api/v1/backtests/{experiment_id}/trades",
            headers=headers,
        )
        csv_export = client.get(
            f"/api/v1/backtests/{experiment_id}/export?format=csv",
            headers=headers,
        )
        json_export = client.get(
            f"/api/v1/backtests/{experiment_id}/export?format=json",
            headers=headers,
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "SUCCEEDED"
        assert detail.json()["progress"]["processed"] == 12
        assert trades.status_code == 200
        assert trades.json()["total"] >= 1
        assert csv_export.status_code == 200
        assert csv_export.text.startswith("id,experiment_id,direction")
        assert json_export.status_code == 200
        assert json_export.json()["experiment"]["id"] == str(experiment_id)
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


def test_collector_control_plane_lifecycle() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    agent_headers = {"X-Agent-Token": "test-agent-token"}
    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/collector/instances/register",
            headers=agent_headers,
            json={
                "name": "test-collector",
                "defaults": {
                    "quote_interval_seconds": 5,
                    "candle_poll_seconds": 15,
                    "heartbeat_seconds": 10,
                    "backfill_days": 30,
                    "backfill_batch_size": 250,
                    "configuration_retry_seconds": 900,
                },
                "instruments": ["EUR_USD", "USD_JPY"],
            },
        )
        assert registered.status_code == 201
        instance_id = registered.json()["instance"]["id"]
        assert registered.json()["configuration"]["version"] == 1

        headers = login(client)
        settings = client.get("/api/v1/collector/settings", headers=headers)
        assert settings.status_code == 200
        assert len(settings.json()["instruments"]) == 2

        update_payload = {
            **settings.json()["configuration"],
            "expected_version": 1,
            "quote_interval_seconds": 7,
        }
        update_payload.pop("id")
        update_payload.pop("version")
        update_payload.pop("updated_at")
        updated = client.put(
            "/api/v1/collector/settings",
            headers=headers,
            json=update_payload,
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2
        conflict = client.put(
            "/api/v1/collector/settings",
            headers=headers,
            json=update_payload,
        )
        assert conflict.status_code == 409

        command = client.post(
            "/api/v1/collector/commands",
            headers=headers,
            json={"command": "PAUSE", "payload": {}},
        )
        assert command.status_code == 201
        command_id = command.json()["id"]
        polled = client.post(
            f"/api/v1/collector/instances/{instance_id}/poll",
            headers=agent_headers,
            json={},
        )
        assert polled.status_code == 200
        assert polled.json()["commands"][0]["id"] == command_id
        assert polled.json()["commands"][0]["status"] == "RUNNING"
        assert polled.json()["configuration"]["version"] == 2

        restarted = client.post(
            "/api/v1/collector/instances/register",
            headers=agent_headers,
            json={
                "name": "test-collector",
                "defaults": {
                    "quote_interval_seconds": 5,
                    "candle_poll_seconds": 15,
                    "heartbeat_seconds": 10,
                    "backfill_days": 30,
                    "backfill_batch_size": 250,
                    "configuration_retry_seconds": 900,
                },
                "instruments": ["EUR_USD", "USD_JPY"],
            },
        )
        assert restarted.status_code == 201
        assert restarted.json()["instance"]["id"] == instance_id

        resumed = client.post(
            f"/api/v1/collector/instances/{instance_id}/poll",
            headers=agent_headers,
            json={},
        )
        assert resumed.status_code == 200
        assert resumed.json()["commands"][0]["id"] == command_id
        assert resumed.json()["commands"][0]["status"] == "RUNNING"

        completed = client.patch(
            f"/api/v1/collector/commands/{command_id}",
            headers=agent_headers,
            json={
                "status": "SUCCEEDED",
                "progress": {},
                "result": {"symbols": ["EUR_USD", "USD_JPY"]},
            },
        )
        assert completed.status_code == 200
        duplicate = client.patch(
            f"/api/v1/collector/commands/{command_id}",
            headers=agent_headers,
            json={"status": "FAILED", "error": "late duplicate"},
        )
        assert duplicate.json()["status"] == "SUCCEEDED"

        heartbeat = client.post(
            f"/api/v1/collector/instances/{instance_id}/heartbeat",
            headers=agent_headers,
            json={
                "status": "ONLINE",
                "applied_config_version": 2,
                "details": {"worker_count": 2, "read_only": True},
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )
        assert heartbeat.status_code == 200
        overview = client.get("/api/v1/collector/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["instance"]["status"] == "ONLINE"
        assert overview.json()["instance"]["applied_config_version"] == 2


def test_collector_feed_data_commands_and_export() -> None:
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
                "canonical_symbol": "EURUSD",
                "provider_symbol": "EUR_USD",
                "agent_name": "test-feed-agent",
            },
        ).json()
        feed_id = registration["feed"]["id"]
        agent_id = registration["agent"]["id"]
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        client.post(
            f"/api/v1/market-feeds/{feed_id}/quotes/batch",
            headers=agent_headers,
            json={
                "agent_id": agent_id,
                "quotes": [
                    {
                        "observed_at": now.isoformat(),
                        "bid": "1.08000",
                        "ask": "1.08020",
                    }
                ],
            },
        )
        client.post(
            f"/api/v1/market-feeds/{feed_id}/candles/batch",
            headers=agent_headers,
            json={
                "agent_id": agent_id,
                "candles": [
                    {
                        "opened_at": (now - timedelta(minutes=index)).isoformat(),
                        "open": "1.08000",
                        "high": "1.08100",
                        "low": "1.07900",
                        "close": "1.08050",
                        "volume": 10 + index,
                        "complete": True,
                    }
                    for index in range(3)
                ],
            },
        )
        headers = login(client)
        detail = client.get(f"/api/v1/collector/feeds/{feed_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["feed"]["latest_tick"]["spread"] == 0.0002

        candles = client.get(
            f"/api/v1/collector/feeds/{feed_id}/candles?limit=2",
            headers=headers,
        )
        assert candles.status_code == 200
        assert len(candles.json()["items"]) == 2
        assert candles.json()["next_cursor"] is not None
        ticks = client.get(
            f"/api/v1/collector/feeds/{feed_id}/ticks",
            headers=headers,
        )
        assert len(ticks.json()["items"]) == 1

        export = client.get(
            f"/api/v1/collector/feeds/{feed_id}/export/candles",
            headers=headers,
            params={
                "start": (now - timedelta(days=1)).isoformat(),
                "end": (now + timedelta(minutes=1)).isoformat(),
            },
        )
        assert export.status_code == 200
        assert export.text.startswith("opened_at,open,high,low,close,volume")

        too_long = client.post(
            "/api/v1/collector/commands",
            headers=headers,
            json={
                "command": "BACKFILL",
                "market_feed_id": feed_id,
                "payload": {
                    "start": (now - timedelta(days=366)).isoformat(),
                    "end": now.isoformat(),
                },
            },
        )
        assert too_long.status_code == 422
        valid = client.post(
            "/api/v1/collector/commands",
            headers=headers,
            json={
                "command": "BACKFILL",
                "market_feed_id": feed_id,
                "payload": {
                    "start": (now - timedelta(days=30)).isoformat(),
                    "end": now.isoformat(),
                },
            },
        )
        assert valid.status_code == 201
        second = client.post(
            "/api/v1/collector/commands",
            headers=headers,
            json={
                "command": "BACKFILL",
                "market_feed_id": feed_id,
                "payload": {
                    "start": (now - timedelta(days=1)).isoformat(),
                    "end": now.isoformat(),
                },
            },
        )
        assert second.status_code == 409
