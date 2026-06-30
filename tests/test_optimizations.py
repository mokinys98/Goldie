import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

os.environ["DATABASE_URL"] = "sqlite:///./.pytest-goldie.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-longer-than-thirty-two-bytes"
os.environ["LOCAL_ADMIN_EMAIL"] = "admin@test.local"
os.environ["LOCAL_ADMIN_PASSWORD"] = "test-password"
os.environ["AGENT_SERVICE_TOKEN"] = "test-agent-token"

from fastapi.testclient import TestClient
from goldie_api.db import Base, SessionLocal, engine
from goldie_api.main import app
from goldie_api.models import (
    Candle,
    InstrumentSpecification,
    MarketFeed,
    OptimizationRun,
    OptimizationTrial,
    OptimizationTrialTrade,
)
from goldie_api.optimization_diagnostics import (
    build_backtest_diagnostics,
    build_data_profile,
    build_llm_context,
    build_research_quality_gates,
)
from goldie_api.optimizations import (
    OPTIMIZATION_CANCEL_CHECK_INTERVAL,
    OPTIMIZATION_COMMIT_INTERVAL,
    _is_cancellation_checkpoint,
    _is_commit_checkpoint,
    build_fixed_config_pairs,
    build_search_space,
    compute_balanced_score,
    execute_optimization,
    sample_parameters,
    split_optimization_period,
)


def test_optimization_progress_and_cancellation_use_five_trial_batches() -> None:
    assert OPTIMIZATION_COMMIT_INTERVAL == 5
    assert OPTIMIZATION_CANCEL_CHECK_INTERVAL == 5
    cancellation_checks = [index for index in range(12) if _is_cancellation_checkpoint(index)]
    commit_checks = [
        completed for completed in range(1, 13) if _is_commit_checkpoint(completed, 12)
    ]
    assert cancellation_checks == [0, 5, 10]
    assert commit_checks == [5, 10]


def test_search_space_includes_exclusive_minimum_parameters() -> None:
    from goldie_domain import BotConfiguration

    config = BotConfiguration.model_validate(
        {
            "strategy": {
                "name": "ema_atr_trend",
                "parameters": {
                    "fast_ema_period": 9,
                    "slow_ema_period": 21,
                    "atr_period": 14,
                    "min_atr_points": "5",
                    "max_atr_points": "500",
                    "min_trend_points": "0",
                    "atr_stop_multiplier": "1.5",
                    "require_crossover": False,
                },
            }
        }
    )

    names = {parameter["name"] for parameter in build_search_space(config)}

    assert "max_atr_points" in names
    assert "atr_stop_multiplier" in names


def test_strategy_ranges_override_catalog_search_space() -> None:
    from goldie_domain import BotConfiguration

    config = BotConfiguration.model_validate(
        {
            "strategy": {
                "name": "ema_rsi",
                "parameters": {
                    "fast_ema_period": 9,
                    "slow_ema_period": 21,
                    "rsi_period": 14,
                    "buy_rsi_max": "70",
                    "min_trend_points": "0",
                    "sell_rsi_min": "60",
                    "require_crossover": False,
                },
            }
        }
    )

    search_space = build_search_space(
        config,
        {"fast_ema_period": {"minimum": 6, "maximum": 12}},
    )
    fast_ema = next(item for item in search_space if item["name"] == "fast_ema_period")

    assert fast_ema["minimum"] == 6
    assert fast_ema["maximum"] == 12


def test_optimization_period_is_split_without_overlap() -> None:
    date_from = datetime(2026, 1, 1, tzinfo=UTC)
    date_to = date_from + timedelta(days=10)

    search_period, validation_period = split_optimization_period(date_from, date_to)

    assert search_period == (date_from, date_from + timedelta(days=8))
    assert validation_period == (search_period[1], date_to)


def test_fixed_config_grid_contains_nine_unique_pairs() -> None:
    from goldie_domain import BotConfiguration

    pairs = build_fixed_config_pairs(BotConfiguration())
    values = {
        (
            pair["theoretical_trade"]["stop_loss_points"],
            pair["theoretical_trade"]["take_profit_points"],
        )
        for pair in pairs
    }

    assert len(pairs) == 9
    assert len(values) == 9
    assert (Decimal("70.0"), Decimal("100.0")) in values


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
        assert (
            client.post(
                f"/api/v1/config-versions/{versions[0]['id']}/validate",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/v1/config-versions/{versions[0]['id']}/activate",
                headers=headers,
            ).status_code
            == 200
        )
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


