import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter

from goldie_domain import (
    BacktestCandle,
    BacktestCosts,
    BacktestEngine,
    BacktestInstrument,
    BotConfiguration,
    CandleInput,
)


def configuration() -> BotConfiguration:
    return BotConfiguration.model_validate(
        {
            "market": {"symbol": "XAUUSD", "timeframe": "M1"},
            "strategy": {
                "name": "ema_rsi",
                "parameters": {
                    "fast_ema_period": 9,
                    "slow_ema_period": 21,
                    "rsi_period": 14,
                    "buy_rsi_max": "70",
                    "sell_rsi_min": "30",
                    "min_trend_points": "10000",
                    "require_crossover": False,
                },
            },
            "filters": {"max_spread_points": "30", "stale_after_seconds": 15},
            "session": {
                "timezone": "UTC",
                "start_time": "00:00:00",
                "end_time": "23:59:59",
            },
            "theoretical_trade": {
                "stop_loss_points": "70",
                "take_profit_points": "100",
                "risk_per_trade_pct": "0.25",
                "max_trade_duration_minutes": 5,
                "max_open_shadow_positions": 1,
            },
        }
    )


def candles(total: int, *, optimized: bool):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    base = Decimal("2300")
    offsets = [Decimal(index) / Decimal("100") for index in range(100)]
    for index in range(total):
        offset = offsets[index % len(offsets)]
        values = {
            "opened_at": start + timedelta(minutes=index),
            "open": base + offset,
            "high": base + Decimal("1") + offset,
            "low": base - Decimal("1") + offset,
            "close": base + Decimal("0.5") + offset,
            "tick_volume": 100,
            "is_complete": True,
        }
        yield (
            BacktestCandle(**values)
            if optimized
            else CandleInput.model_construct(**values)
        )


def run(total: int, *, optimized: bool):
    instrument = BacktestInstrument(
        point=Decimal("0.01"),
        tick_size=Decimal("0.01"),
        tick_value=Decimal("0.01"),
        volume_min=Decimal("1"),
        volume_max=Decimal("1000000"),
        volume_step=Decimal("1"),
    )
    costs = BacktestCosts(
        spread_points=Decimal("2"),
        slippage_points=Decimal("1"),
        commission_per_trade=Decimal("0"),
    )
    started = perf_counter()
    result = BacktestEngine().run_stream(
        candles=candles(total, optimized=optimized),
        total_candles=total,
        config=configuration(),
        instrument=instrument,
        costs=costs,
        initial_capital=Decimal("10000"),
        use_prepared_strategy=optimized,
    )
    return perf_counter() - started, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--minimum-speedup", type=float, default=3.0)
    args = parser.parse_args()
    total = args.days * 24 * 60

    legacy_seconds, legacy = run(total, optimized=False)
    optimized_seconds, optimized = run(total, optimized=True)
    speedup = legacy_seconds / optimized_seconds
    print(
        {
            "candles": total,
            "legacy_seconds": round(legacy_seconds, 3),
            "optimized_seconds": round(optimized_seconds, 3),
            "speedup": round(speedup, 2),
            "results_equal": legacy == optimized,
        }
    )
    if legacy != optimized:
        raise SystemExit("Optimized result differs from legacy result")
    if speedup < args.minimum_speedup:
        raise SystemExit(
            f"Speedup {speedup:.2f}x is below required {args.minimum_speedup:.2f}x"
        )


if __name__ == "__main__":
    main()
