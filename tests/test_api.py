import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from goldie_api.db import Base, SessionLocal, engine
from goldie_api.backtests import BacktestProgressReporter, execute_backtest
from goldie_api.maintenance import prune_market_quotes
from goldie_api.main import app
from goldie_api.models import (
    Bot,
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


def test_binance_collector_instrument_and_feed_registration() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        instrument = client.post(
            "/api/v1/collector/instruments",
            headers=headers,
            json={
                "provider": "binance_spot",
                "environment": "spot",
                "provider_symbol": "BTCUSDT",
            },
        )
        assert instrument.status_code == 201
        assert instrument.json()["provider"] == "binance_spot"
        assert instrument.json()["environment"] == "spot"

        feed = client.post(
            "/api/v1/market-feeds/register",
            headers={"X-Agent-Token": "test-agent-token"},
            json={
                "provider": "binance_spot",
                "environment": "spot",
                "canonical_symbol": "BTCUSDT",
                "provider_symbol": "BTCUSDT",
                "agent_name": "collector-binance-spot-btcusdt",
            },
        )
        assert feed.status_code == 201
        assert feed.json()["feed"]["provider"] == "binance_spot"

        settings = client.get("/api/v1/collector/settings", headers=headers)
        assert settings.status_code == 200
        rows = settings.json()["instruments"]
        assert rows[0]["market_feed_id"] == feed.json()["feed"]["id"]


def test_strategy_catalog_endpoint() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        response = client.get("/api/v1/strategies", headers=headers)
        assert response.status_code == 200
        catalog = {item["name"]: item for item in response.json()}
        assert set(catalog) == {
            "basic_momentum",
            "ema_rsi",
            "bb_rsi_mean_reversion",
            "ema_momentum_breakout",
            "ema_atr_trend",
            "bb_momentum_breakout",
            "bb_ema_rsi_mean_reversion",
            "range_break_scalper",
            "pine_bb_rsi_stoch",
        }
        assert catalog["ema_rsi"]["required_candles"] == 21
        assert "fast_ema_period" in catalog["ema_rsi"]["parameters"]
        parameter = catalog["ema_rsi"]["parameters"]["fast_ema_period"]
        assert parameter["description"]
        assert parameter["unit"] == "candles"
        assert parameter["impact"]


def register_feed(client: TestClient, symbol: str, provider_symbol: str) -> str:
    response = client.post(
        "/api/v1/market-feeds/register",
        headers={"X-Agent-Token": "test-agent-token"},
        json={
            "provider": "oanda",
            "environment": "practice",
            "canonical_symbol": symbol,
            "provider_symbol": provider_symbol,
            "agent_name": f"collector-{symbol.lower()}",
        },
    )
    assert response.status_code == 201
    return response.json()["feed"]["id"]


def create_strategy(
    client: TestClient, headers: dict[str, str], name: str = "Global momentum"
) -> dict:
    created = client.post(
        "/api/v1/strategy-profiles",
        headers=headers,
        json={
            "name": name,
            "description": "Shared configuration",
            "initial_config": {
                "market": {"symbol": "EURUSD", "timeframe": "M1"},
                "strategy": {
                    "name": "basic_momentum",
                    "parameters": {
                        "lookback_candles": 5,
                        "min_momentum_points": 50,
                    },
                },
                "filters": {"max_spread_points": 30, "stale_after_seconds": 15},
                "session": {
                    "timezone": "Europe/Vilnius",
                    "start_time": "10:00:00",
                    "end_time": "18:00:00",
                },
                "theoretical_trade": {
                    "stop_loss_points": 70,
                    "take_profit_points": 100,
                    "risk_per_trade_pct": 0.25,
                    "max_trade_duration_minutes": 5,
                    "max_open_shadow_positions": 1,
                },
            },
        },
    )
    assert created.status_code == 201
    profile = created.json()
    assert profile["status"] == "ACTIVE"
    assert profile["config"]["strategy"]["name"] == "basic_momentum"
    return profile


def test_global_strategy_bulk_creation_and_overrides() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        eur_feed = register_feed(client, "EURUSD", "EUR_USD")
        xau_feed = register_feed(client, "XAUUSD", "XAU_USD")
        profile = create_strategy(client, headers)

        request = {
            "request_id": str(uuid.uuid4()),
            "strategy_profile_id": profile["id"],
            "market_feed_ids": [eur_feed, xau_feed],
            "mode": "SHADOW",
            "name_template": "{symbol}-{strategy}-{mode}",
        }
        first = client.post("/api/v1/bots/bulk", headers=headers, json=request)
        assert first.status_code == 200
        assert [item["status"] for item in first.json()] == ["CREATED", "CREATED"]
        second = client.post("/api/v1/bots/bulk", headers=headers, json=request)
        assert second.status_code == 200
        assert [item["status"] for item in second.json()] == ["EXISTS", "EXISTS"]
        with SessionLocal() as db:
            assert db.scalar(select(func.count(Bot.id))) == 2

        eur_bot = first.json()[0]["bot"]
        override = client.put(
            f"/api/v1/bots/{eur_bot['id']}/overrides",
            headers=headers,
            json={
                "overrides": {
                    "filters": {"max_spread_points": 12},
                    "theoretical_trade": {"risk_per_trade_pct": 0.1},
                }
            },
        )
        assert override.status_code == 200
        assert override.json()["config"]["market"]["symbol"] == "EURUSD"
        assert override.json()["config"]["filters"]["max_spread_points"] == "12"
        assert override.json()["config_overrides"]["filters"]["max_spread_points"] == 12

        market_override = client.put(
            f"/api/v1/bots/{eur_bot['id']}/overrides",
            headers=headers,
            json={"overrides": {"market": {"symbol": "XAUUSD"}}},
        )
        assert market_override.status_code == 409


def test_strategy_update_activates_linked_bot_config() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        feed_id = register_feed(client, "EURUSD", "EUR_USD")
        profile = create_strategy(client, headers, "Strategy propagation")
        bulk = client.post(
            "/api/v1/bots/bulk",
            headers=headers,
            json={
                "request_id": str(uuid.uuid4()),
                "strategy_profile_id": profile["id"],
                "market_feed_ids": [feed_id],
                "mode": "SHADOW",
                "name_template": "{symbol}-isolated",
            },
        ).json()
        bot = bulk[0]["bot"]
        changed = profile["config"]
        changed["filters"]["max_spread_points"] = 5
        updated = client.patch(
            f"/api/v1/strategy-profiles/{profile['id']}",
            headers=headers,
            json={"config": changed},
        )
        assert updated.status_code == 200
        current = client.get(f"/api/v1/bots/{bot['id']}", headers=headers).json()
        assert current["strategy_profile_id"] == profile["id"]
        configs = client.get(
            f"/api/v1/bots/{bot['id']}/config-versions", headers=headers
        ).json()
        assert len(configs) == 2
        assert configs[0]["status"] == "ACTIVE"
        assert configs[0]["config"]["filters"]["max_spread_points"] == "5"
        assert configs[1]["status"] == "SUPERSEDED"


def test_strategy_and_bot_crud_archive_preserves_history() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        feed_id = register_feed(client, "EURUSD", "EUR_USD")
        profile = create_strategy(client, headers, "CRUD strategy")
        bot = client.post(
            "/api/v1/bots/bulk",
            headers=headers,
            json={
                "request_id": str(uuid.uuid4()),
                "strategy_profile_id": profile["id"],
                "market_feed_ids": [feed_id],
                "mode": "SHADOW",
                "name_template": "crud-{symbol}",
            },
        ).json()[0]["bot"]
        updated = client.patch(
            f"/api/v1/bots/{bot['id']}",
            headers=headers,
            json={"name": "Renamed CRUD bot", "description": "Updated"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Renamed CRUD bot"

        archived_bot = client.delete(f"/api/v1/bots/{bot['id']}", headers=headers)
        assert archived_bot.status_code == 200
        assert archived_bot.json()["archived_at"] is not None
        assert client.get("/api/v1/bots", headers=headers).json() == []
        with SessionLocal() as db:
            assert db.scalar(select(func.count(ConfigVersion.id))) == 1
            assert db.scalar(select(func.count(Run.id))) == 1

        archived_strategy = client.delete(
            f"/api/v1/strategy-profiles/{profile['id']}", headers=headers
        )
        assert archived_strategy.status_code == 200
        assert archived_strategy.json()["status"] == "ARCHIVED"
        assert client.get("/api/v1/strategy-profiles", headers=headers).json() == []


def activate_first_config(client: TestClient, bot_id: str, headers: dict[str, str]) -> None:
    versions = client.get(
        f"/api/v1/bots/{bot_id}/config-versions", headers=headers
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
        candle_count = 2105
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
        assert created.json()["fill_mode"] == "simulated"
        assert created.json()["medium_impact"] == created.json()["slippage_medium"]
        experiment_id = uuid.UUID(created.json()["id"])
        statements = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            with SessionLocal() as db:
                experiment = db.get(BacktestExperiment, experiment_id)
                experiment.status = "RUNNING"
                db.commit()
                execute_backtest(db, experiment_id)
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)

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
        assert detail.json()["progress"]["processed"] == candle_count
        assert trades.status_code == 200
        assert trades.json()["total"] >= 1
        assert csv_export.status_code == 200
        assert csv_export.text.startswith("id,experiment_id,direction")
        assert json_export.status_code == 200
        assert json_export.json()["experiment"]["id"] == str(experiment_id)
        candle_select = next(
            statement
            for statement in statements
            if "FROM candles" in statement and "ORDER BY candles.opened_at" in statement
        )
        selected_columns = candle_select.split("FROM candles", 1)[0]
        assert "candles.id" not in selected_columns
        assert "candles.opened_at" in selected_columns
        assert "candles.tick_volume" in selected_columns


def test_batch_backtest_uses_active_bot_configuration() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as client:
        headers = login(client)
        feed_id = register_feed(client, "XAUUSD", "XAU_USD")
        active = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Batch active", "market_feed_id": feed_id},
        ).json()
        inactive = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "Batch inactive"},
        ).json()
        response = client.post(
            "/api/v1/backtests/batch",
            headers=headers,
            json={
                "bot_ids": [active["id"], inactive["id"]],
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-01-02T00:00:00Z",
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
        assert response.status_code == 200
        assert [item["status"] for item in response.json()] == ["CREATED", "FAILED"]
        assert response.json()[0]["experiment"]["config_version_id"] == active[
            "active_config_version_id"
        ]


def test_backtest_progress_reporter_throttles_and_honors_cancel() -> None:
    class FakeDialect:
        name = "sqlite"

    class FakeBind:
        dialect = FakeDialect()

    class FakeSession:
        def get_bind(self):
            return FakeBind()

    now = [0.0]
    writes = []
    reporter = BacktestProgressReporter(
        FakeSession(),
        uuid.uuid4(),
        clock=lambda: now[0],
    )
    reporter._write = lambda _db, processed, total: (
        writes.append((processed, total)) or True
    )

    assert reporter(100, 5000)
    assert writes == []
    assert reporter(2000, 5000)
    assert writes == [(2000, 5000)]
    now[0] = 1.1
    assert reporter(2100, 5000)
    assert writes[-1] == (2100, 5000)
    reporter._write = lambda _db, _processed, _total: False
    assert reporter(5000, 5000) is False


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
        empty_bot = client.post(
            "/api/v1/bots",
            headers=headers,
            json={"name": "No performance yet", "mode": "SHADOW"},
        ).json()
        portfolio = client.get(
            "/api/v1/bots/performance"
            "?date_from=2026-06-11T00:00:00Z&date_to=2026-06-12T00:00:00Z",
            headers=headers,
        )

        assert trades.status_code == 200
        assert len(trades.json()) == 1
        assert performance.status_code == 200
        assert performance.json()["closed_trades"] == 1
        assert performance.json()["win_rate"] == "100"
        assert performance.json()["net_pnl"] == "8.00000000"
        assert portfolio.status_code == 200
        by_id = {item["bot"]["id"]: item["performance"] for item in portfolio.json()["items"]}
        assert by_id[bot["id"]]["net_pnl"] == "8.00000000"
        assert by_id[empty_bot["id"]]["closed_trades"] == 0


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
                    "backfill_batch_size": 50,
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
                    "backfill_batch_size": 50,
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


def test_feed_pause_is_immediate_persistent_and_resume_skips_gap() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    agent_headers = {"X-Agent-Token": "test-agent-token"}
    with TestClient(app) as client:
        instance = client.post(
            "/api/v1/collector/instances/register",
            headers=agent_headers,
            json={
                "name": "pause-test-collector",
                "defaults": {
                    "quote_interval_seconds": 5,
                    "candle_poll_seconds": 15,
                    "heartbeat_seconds": 10,
                    "backfill_days": 30,
                    "backfill_batch_size": 50,
                    "configuration_retry_seconds": 900,
                },
                "instruments": ["EUR_USD"],
            },
        ).json()["instance"]
        feed = client.post(
            "/api/v1/market-feeds/register",
            headers=agent_headers,
            json={
                "provider": "oanda",
                "environment": "practice",
                "canonical_symbol": "EURUSD",
                "provider_symbol": "EUR_USD",
                "agent_name": "pause-test-agent",
            },
        ).json()["feed"]
        headers = login(client)
        paused = client.post(
            "/api/v1/collector/commands",
            headers=headers,
            json={"command": "PAUSE", "market_feed_id": feed["id"], "payload": {}},
        ).json()

        feeds = client.get("/api/v1/market-feeds", headers=headers).json()
        current = next(item for item in feeds if item["id"] == feed["id"])
        assert current["status"] == "PAUSED"
        assert current["paused_at"] is not None
        control = client.post(
            f"/api/v1/collector/instances/{instance['id']}/poll",
            headers=agent_headers,
            json={},
        ).json()
        instrument = next(
            item for item in control["instruments"] if item["market_feed_id"] == feed["id"]
        )
        assert instrument["feed_status"] == "PAUSED"

        client.patch(
            f"/api/v1/collector/commands/{paused['id']}",
            headers=agent_headers,
            json={"status": "SUCCEEDED", "result": {}, "progress": {}},
        )
        resumed = client.post(
            "/api/v1/collector/commands",
            headers=headers,
            json={"command": "RESUME", "market_feed_id": feed["id"], "payload": {}},
        ).json()
        client.patch(
            f"/api/v1/collector/commands/{resumed['id']}",
            headers=agent_headers,
            json={"status": "SUCCEEDED", "result": {}, "progress": {}},
        )

        feeds = client.get("/api/v1/market-feeds", headers=headers).json()
        current = next(item for item in feeds if item["id"] == feed["id"])
        assert current["status"] == "REGISTERED"
        assert current["paused_at"] is None
        assert current["resume_from_at"] is not None
        resume_from = datetime.fromisoformat(current["resume_from_at"])
        assert resume_from.second == 0
        assert resume_from.microsecond == 0


def test_feed_heartbeat_publishes_once_and_excludes_archived_bots(monkeypatch) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    agent_headers = {"X-Agent-Token": "test-agent-token"}
    published: list[dict] = []
    monkeypatch.setattr(
        "goldie_api.routers.feeds.publish_event_sync",
        lambda payload: published.append(dict(payload)) or True,
    )
    with TestClient(app) as client:
        registration = client.post(
            "/api/v1/market-feeds/register",
            headers=agent_headers,
            json={
                "provider": "oanda",
                "environment": "practice",
                "canonical_symbol": "EURUSD",
                "provider_symbol": "EUR_USD",
                "agent_name": "heartbeat-test-agent",
            },
        ).json()
        feed_id = registration["feed"]["id"]
        with SessionLocal() as db:
            active_ids = []
            for index in range(3):
                bot = Bot(
                    name=f"Heartbeat active {index}",
                    market_feed_id=uuid.UUID(feed_id),
                    state="MONITORING",
                    active_config_version_id=uuid.uuid4(),
                )
                db.add(bot)
                db.flush()
                active_ids.append(str(bot.id))
            db.add(
                Bot(
                    name="Heartbeat archived",
                    market_feed_id=uuid.UUID(feed_id),
                    state="MONITORING",
                    active_config_version_id=uuid.uuid4(),
                    archived_at=datetime.now(UTC),
                )
            )
            db.commit()

        response = client.post(
            f"/api/v1/market-feeds/{feed_id}/heartbeat",
            headers=agent_headers,
            json={
                "agent_id": registration["agent"]["id"],
                "status": "ONLINE",
                "details": {},
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )

        assert response.status_code == 200
        assert len(published) == 1
        assert set(published[0]["bot_instance_ids"]) == set(active_ids)


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

        second_registration = client.post(
            "/api/v1/market-feeds/register",
            headers=agent_headers,
            json={
                "provider": "oanda",
                "environment": "practice",
                "canonical_symbol": "USDCHF",
                "provider_symbol": "USD_CHF",
                "agent_name": "test-usd-chf-agent",
            },
        ).json()
        other_feed = client.post(
            "/api/v1/collector/commands",
            headers=headers,
            json={
                "command": "BACKFILL",
                "market_feed_id": second_registration["feed"]["id"],
                "payload": {
                    "start": (now - timedelta(days=1)).isoformat(),
                    "end": now.isoformat(),
                },
            },
        )
        assert other_feed.status_code == 201

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

        deleted = client.delete(
            f"/api/v1/collector/commands/{valid.json()['id']}",
            headers=headers,
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "FAILED"
        assert deleted.json()["error"] == "Cancelled by user"

        replacement = client.post(
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
        assert replacement.status_code == 201
