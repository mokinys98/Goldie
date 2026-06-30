"use client";

import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, downloadAuthenticated } from "@/lib/api";
import { normalizeBotConfig } from "@/lib/config";
import { displayValue } from "@/lib/display";
import type { BacktestExperiment, BacktestTradePage } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function BacktestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const experiment = useQuery({
    queryKey: ["backtest", id],
    queryFn: () => api<BacktestExperiment>(`/api/v1/backtests/${id}`),
    refetchInterval: (query) =>
      ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(query.state.data?.status ?? "")
        ? 2000
        : false,
  });
  const trades = useQuery({
    queryKey: ["backtest-trades", id],
    queryFn: () => api<BacktestTradePage>(`/api/v1/backtests/${id}/trades?limit=500`),
    enabled: experiment.data?.status === "SUCCEEDED",
  });
  const data = experiment.data;
  if (experiment.isLoading) return <div className="panel">Loading backtest...</div>;
  if (experiment.error || !data) {
    return <div className="error-box">{experiment.error?.message ?? "Backtest unavailable"}</div>;
  }
  const configSnapshot = normalizeBotConfig(data.config_snapshot);
  const canCancel = ["PENDING", "RUNNING"].includes(data.status);

  async function cancel() {
    if (!window.confirm("Cancel this backtest?")) return;
    await api(`/api/v1/backtests/${id}/cancel`, { method: "POST" });
    await client.invalidateQueries({ queryKey: ["backtest", id] });
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">BACKTEST RESULT</span>
          <h1>{configSnapshot.market.symbol} M1</h1>
          <p>
            {configSnapshot.strategy.name} | {new Date(data.date_from).toLocaleString()}
            {" - "}{new Date(data.date_to).toLocaleString()}
          </p>
        </div>
        <div className="button-row">
          <StatusPill value={data.status} />
          {canCancel && <button className="button button-secondary" onClick={() => void cancel()}>Cancel</button>}
          <button className="button button-secondary" onClick={() => void downloadAuthenticated(`/api/v1/backtests/${id}/export?format=csv`, `backtest-${id}.csv`)}>CSV</button>
          <button className="button button-secondary" onClick={() => void downloadAuthenticated(`/api/v1/backtests/${id}/export?format=json`, `backtest-${id}.json`)}>JSON</button>
        </div>
      </header>
      {data.error && <div className="error-box">{data.error}</div>}
      <div className="panel backtest-progress">
        <strong>Progress</strong>
        <progress max={data.progress.total ?? 1} value={data.progress.processed ?? 0} />
        <span>{data.progress.processed ?? 0} / {data.progress.total ?? 0} candles</span>
      </div>
      <div className="dashboard-grid collector-section">
        <Metric label="Trades" value={data.summary.total_trades ?? "--"} />
        <Metric label="Win rate" value={percent(data.summary.win_rate)} />
        <Metric label="Net P&L" value={data.summary.net_pnl ?? "--"} />
        <Metric label="Profit factor" value={data.summary.profit_factor ?? "--"} />
        <Metric label="Max drawdown" value={data.summary.max_drawdown ?? "--"} />
        <Metric label="Consecutive losses" value={data.summary.max_consecutive_losses ?? "--"} />
      </div>
      <div className="split-layout collector-section">
        <div className="panel">
          <h2>Equity curve</h2>
          <EquityCurve points={data.summary.equity_curve ?? []} />
        </div>
        <div className="panel">
          <h2>Decision reasons</h2>
          {!Object.keys(data.reason_counts).length ? <p className="muted">No decisions yet.</p> : (
            <div className="key-values">
              {Object.entries(data.reason_counts).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{value}</dd></div>
              ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h2>Execution model</h2>
          <div className="key-values">
            <div><dt>fee_maker</dt><dd>{String(data.fee_maker)}</dd></div>
            <div><dt>fee_taker</dt><dd>{String(data.fee_taker)}</dd></div>
            <div><dt>slippage_small</dt><dd>{String(data.slippage_small)}</dd></div>
            <div><dt>slippage_medium</dt><dd>{String(data.slippage_medium)}</dd></div>
            <div><dt>impact_model</dt><dd>{data.impact_model}</dd></div>
            <div><dt>limit_fill_timeout_s</dt><dd>{data.limit_fill_timeout_s}</dd></div>
            <div><dt>min_qty_check</dt><dd>{String(data.min_qty_check)}</dd></div>
          </div>
        </div>
        <div className="panel">
          <h2>Strategy parameters</h2>
          <div className="key-values">
            {Object.entries(configSnapshot.strategy.parameters).map(([key, value]) => (
              <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>
            ))}
          </div>
        </div>
      </div>
      <div className="panel collector-section">
        <h2>Trades ({trades.data?.total ?? 0})</h2>
        {!trades.data?.items.length ? <p className="muted">No completed trades.</p> : (
          <div className="table-wrap borderless">
            <table>
              <thead><tr><th>Opened</th><th>Direction</th><th>Exit</th><th>Reason</th><th>Net P&L</th><th>R</th><th>MFE / MAE</th></tr></thead>
              <tbody>{trades.data.items.map((trade) => (
                <tr key={trade.id}>
                  <td>{new Date(trade.opened_at).toLocaleString()}</td>
                  <td>{trade.direction}</td><td>{trade.exit_price}</td>
                  <td>{trade.close_reason}</td><td>{trade.net_pnl}</td>
                  <td>{trade.r_multiple}</td><td>{trade.mfe_points} / {trade.mae_points}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function percent(value: string | number | null | undefined): string {
  return value === null || value === undefined ? "--" : `${Number(value).toFixed(2)}%`;
}

function EquityCurve({ points }: { points: Array<{ time: string; value: string | number }> }) {
  if (points.length < 2) return <div className="chart-empty">Not enough trades for a curve.</div>;
  const values = points.map((point) => Number(point.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const path = values.map((value, index) => {
    const x = (index / (values.length - 1)) * 100;
    const y = 100 - ((value - min) / range) * 90 - 5;
    return `${index ? "L" : "M"} ${x} ${y}`;
  }).join(" ");
  return (
    <svg className="equity-chart" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Equity curve">
      <path d={path} fill="none" stroke="var(--gold-bright)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