def test_data_profile_excludes_oanda_weekend_market_closure_from_detected_gaps() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        feed = MarketFeed(
            provider="oanda",
            environment="practice",
            canonical_symbol="XAUUSD",
            provider_symbol="XAU_USD",
        )
        db.add(feed)
        db.flush()
        for opened_at in (
            datetime(2026, 1, 2, 21, 59, tzinfo=UTC),
            datetime(2026, 1, 4, 22, 0, tzinfo=UTC),
            datetime(2026, 1, 4, 22, 3, tzinfo=UTC),
        ):
            db.add(
                Candle(
                    market_feed_id=feed.id,
                    symbol="XAUUSD",
                    timeframe="M1",
                    opened_at=opened_at,
                    source="oanda",
                    open=Decimal("2300"),
                    high=Decimal("2301"),
                    low=Decimal("2299"),
                    close=Decimal("2300.5"),
                    tick_volume=100,
                    is_complete=True,
                )
            )
        db.commit()

        profile = build_data_profile(
            db,
            SimpleNamespace(
                market_feed_id=feed.id,
                date_from=datetime(2026, 1, 2, 21, 0, tzinfo=UTC),
                date_to=datetime(2026, 1, 4, 22, 5, tzinfo=UTC),
            ),
            search_period=None,
            validation_period=None,
            search_total_candles=0,
            validation_total_candles=0,
        )

    assert profile["raw_m1_gap_count"] == 2
    assert profile["market_closed_m1_gap_count"] == 1
    assert profile["market_closed_m1_missing_minutes"] == 2880
    assert profile["detected_m1_gap_count"] == 1
    assert profile["detected_m1_missing_minutes"] == 2


def test_data_profile_reports_atr_quantiles_for_search_and_validation_periods() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    split = start + timedelta(minutes=20)
    end = split + timedelta(minutes=20)
    with SessionLocal() as db:
        feed = MarketFeed(
            provider="oanda",
            environment="practice",
            canonical_symbol="XAUUSD",
            provider_symbol="XAU_USD",
        )
        db.add(feed)
        db.flush()
        db.add(
            InstrumentSpecification(
                market_feed_id=feed.id,
                canonical_symbol="XAUUSD",
                provider_symbol="XAU_USD",
                display_precision=1,
                pip_location=-1,
                point=Decimal("0.1"),
                source="oanda",
                provider_metadata={},
            )
        )
        for index in range(40):
            half_range = Decimal("1") if index < 20 else Decimal("2")
            db.add(
                Candle(
                    market_feed_id=feed.id,
                    symbol="XAUUSD",
                    timeframe="M1",
                    opened_at=start + timedelta(minutes=index),
                    source="oanda",
                    open=Decimal("100"),
                    high=Decimal("100") + half_range,
                    low=Decimal("100") - half_range,
                    close=Decimal("100"),
                    tick_volume=100,
                    is_complete=True,
                )
            )
        db.commit()

        profile = build_data_profile(
            db,
            SimpleNamespace(
                market_feed_id=feed.id,
                date_from=start,
                date_to=end,
                config_snapshot={"strategy": {"parameters": {"atr_period": 3}}},
            ),
            search_period=(start, split),
            validation_period=(split, end),
            search_total_candles=20,
            validation_total_candles=20,
        )

    quantiles = profile["atr_quantiles"]
    assert quantiles["period"] == 3
    assert quantiles["unit"] == "points"
    assert quantiles["search"] == {
        "count": 17,
        "q05": 20,
        "q10": 20,
        "q25": 20,
        "q50": 20,
        "q75": 20,
        "q90": 20,
        "q95": 20,
    }
    assert quantiles["validation"] == {
        "count": 17,
        "q05": 40,
        "q10": 40,
        "q25": 40,
        "q50": 40,
        "q75": 40,
        "q90": 40,
        "q95": 40,
    }


def test_compute_balanced_score_penalizes_drawdown_and_low_trade_count() -> None:
    summary = {"net_pnl": "120", "max_drawdown": "20", "total_trades": 2}
    assert compute_balanced_score(summary) == Decimal("-1310")


