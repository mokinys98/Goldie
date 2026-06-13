import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Performance, ShadowTrade } from "@/lib/types";
import { PerformancePanel } from "@/components/performance-panel";

const emptyPerformance: Performance = {
  total_signals: 0,
  closed_trades: 0,
  open_trades: 0,
  skipped_trades: 0,
  win_rate: null,
  average_win: null,
  average_loss: null,
  net_pnl: 0,
  total_points: 0,
  total_r: 0,
  profit_factor: null,
  expectancy: null,
  expectancy_r: null,
  max_drawdown: 0,
  max_consecutive_wins: 0,
  max_consecutive_losses: 0,
  average_duration_seconds: null,
  skipped_by_reason: {},
  equity_curve: [],
  breakdown: {
    direction: [],
    hour_utc: [],
    run: [],
    config_version: [],
  },
};

function trade(overrides: Partial<ShadowTrade>): ShadowTrade {
  return {
    id: "outcome-1",
    signal_id: "signal-1",
    bot_id: "bot-1",
    run_id: "run-1",
    config_version_id: "config-1",
    direction: "BUY",
    status: "OPEN",
    result: null,
    close_reason: null,
    skip_reason: null,
    opened_at: "2026-06-11T10:00:00Z",
    closed_at: null,
    entry_price: "2350.20",
    exit_price: null,
    stop_loss: "2349.50",
    take_profit: "2351.20",
    volume: "0.08",
    risk_amount: "5.60",
    gross_pnl: null,
    net_pnl: null,
    pnl_points: null,
    r_multiple: null,
    mfe_points: "10",
    mae_points: "5",
    duration_seconds: null,
    ...overrides,
  };
}

describe("PerformancePanel", () => {
  it("renders an empty shadow result state", () => {
    render(<PerformancePanel performance={emptyPerformance} trades={[]} />);

    expect(screen.getByText("No shadow trades yet.")).toBeInTheDocument();
    expect(screen.getByText("SHADOW / THEORETICAL RESULTS. No broker orders were placed."))
      .toBeInTheDocument();
  });

  it("renders an active shadow position", () => {
    render(
      <PerformancePanel
        performance={{ ...emptyPerformance, total_signals: 1, open_trades: 1 }}
        trades={[trade({})]}
      />,
    );

    expect(screen.getByText("OPEN")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });

  it("renders a closed profitable result", () => {
    render(
      <PerformancePanel
        performance={{
          ...emptyPerformance,
          total_signals: 1,
          closed_trades: 1,
          win_rate: "100.00000000",
          net_pnl: "8.00000000",
          total_r: "1.43000000",
          equity_curve: [{ time: "2026-06-11T10:02:00Z", value: "8.00000000" }],
        }}
        trades={[
          trade({
            status: "CLOSED",
            result: "WIN",
            close_reason: "TAKE_PROFIT",
            closed_at: "2026-06-11T10:02:00Z",
            exit_price: "2351.20",
            gross_pnl: "8.00",
            net_pnl: "8.00",
            pnl_points: "100",
            r_multiple: "1.43",
            duration_seconds: 120,
          }),
        ]}
      />,
    );

    expect(screen.getByText("WIN")).toBeInTheDocument();
    expect(screen.getByText("TAKE_PROFIT")).toBeInTheDocument();
    expect(screen.getByText("100.0%")).toBeInTheDocument();
  });
});
