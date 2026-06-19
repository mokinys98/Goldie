import argparse
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter


def configure_database(path: Path) -> None:
    os.environ.setdefault("JWT_SECRET", "benchmark-secret-that-is-longer-than-thirty-two-bytes")
    os.environ.setdefault("LOCAL_ADMIN_EMAIL", "admin@benchmark.local")
    os.environ.setdefault("LOCAL_ADMIN_PASSWORD", "benchmark-password")
    os.environ.setdefault("AGENT_SERVICE_TOKEN", "benchmark-agent-token")
    os.environ["DATABASE_URL"] = f"sqlite:///{path.as_posix()}"


def config_snapshot(symbol: str, strategy_name: str) -> dict:
    strategy_parameters = {
        "fast_ema_period": 9,
        "slow_ema_period": 21,
        "rsi_period": 14,
        "buy_rsi_max": "70",
        "sell_rsi_min": "30",
        "min_trend_points": "2",
        "require_crossover": False,
    }
    if strategy_name == "bb_ema_rsi_mean_reversion":
        strategy_parameters = {
            "bollinger_period": 20,
            "bollinger_deviations": "2",
            "rsi_period": 14,
            "buy_rsi_max": "45",
            "sell_rsi_min": "55",
            "atr_period": 14,
            "atr_stop_multiplier": "1.5",
            "require_touch_band": True,
            "fast_ema_period": 9,
            "slow_ema_period": 21,
            "max_trend_points": "30",
        }
    return {
        "market": {"symbol": symbol, "timeframe": "M1"},
        "strategy": {
            "name": strategy_name,
            "parameters": strategy_parameters,
        },
        "filters": {"max_spread_points": "30", "stale_after_seconds": 15},
        "session": {
            "timezone": "UTC",
            "start_time": "00:00:00",
            "end_time": "23:59:59",
        },
        "theoretical_trade": {
            "stop_loss_points": "20",
            "take_profit_points": "30",
            "risk_per_trade_pct": "0.25",
            "max_trade_duration_minutes": 5,
            "max_open_shadow_positions": 1,
        },
    }