def test_compute_balanced_score_heavily_penalizes_one_trade_candidate() -> None:
    summary = {"net_pnl": "-20.35113984", "max_drawdown": "20.35113984", "total_trades": 1}
    assert compute_balanced_score(summary) == Decimal("-1500.877849600")


def test_compute_balanced_score_rejects_candidate_without_trades() -> None:
    summary = {"net_pnl": "0", "max_drawdown": "0", "total_trades": 0}
    assert compute_balanced_score(summary) == Decimal("-99999")


def test_backtest_diagnostics_compacts_trade_behavior() -> None:
    diagnostics = build_backtest_diagnostics(
        {
            "direction_breakdown": {"BUY": {"trades": 2, "net_pnl": "10"}},
            "close_reason_counts": {"TAKE_PROFIT": 1, "STOP_LOSS": 1},
            "expectancy_r": "0.25",
            "total_r": "0.5",
            "trade_sortino": "1.2",
            "max_drawdown_pct": "2.5",
            "average_duration_seconds": "180",
        },
        {"NO_TRADE": 20, "TAKE_PROFIT": 1},
    )

    assert diagnostics["direction_breakdown"]["BUY"]["trades"] == 2
    assert diagnostics["close_reason_counts"]["STOP_LOSS"] == 1
    assert diagnostics["reason_counts"]["NO_TRADE"] == 20
    assert diagnostics["trade_quality"]["expectancy_r"] == "0.25"


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
    assert sampled["fast_ema_period"] < sampled["medium_ema_period"] < sampled["slow_ema_period"]


def test_sample_parameters_respects_independent_rsi_band_bounds() -> None:
    sampled = sample_parameters(
        BoundaryTrial(),
        search_space=[
            {"name": "sell_rsi_max", "type": "number", "minimum": 40, "maximum": 60},
            {"name": "sell_rsi_min", "type": "number", "minimum": 20, "maximum": 40},
            {"name": "buy_rsi_max", "type": "number", "minimum": 60, "maximum": 80},
            {"name": "buy_rsi_min", "type": "number", "minimum": 40, "maximum": 60},
        ],
        defaults={},
    )

    assert sampled["buy_rsi_min"] <= sampled["buy_rsi_max"]
    assert sampled["sell_rsi_min"] <= sampled["sell_rsi_max"]


def test_ema_atr_pullback_continuation_search_samples_are_always_valid() -> None:
    from goldie_domain import BotConfiguration, get_strategy

    strategy = get_strategy("ema_atr_pullback_continuation")
    defaults = strategy.parameters_model().model_dump(mode="json")
    config = BotConfiguration.model_validate(
        {
            "strategy": {
                "name": "ema_atr_pullback_continuation",
                "parameters": defaults,
            }
        }
    )
    search_space = build_search_space(config)

    for index in range(101):
        sampled = sample_parameters(
            FractionTrial(index / 100),
            search_space=search_space,
            defaults=defaults,
        )
        strategy.parameters_model.model_validate(sampled)


def test_bb_squeeze_breakout_search_space_matches_candidate_ranges() -> None:
    from goldie_domain import BotConfiguration, get_strategy

    strategy = get_strategy("bb_squeeze_breakout")
    defaults = strategy.parameters_model().model_dump(mode="json")
    config = BotConfiguration.model_validate(
        {
            "strategy": {
                "name": "bb_squeeze_breakout",
                "parameters": defaults,
            }
        }
    )
    search_space = build_search_space(config)
    by_name = {item["name"]: item for item in search_space}

    assert by_name["bollinger_period"]["minimum"] == 20
    assert by_name["bollinger_period"]["maximum"] == 60
    assert by_name["bollinger_deviations"]["minimum"] == "1.8"
    assert by_name["bollinger_deviations"]["maximum"] == "2.5"
    assert by_name["squeeze_lookback"]["minimum"] == 20
    assert by_name["squeeze_lookback"]["maximum"] == 80
    assert by_name["max_squeeze_width_points"]["minimum"] == "50"
    assert by_name["max_squeeze_width_points"]["maximum"] == "180"
    assert by_name["breakout_points"]["minimum"] == "0"
    assert by_name["breakout_points"]["maximum"] == "20"
    assert by_name["momentum_period"]["minimum"] == 5
    assert by_name["momentum_period"]["maximum"] == 24
    assert by_name["min_momentum_points"]["minimum"] == "0"
    assert by_name["min_momentum_points"]["maximum"] == "80"
    assert by_name["atr_period"]["minimum"] == 10
    assert by_name["atr_period"]["maximum"] == 40
    assert by_name["min_atr_points"]["minimum"] == "0"
    assert by_name["min_atr_points"]["maximum"] == "50"
    assert by_name["max_atr_points"]["minimum"] == "50"
    assert by_name["max_atr_points"]["maximum"] == "300"
    assert by_name["squeeze_percentile"]["minimum"] == "5"
    assert by_name["squeeze_percentile"]["maximum"] == "35"
    assert by_name["trade_direction"]["choices"] == ["BOTH", "BUY_ONLY", "SELL_ONLY"]

    for index in range(101):
        sampled = sample_parameters(
            FractionTrial(index / 100),
            search_space=search_space,
            defaults=defaults,
        )
        strategy.parameters_model.model_validate(sampled)


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


