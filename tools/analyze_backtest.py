#!/usr/bin/env python3
"""
Small helper to analyze backtest JSON exports.

Usage (PowerShell):
  python .\tools\analyze_backtest.py .\exports\Backtests\backtest-xxx.json

The script prints counts by close reason, TIMEOUT share, duration stats,
MFE/MAE summaries and shows a few sample trades for inspection.
"""
import json
import sys
from collections import Counter
from statistics import mean, median
from decimal import Decimal


def to_num(v):
    try:
        return float(v)
    except Exception:
        return None


def summarize(trades):
    reasons = Counter()
    durations = []
    net_pnls = []
    mfe = []
    mae = []
    for t in trades:
        reasons[t.get("close_reason", "UNKNOWN")] += 1
        d = t.get("duration_seconds")
        if d is not None:
            durations.append(d)
        npnl = t.get("net_pnl")
        if npnl is not None:
            net_pnls.append(to_num(npnl))
        m = t.get("mfe_points")
        if m is not None:
            mfe.append(to_num(m))
        M = t.get("mae_points")
        if M is not None:
            mae.append(to_num(M))

    total = len(trades)
    print(f"Total trades: {total}")
    print("Close reasons:")
    for r, c in reasons.most_common():
        pct = c / total * 100 if total else 0
        print(f"  {r}: {c} ({pct:.1f}%)")

    def stats(name, arr):
        if not arr:
            print(f"{name}: none")
            return
        print(f"{name}: count={len(arr)} mean={mean(arr):.3f} median={median(arr):.3f} min={min(arr):.3f} max={max(arr):.3f}")

    stats("Duration_seconds", durations)
    stats("Net PnL", net_pnls)
    stats("MFE points", mfe)
    stats("MAE points", mae)

    # Show worst trades
    sorted_by_net = sorted(trades, key=lambda x: to_num(x.get("net_pnl") or 0))
    print("\nWorst 5 trades:")
    for t in sorted_by_net[:5]:
        print_sample_trade(t)

    print("\nBest 5 trades:")
    for t in sorted_by_net[-5:][::-1]:
        print_sample_trade(t)

    # Extra metrics for TIMEOUT trades
    timeout_trades = [t for t in trades if t.get("close_reason") == "TIMEOUT"]
    if timeout_trades:
        mfe_positive = sum(1 for t in timeout_trades if to_num(t.get("mfe_points") or 0) > 0)
        pct_mfe_positive = mfe_positive / len(timeout_trades) * 100
        # compute how many reached >=50% of TP distance (in points). We need to know point; try to infer from trade if possible
        reached_half_tp = 0
        assumed_point = 0.0001  # typical EURUSD point
        for t in timeout_trades:
            entry = to_num(t.get("entry_price"))
            tp = to_num(t.get("take_profit"))
            mfe_p = to_num(t.get("mfe_points") or 0)
            if entry is None or tp is None:
                continue
            tp_points = abs(tp - entry) / assumed_point
            if tp_points > 0 and mfe_p >= 0.5 * tp_points:
                reached_half_tp += 1
        pct_half_tp = reached_half_tp / len(timeout_trades) * 100
        print(f"\nTIMEOUT trades: {len(timeout_trades)}; MFE>0: {mfe_positive} ({pct_mfe_positive:.1f}%) ; reached >=50% TP (assume point={assumed_point}): {reached_half_tp} ({pct_half_tp:.1f}%)")


def print_sample_trade(t):
    s = (
        f"{t.get('opened_at')} -> {t.get('closed_at')} | dir={t.get('direction')} | reason={t.get('close_reason')} | "
        f"entry={t.get('entry_price')} exit={t.get('exit_price')} net_pnl={t.get('net_pnl')} duration_s={t.get('duration_seconds')} mfe={t.get('mfe_points')} mae={t.get('mae_points')}"
    )
    print("  " + s)


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_backtest.py <backtest.json>")
        sys.exit(2)
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support either top-level 'trades' or 'result' keys
    trades = data.get("trades") or data.get("result", {}).get("trades") or []
    # Print basic metadata if available
    for key in ("config", "instrument", "costs", "settings"):
        if key in data:
            print(f"{key}: {json.dumps(data[key], ensure_ascii=False)[:1000]}\n")
    if not trades and isinstance(data, dict):
        # In some export formats trades may be nested under 'payload' or similar
        for key in ("payload", "data", "backtest"):
            if key in data and isinstance(data[key], dict):
                trades = data[key].get("trades") or trades

    if not trades:
        print("No trades found in backtest JSON. Check file structure.")
        sys.exit(1)

    summarize(trades)


if __name__ == "__main__":
    main()
