import React from "react";

import type { Performance, PerformanceBreakdown, ShadowTrade } from "@/lib/types";
import { MarketChart } from "./market-chart";

export function PerformancePanel({
  performance,
  trades,
}: {
  performance: Performance | undefined;
  trades: ShadowTrade[];
}) {
  if (!performance) return <div className="panel">Loading shadow performance...</div>;
  return (
    <div className="performance-stack">
      <div className="theoretical-banner">
        SHADOW / THEORETICAL RESULTS. No broker orders were placed.
      </div>
      <div className="dashboard-grid">
        <Metric label="Closed trades" value={String(performance.closed_trades)} />
        <Metric label="Net P&L" value={money(performance.net_pnl)} />
        <Metric label="Win rate" value={percent(performance.win_rate)} />
        <Metric label="Profit factor" value={metric(performance.profit_factor)} />
        <Metric label="Expectancy" value={money(performance.expectancy)} />
        <Metric label="Total R" value={metric(performance.total_r)} />
        <Metric label="Max drawdown" value={money(performance.max_drawdown)} />
        <Metric label="Skipped" value={String(performance.skipped_trades)} />
        <Metric
          label="Average hold"
          value={
            performance.average_duration_seconds === null
              ? "--"
              : `${Math.round(performance.average_duration_seconds)}s`
          }
        />
        <div className="panel grid-span-2">
          <h2>Theoretical equity curve</h2>
          <MarketChart
            candles={performance.equity_curve.map((point) => ({
              opened_at: point.time,
              close: String(point.value),
            }))}
          />
        </div>
        <div className="panel">
          <h2>Skipped by reason</h2>
          <KeyValues values={performance.skipped_by_reason} />
        </div>
      </div>
      <div className="breakdown-grid">
        <Breakdown title="Direction" rows={performance.breakdown.direction} />
        <Breakdown title="Hour UTC" rows={performance.breakdown.hour_utc} />
        <Breakdown title="Run" rows={performance.breakdown.run} />
        <Breakdown title="Config version" rows={performance.breakdown.config_version} />
      </div>
      <DataTable
        empty="No shadow trades yet."
        headers={["Opened", "Side", "Status", "Result", "Exit", "P&L", "R", "MFE", "MAE"]}
        rows={trades.map((trade) => [
          trade.opened_at ? new Date(trade.opened_at).toLocaleString() : "--",
          trade.direction,
          trade.status,
          trade.result ?? trade.skip_reason ?? "--",
          trade.close_reason ?? "--",
          trade.net_pnl ?? "--",
          trade.r_multiple ?? "--",
          trade.mfe_points,
          trade.mae_points,
        ])}
      />
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: PerformanceBreakdown[] }) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      <DataTable
        empty="No closed trades."
        headers={["Group", "Trades", "Net P&L"]}
        rows={rows.map((row) => [
          row.key.length > 12 ? row.key.slice(0, 8) : row.key,
          String(row.trades),
          money(row.net_pnl),
        ])}
      />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function KeyValues({ values }: { values: Record<string, number> }) {
  if (!Object.keys(values).length) return <p className="muted">No skipped signals.</p>;
  return (
    <dl className="key-values">
      {Object.entries(values).map(([key, value]) => (
        <div key={key}>
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function DataTable({
  headers,
  rows,
  empty,
}: {
  headers: string[];
  rows: string[][];
  empty: string;
}) {
  if (!rows.length) {
    return (
      <div className="empty-state">
        <p>{empty}</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function money(value: string | number | null | undefined): string {
  return formatDecimal(value, 2);
}

function percent(value: string | number | null | undefined): string {
  const formatted = formatDecimal(value, 1);
  return formatted === "--" ? formatted : `${formatted}%`;
}

function metric(value: string | number | null | undefined): string {
  return formatDecimal(value, 2);
}

function formatDecimal(
  value: string | number | null | undefined,
  digits: number,
): string {
  if (value === null || value === undefined) return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "--";
}