class FractionTrial:
    def __init__(self, fraction: float) -> None:
        self.fraction = fraction

    def suggest_float(self, name: str, lower: float, upper: float) -> float:
        return lower + (upper - lower) * self.fraction

    def suggest_int(self, name: str, lower: int, upper: int) -> int:
        return lower + round((upper - lower) * self.fraction)

    def suggest_categorical(self, name: str, choices: list):
        return choices[round((len(choices) - 1) * self.fraction)]


def test_pine_search_space_and_samples_are_always_valid() -> None:
    from goldie_domain import BotConfiguration, get_strategy

    strategy = get_strategy("pine_bb_rsi_stoch")
    defaults = strategy.parameters_model().model_dump(mode="json")
    config = BotConfiguration.model_validate(
        {
            "strategy": {
                "name": "pine_bb_rsi_stoch",
                "parameters": defaults,
            }
        }
    )
    search_space = build_search_space(config)

    assert {item["name"] for item in search_space} == set(defaults)
    by_name = {item["name"]: item for item in search_space}
    assert by_name["bollinger_period"]["minimum"] == 20
    assert by_name["bollinger_period"]["maximum"] == 120
    assert by_name["rsi_oversold"]["minimum"] == "20"
    assert by_name["rsi_oversold"]["maximum"] == "40"
    assert by_name["rsi_overbought"]["minimum"] == "60"
    assert by_name["rsi_overbought"]["maximum"] == "80"
    assert by_name["stochastic_oversold"]["minimum"] == "10"
    assert by_name["stochastic_oversold"]["maximum"] == "30"
    assert by_name["stochastic_overbought"]["minimum"] == "70"
    assert by_name["stochastic_overbought"]["maximum"] == "90"
    assert by_name["trade_direction"]["choices"] == ["BOTH", "BUY_ONLY", "SELL_ONLY"]
    for index in range(101):
        sampled = sample_parameters(
            FractionTrial(index / 100),
            search_space=search_space,
            defaults=defaults,
        )
        strategy.parameters_model.model_validate(sampled)


