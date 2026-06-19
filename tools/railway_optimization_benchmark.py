import argparse
import copy
import json
import os
from datetime import timedelta
from decimal import Decimal

import psycopg


def connect():
    database_url = os.getenv("DATABASE_PUBLIC_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_PUBLIC_URL or DATABASE_URL is required")
    return psycopg.connect(database_url)


def inventory() -> None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            select
                mf.id,
                mf.canonical_symbol,
                mf.provider_symbol,
                count(c.id),
                min(c.opened_at),
                max(c.opened_at)
            from market_feeds mf
            left join candles c
                on c.market_feed_id = mf.id
                and c.timeframe = 'M1'
                and c.is_complete = true
            group by mf.id, mf.canonical_symbol, mf.provider_symbol
            order by count(c.id) desc
            """
        )
        feeds = [
            {
                "id": str(row[0]),
                "symbol": row[1],
                "provider_symbol": row[2],
                "candles": row[3],
                "from": row[4],
                "to": row[5],
            }
            for row in cursor.fetchall()
        ]
        cursor.execute(
            """
            select
                b.id,
                b.name,
                b.market_feed_id,
                cv.id,
                cv.status,
                cv.config
            from bots b
            join config_versions cv on cv.bot_id = b.id
            where cv.status in ('ACTIVE', 'VALIDATED', 'SUPERSEDED')
            order by b.created_at, cv.version desc
            """
        )
        configs = [
            {
                "bot_id": str(row[0]),
                "bot": row[1],
                "feed_id": str(row[2]),
                "config_id": str(row[3]),
                "status": row[4],
                "strategy": row[5]["strategy"]["name"],
            }
            for row in cursor.fetchall()
        ]
    print(json.dumps({"feeds": feeds, "configs": configs}, default=str))


def report() -> None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            select
                o.id,
                o.status,
                o.n_trials,
                o.started_at,
                o.completed_at,
                o.progress,
                o.summary,
                o.config_snapshot,
                mf.canonical_symbol
            from optimization_runs o
            join market_feeds mf on mf.id = o.market_feed_id
            order by o.created_at desc
            limit 30
            """
        )
        rows = [
            {
                "id": str(row[0]),
                "status": row[1],
                "n_trials": row[2],
                "started_at": row[3],
                "completed_at": row[4],
                "progress": row[5],
                "duration_seconds": (row[6] or {}).get("duration_seconds"),
                "strategy": row[7]["strategy"]["name"],
                "symbol": row[8],
            }
            for row in cursor.fetchall()
        ]
    print(json.dumps(rows, default=str))


def enqueue() -> None:
    database_url = os.getenv("DATABASE_PUBLIC_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_PUBLIC_URL or DATABASE_URL is required")
    os.environ["DATABASE_URL"] = database_url

    from goldie_api.db import SessionLocal
    from goldie_api.models import (
        Bot,
        Candle,
        ConfigVersion,
        MarketFeed,
        OptimizationRun,
        Run,
    )
    from goldie_domain import get_strategy, strategy_catalog
    from sqlalchemy import func, select

    matrix = {
        "EURUSD": [entry["name"] for entry in strategy_catalog()],
        "USDJPY": ["bb_ema_rsi_mean_reversion"],
        "USDCHF": ["bb_ema_rsi_mean_reversion"],
    }
    created = []
    with SessionLocal() as db:
        active = db.scalar(
            select(func.count(OptimizationRun.id)).where(
                OptimizationRun.status.in_(("PENDING", "RUNNING", "CANCEL_REQUESTED"))
            )
        )
        if active:
            raise SystemExit(f"Refusing to enqueue while {active} optimization(s) are active")

        for symbol, strategy_names in matrix.items():
            feed = db.scalar(
                select(MarketFeed).where(MarketFeed.canonical_symbol == symbol)
            )
            if feed is None:
                raise SystemExit(f"Missing feed: {symbol}")
            bounds = db.execute(
                select(func.min(Candle.opened_at), func.max(Candle.opened_at)).where(
                    Candle.market_feed_id == feed.id,
                    Candle.timeframe == "M1",
                    Candle.is_complete.is_(True),
                )
            ).one()
            if bounds[0] is None or bounds[1] is None:
                raise SystemExit(f"No completed M1 candles for {symbol}")

            configs = list(
                db.execute(
                    select(Bot, ConfigVersion)
                    .join(ConfigVersion, ConfigVersion.bot_id == Bot.id)
                    .where(
                        Bot.market_feed_id == feed.id,
                        ConfigVersion.status == "ACTIVE",
                    )
                    .order_by(ConfigVersion.created_at.desc())
                )
            )
            if not configs:
                raise SystemExit(f"No active bot configuration for {symbol}")

            for strategy_name in strategy_names:
                matching = next(
                    (
                        row
                        for row in configs
                        if row.ConfigVersion.config["strategy"]["name"] == strategy_name
                    ),
                    configs[0],
                )
                bot = matching.Bot
                config_version = matching.ConfigVersion
                snapshot = copy.deepcopy(config_version.config)
                if snapshot["strategy"]["name"] != strategy_name:
                    strategy = get_strategy(strategy_name)
                    snapshot["strategy"] = {
                        "name": strategy_name,
                        "parameters": strategy.parameters_model().model_dump(mode="json"),
                    }
                run = Run(
                    bot_id=bot.id,
                    config_version_id=config_version.id,
                    mode="OPTIMIZATION",
                    status="QUEUED",
                )
                db.add(run)
                db.flush()
                optimization = OptimizationRun(
                    bot_id=bot.id,
                    config_version_id=config_version.id,
                    market_feed_id=feed.id,
                    run_id=run.id,
                    requested_by=None,
                    status="PENDING",
                    date_from=bounds[0],
                    date_to=bounds[1] + timedelta(minutes=1),
                    n_trials=100,
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
                    model_sqrt_limit=Decimal("1"),
                    limit_fill_timeout_s=1,
                    min_qty_threshold=Decimal("0"),
                    min_qty_check=False,
                    config_snapshot=snapshot,
                    progress={"completed_trials": 0, "total_trials": 100},
                    best_candidate={},
                    summary={},
                )
                db.add(optimization)
                db.flush()
                created.append(
                    {
                        "id": str(optimization.id),
                        "symbol": symbol,
                        "strategy": strategy_name,
                        "candles_from": bounds[0],
                        "candles_to": bounds[1],
                    }
                )
        db.commit()
    print(json.dumps(created, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inventory", "enqueue", "report"))
    args = parser.parse_args()
    if args.command == "inventory":
        inventory()
    elif args.command == "enqueue":
        enqueue()
    else:
        report()


if __name__ == "__main__":
    main()