def seed_database(
    *,
    db,
    models,
    symbol: str,
    provider_symbol: str,
    strategy_name: str,
    days: int,
    trials: int,
    batch_size: int,
) -> uuid.UUID:
    feed_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    config_id = uuid.uuid4()
    run_id = uuid.uuid4()
    optimization_id = uuid.uuid4()
    start = datetime(2025, 7, 1, tzinfo=UTC)
    total_candles = days * 24 * 60
    snapshot = config_snapshot(symbol, strategy_name)

    db.add_all(
        [
            models.MarketFeed(
                id=feed_id,
                provider="oanda",
                environment="practice",
                canonical_symbol=symbol,
                provider_symbol=provider_symbol,
                status="ACTIVE",
                details={},
            ),
            models.Bot(
                id=bot_id,
                name=f"Benchmark {symbol}",
                mode="SHADOW",
                market_feed_id=feed_id,
                config_overrides={},
            ),
            models.ConfigVersion(
                id=config_id,
                bot_id=bot_id,
                version=1,
                status="ACTIVE",
                config=snapshot,
                config_overrides={},
            ),
            models.Run(
                id=run_id,
                bot_id=bot_id,
                config_version_id=config_id,
                mode="OPTIMIZATION",
                status="RUNNING",
            ),
            models.InstrumentSpecification(
                market_feed_id=feed_id,
                canonical_symbol=symbol,
                provider_symbol=provider_symbol,
                display_precision=5,
                pip_location=-4,
                point=Decimal("0.0001"),
                minimum_trade_size=Decimal("1"),
                trade_units_precision=0,
                margin_rate=Decimal("0.0333"),
                source="benchmark",
                provider_metadata={},
            ),
            models.OptimizationRun(
                id=optimization_id,
                bot_id=bot_id,
                config_version_id=config_id,
                market_feed_id=feed_id,
                run_id=run_id,
                status="RUNNING",
                date_from=start,
                date_to=start + timedelta(days=days),
                n_trials=trials,
                objective="BALANCED",
                initial_capital=Decimal("10000"),
                fill_mode="perfect",
                fee_maker=Decimal("0"),
                fee_taker=Decimal("0"),
                taker_slippage=Decimal("0"),
                slippage_small=Decimal("0"),
                slippage_medium=Decimal("0"),
                medium_impact=Decimal("0"),
                impact_model="sqrt",
                model_sqrt_limit=Decimal("1.0"),
                limit_fill_timeout_s=1,
                min_qty_threshold=Decimal("0"),
                min_qty_check=False,
                config_snapshot=snapshot,
                progress={},
                best_candidate={},
                summary={},
            ),
        ]
    )
    db.commit()

    base = Decimal("1.10000")
    batch = []
    for index in range(total_candles):
        offset = Decimal(index % 100) / Decimal("100000")
        opened_at = start + timedelta(minutes=index)
        batch.append(
            {
                "id": uuid.uuid4(),
                "market_feed_id": feed_id,
                "symbol": symbol,
                "timeframe": "M1",
                "opened_at": opened_at,
                "source": "benchmark",
                "open": base + offset,
                "high": base + Decimal("0.00030") + offset,
                "low": base - Decimal("0.00030") + offset,
                "close": base + Decimal("0.00010") + offset,
                "tick_volume": 100,
                "is_complete": True,
            }
        )
        if len(batch) >= batch_size:
            db.bulk_insert_mappings(models.Candle, batch)
            db.commit()
            batch.clear()
    if batch:
        db.bulk_insert_mappings(models.Candle, batch)
        db.commit()

    return optimization_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=".benchmark-optuna-worker.db")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--provider-symbol", default="EUR_USD")
    parser.add_argument(
        "--strategy",
        choices=("ema_rsi", "bb_ema_rsi_mean_reversion"),
        default="ema_rsi",
    )
    parser.add_argument("--days", type=int, default=349)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--max-seconds", type=float, default=120)
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()

    database_path = Path(args.database).resolve()
    if args.reset and database_path.exists():
        workspace = Path.cwd().resolve()
        if workspace not in (database_path, *database_path.parents):
            raise SystemExit(f"Refusing to remove database outside workspace: {database_path}")
        database_path.unlink()

    configure_database(database_path)

    from goldie_api import models
    from goldie_api.db import Base, SessionLocal, engine
    from goldie_api.optimizations import execute_optimization

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        optimization_id = seed_database(
            db=db,
            models=models,
            symbol=args.symbol,
            provider_symbol=args.provider_symbol,
            strategy_name=args.strategy,
            days=args.days,
            trials=args.trials,
            batch_size=args.batch_size,
        )
        started = perf_counter()
        execute_optimization(db, optimization_id)
        elapsed = perf_counter() - started
        optimization = db.get(models.OptimizationRun, optimization_id)
        payload = {
            "symbol": args.symbol,
            "strategy": args.strategy,
            "days": args.days,
            "candles": args.days * 24 * 60,
            "trials": args.trials,
            "elapsed_seconds": round(elapsed, 3),
            "max_seconds": args.max_seconds,
            "status": optimization.status if optimization else None,
            "completed_trials": (optimization.summary or {}).get("completed_trials")
            if optimization
            else None,
            "failed_trials": (optimization.summary or {}).get("failed_trials")
            if optimization
            else None,
        }
        print(json.dumps(payload, sort_keys=True))
        if optimization is None or optimization.status != "SUCCEEDED":
            raise SystemExit("Optimization did not succeed")
        if elapsed > args.max_seconds:
            raise SystemExit(
                f"Benchmark took {elapsed:.3f}s; expected <= {args.max_seconds:.3f}s"
            )


if __name__ == "__main__":
    main()