def test_llm_context_v3_compacts_trials_and_aggregates_best_trades() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        optimization = OptimizationRun(
            bot_id=uuid4(),
            config_version_id=uuid4(),
            market_feed_id=uuid4(),
            run_id=uuid4(),
            status="SUCCEEDED",
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 1, 2, tzinfo=UTC),
            n_trials=4,
            objective="BALANCED",
            initial_capital=Decimal("10000"),
            fill_mode="simulated",
            fee_maker=Decimal("0"),
            fee_taker=Decimal("0"),
            taker_slippage=Decimal("0"),
            slippage_small=Decimal("0"),
            slippage_medium=Decimal("0"),
            medium_impact=Decimal("0"),
            impact_model="sqrt",
            model_sqrt_limit=Decimal("1"),
            limit_fill_timeout_s=30,
            min_qty_threshold=Decimal("0"),
            min_qty_check=True,
            config_snapshot={"strategy": {"name": "ema_atr_pullback_continuation"}},
            progress={},
            best_candidate={},
            summary={},
        )
        db.add(optimization)
        db.flush()
        trade_counts = [0, 3, 6, 30]
        trials = []
        for index, trade_count in enumerate(trade_counts):
            trial = OptimizationTrial(
                optimization_run_id=optimization.id,
                trial_number=index,
                phase="STRATEGY_SEARCH" if index < 2 else "FIXED_CONFIG_VALIDATION",
                config_overrides={},
                status="SUCCEEDED",
                sampled_parameters={"fast_ema_period": 5 + index},
                score=Decimal(index),
                metrics={
                    "diagnostics": {
                        "condition_pass_counts": {
                            "volatility_ok": {"evaluated": 10, "passed": index}
                        }
                    }
                },
                summary={"total_trades": trade_count},
            )
            db.add(trial)
            db.flush()
            trials.append(trial)
            for trade_index in range(trade_count):
                opened_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(
                    minutes=trade_index
                )
                db.add(
                    OptimizationTrialTrade(
                        trial_id=trial.id,
                        direction="BUY",
                        signal_reason="EMA_ATR_PULLBACK_CONTINUATION_BUY",
                        signal_at=opened_at,
                        opened_at=opened_at,
                        closed_at=opened_at + timedelta(minutes=1),
                        entry_price=Decimal("1.10000"),
                        exit_price=Decimal("1.10100"),
                        stop_loss=Decimal("1.09900"),
                        take_profit=Decimal("1.10200"),
                        close_reason="TAKE_PROFIT",
                        gross_pnl=Decimal("10"),
                        commission=Decimal("0"),
                        net_pnl=Decimal("10"),
                        pnl_points=Decimal("10"),
                        r_multiple=Decimal("1"),
                        mfe_points=Decimal("12"),
                        mae_points=Decimal("3"),
                        duration_seconds=60,
                        session={
                            "timezone": "UTC",
                            "local_opened_at": opened_at.isoformat(),
                            "window_start": "00:00:00",
                            "window_end": "23:59:59",
                        },
                    )
                )
        db.commit()

        payload = build_llm_context(db, optimization)
        deleted_trial_id = trials[1].id
        db.delete(trials[1])
        db.commit()
        remaining_deleted_trial_trades = (
            db.query(OptimizationTrialTrade)
            .filter_by(trial_id=deleted_trial_id)
            .count()
        )

    assert payload["schema_version"] == "goldie.optimization-llm-context.v3"
    assert "trials" not in payload
    assert payload["best_candidate"]["trial_number"] == 3
    assert len(payload["top_trials"]) == 2
    assert len(payload["validation_winners"]) == 2
    assert len(payload["worst_trials"]) == 2
    assert payload["condition_pass_counts"]["overall"]["volatility_ok"] == {
        "evaluated": 40,
        "passed": 6,
    }
    assert payload["parameter_stability"]["distributions"]["fast_ema_period"][
        "unique_values"
    ] == 2
    assert payload["monthly_breakdown"]["2026-01"]["trades"] == 30
    assert payload["direction_breakdown"]["BUY"]["trades"] == 30
    assert payload["close_reason_counts"] == {"TAKE_PROFIT": 30}
    assert payload["mfe_mae_quantiles"]["mfe_points"]["p50"] == 12
    assert payload["mfe_mae_quantiles"]["mae_points"]["p50"] == 3
    assert payload["duration_quantiles"]["seconds"]["p50"] == 60
    assert all("trades" not in trial for trial in payload["top_trials"])
    assert remaining_deleted_trial_trades == 0


def test_optimization_api_and_execution_flow(monkeypatch) -> None:
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
                "n_trials": 12,
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

        import goldie_api.optimizations as optimization_module

        committed_progress = []
        real_commit_timed = optimization_module._commit_timed

        def record_commit(db, timings) -> None:
            real_commit_timed(db, timings)
            stored = db.get(OptimizationRun, optimization_id)
            committed_progress.append((stored.progress or {}).get("completed_trials", 0))

        monkeypatch.setattr(optimization_module, "_commit_timed", record_commit)
        real_run_stream = optimization_module.BacktestEngine.run_stream
        backtest_calls = 0

        def fail_selected_backtests(engine, *args, **kwargs):
            nonlocal backtest_calls
            backtest_calls += 1
            if backtest_calls in {1, 13}:
                raise RuntimeError("intentional trial failure")
            return real_run_stream(engine, *args, **kwargs)

        monkeypatch.setattr(
            optimization_module.BacktestEngine,
            "run_stream",
            fail_selected_backtests,
        )
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
        timings = detail.json()["summary"]["timings"]
        assert set(timings) == {
            "candle_load_seconds",
            "optuna_sampling_seconds",
            "backtest_seconds",
            "database_commit_seconds",
            "total_seconds",
        }
        assert all(value >= 0 for value in timings.values())
        assert detail.json()["summary"]["failed_trials"] == 2
        assert detail.json()["summary"]["validation_failed_trials"] == 1
        assert detail.json()["summary"]["data_profile"]["search_candles"] == 320
        assert detail.json()["summary"]["data_profile"]["validation_candles"] == 80
        assert "robustness" in detail.json()["summary"]
        assert "parameter_insights" in detail.json()["summary"]
        assert "decision_context" in detail.json()["summary"]
        quality_gates = detail.json()["summary"]["research_quality_gates"]
        assert quality_gates["overall_status"] in {"PASS", "WARN", "BLOCK"}
        assert quality_gates["recommendation"]
        assert {gate["id"] for gate in quality_gates["gates"]} >= {
            "validation_trade_sample",
            "search_validation_degradation",
            "data_quality",
            "failed_trial_rate",
            "validation_robustness",
            "risk_profile",
        }
        assert committed_progress == [0, 5, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50, 55, 57]
        assert trials.status_code == 200
        assert trials.json()["total"] == 57
        strategy_trials = client.get(
            f"/api/v1/optimizations/{optimization_id}/trials?phase=STRATEGY_SEARCH",
            headers=headers,
        )
        validation_trials = client.get(
            f"/api/v1/optimizations/{optimization_id}/trials?phase=FIXED_CONFIG_VALIDATION",
            headers=headers,
        )
        assert strategy_trials.json()["total"] == 12
        assert validation_trials.json()["total"] == 45
        assert all(
            item["config_overrides"]["theoretical_trade"]
            for item in validation_trials.json()["items"]
        )
        assert detail.json()["best_candidate"]["fixed_config_overrides"]
        assert detail.json()["best_candidate"]["validation_score"]
        assert (
            detail.json()["summary"]["search_period"]["date_to"]
            == (detail.json()["summary"]["validation_period"]["date_from"])
        )
        trial_id = trials.json()["items"][0]["id"]
        trial_detail = client.get(
            f"/api/v1/optimizations/{optimization_id}/trials/{trial_id}",
            headers=headers,
        )
        assert trial_detail.status_code == 200
        assert trial_detail.json()["sampled_parameters"]
        trial_timings = trial_detail.json()["metrics"]["timings"]
        assert set(trial_timings) == {"sampling_seconds", "backtest_seconds"}
        assert all(value >= 0 for value in trial_timings.values())
        assert "return_pct" in trial_detail.json()["metrics"]
        assert "win_rate" in trial_detail.json()["metrics"]
        assert "profit_factor" in trial_detail.json()["metrics"]
        assert "diagnostics" in trial_detail.json()["metrics"]
        assert "fill_mode" not in trial_detail.json()["sampled_parameters"]
        assert "taker_slippage" not in trial_detail.json()["sampled_parameters"]
        assert "medium_impact" not in trial_detail.json()["sampled_parameters"]
        assert trial_detail.json()["optimization_run_id"] == str(optimization_id)
        failed_trial = next(item for item in trials.json()["items"] if item["status"] == "FAILED")
        assert failed_trial["metrics"]["timings"]["backtest_seconds"] >= 0
        exported = client.get(
            f"/api/v1/optimizations/{optimization_id}/export",
            headers=headers,
        )
        assert exported.status_code == 200
        export_body = exported.json()
        assert export_body["schema_version"] == "goldie.optimization-results.v2"
        assert export_body["optimization"]["id"] == str(optimization_id)
        assert len(export_body["trials"]) == 57
        assert export_body["analysis"]["phases"]["STRATEGY_SEARCH"]["trial_count"] == 12
        assert export_body["analysis"]["phases"]["FIXED_CONFIG_VALIDATION"][
            "trial_count"
        ] == 45
        assert export_body["analysis"]["parameter_distributions"]
        assert export_body["analysis"]["candidate_validation"]
        assert export_body["analysis"]["parameter_insights"]
        assert export_body["analysis"]["robustness"]
        assert export_body["analysis"]["research_quality_gates"] == quality_gates
        llm_context = client.get(
            f"/api/v1/optimizations/{optimization_id}/llm-context",
            headers=headers,
        )
        assert llm_context.status_code == 200
        llm_body = llm_context.json()
        assert llm_body["schema_version"] == "goldie.optimization-llm-context.v3"
        assert llm_body["top_trials"]
        assert llm_body["worst_trials"]
        assert llm_body["validation_winners"]
        assert "trials" not in llm_body
        assert llm_body["objective"]["trial_counts"]["phase"]["STRATEGY_SEARCH"] == 12
        assert llm_body["parameter_stability"]["insights"]
        assert llm_body["parameter_stability"]["distributions"]
        assert llm_body["parameter_stability"]["stable_candidates"]
        atr_quantiles = llm_body["data_quality"]["atr_quantiles"]
        assert atr_quantiles["period"] == 14
        assert atr_quantiles["unit"] == "points"
        assert set(atr_quantiles["search"]) == {
            "count",
            "q05",
            "q10",
            "q25",
            "q50",
            "q75",
            "q90",
            "q95",
        }
        assert atr_quantiles["search"]["count"] > 0
        assert atr_quantiles["validation"]["count"] > 0
        assert llm_body["research_quality_gates"] == quality_gates
        assert "equity_curve" not in str(llm_body["top_trials"])
        assert "equity_curve" not in str(llm_body["best_candidate"])
        assert len(json.dumps(llm_body).encode("utf-8")) < 300 * 1024
        successful_export_trial = next(
            item for item in export_body["trials"] if item["status"] == "SUCCEEDED"
        )
        assert "expectancy" in successful_export_trial["summary"]
        assert "direction_breakdown" in successful_export_trial["summary"]
        with SessionLocal() as db:
            stored_trials = (
                db.query(OptimizationTrial).filter_by(optimization_run_id=optimization_id).count()
            )
            assert stored_trials == 57


def test_research_quality_gates_block_weak_validation_sample_and_degradation() -> None:
    trials = [
        SimpleNamespace(
            status="SUCCEEDED",
            phase="FIXED_CONFIG_VALIDATION",
            summary={"total_trades": 2},
        ),
        SimpleNamespace(
            status="FAILED",
            phase="FIXED_CONFIG_VALIDATION",
            summary={},
        ),
    ]

    gates = build_research_quality_gates(
        trials,
        data_profile={
            "detected_m1_gap_count": 1,
            "incomplete_candles": 0,
        },
        robustness={
            "validated_candidate_count": 1,
            "average_score_degradation_pct": 90,
            "stable_candidates": [],
            "best_validation_candidates": [
                {
                    "validation_metrics": {
                        "max_drawdown_pct": 25,
                        "max_consecutive_losses": 9,
                    }
                }
            ],
        },
    )

    statuses = {gate["id"]: gate["status"] for gate in gates["gates"]}
    assert gates["overall_status"] == "BLOCK"
    assert statuses["validation_trade_sample"] == "BLOCK"
    assert statuses["search_validation_degradation"] == "BLOCK"
    assert statuses["data_quality"] == "WARN"
    assert statuses["validation_robustness"] == "BLOCK"
    assert statuses["risk_profile"] == "BLOCK"


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


def test_optimization_fails_when_all_validation_trials_fail(monkeypatch) -> None:
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
            json={
                "name": "Failed validation bot",
                "mode": "SHADOW",
                "market_feed_id": feed_id,
            },
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
                "n_trials": 1,
            },
        )
        optimization_id = UUID(created.json()["id"])

        import goldie_api.optimizations as optimization_module

        real_run_stream = optimization_module.BacktestEngine.run_stream
        calls = 0

        def fail_validation(engine, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise RuntimeError("intentional validation failure")
            return real_run_stream(engine, *args, **kwargs)

        monkeypatch.setattr(
            optimization_module,
            "build_fixed_config_pairs",
            lambda bot_config: [
                {
                    "theoretical_trade": {
                        "stop_loss_points": bot_config.theoretical_trade.stop_loss_points,
                        "take_profit_points": bot_config.theoretical_trade.take_profit_points,
                    }
                }
            ],
        )
        monkeypatch.setattr(
            optimization_module.BacktestEngine,
            "run_stream",
            fail_validation,
        )
        with SessionLocal() as db:
            optimization = db.get(OptimizationRun, optimization_id)
            optimization.status = "RUNNING"
            db.commit()
            execute_optimization(db, optimization_id)

        detail = client.get(f"/api/v1/optimizations/{optimization_id}", headers=headers)
        assert detail.json()["status"] == "FAILED"
        assert detail.json()["summary"]["validation_failed_trials"] == 1
        assert "No successful fixed config validation trials" in detail.json()["error"]
