"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { normalizeBotConfig } from "@/lib/config";
import type { OptimizationRun, OptimizationTrialPage } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function OptimizationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [appliedConfigId, setAppliedConfigId] = useState<string | null>(null);
  const run = useQuery({
    queryKey: ["optimization", id],
    queryFn: () => api<OptimizationRun>(`/api/v1/optimizations/${id}`),
    refetchInterval: (query) =>
      ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(query.state.data?.status ?? "")
        ? 2000
        : false,
  });
  const trials = useQuery({
    queryKey: ["optimization-trials", id],
    queryFn: () => api<OptimizationTrialPage>(`/api/v1/optimizations/${id}/trials?limit=100`),
    refetchInterval:
      run.data && ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(run.data.status)
        ? 3000
        : false,
  });
  const data = run.data;
  if (run.isLoading) return <div className="panel">Loading optimization...</div>;
  if (run.error || !data) {
    return <div className="error-box">{run.error?.message ?? "Optimization unavailable"}</div>;
  }
  const configSnapshot = normalizeBotConfig(data.config_snapshot);
  const canCancel = ["PENDING", "RUNNING"].includes(data.status);
  const canApplyBest = Boolean(
    !applyBusy
    && Object.keys(data.best_candidate.sampled_parameters ?? {}).length,
  );

  async function cancel() {
    if (!window.confirm("Cancel this optimization?")) return;
    await api(`/api/v1/optimizations/${id}/cancel`, { method: "POST" });
    await client.invalidateQueries({ queryKey: ["optimization", id] });
  }

  async function applyBestAsNewConfig() {
    if (!canApplyBest || !data) return;
    if (!window.confirm("Create and activate a new config from the current best candidate?")) {
      return;
    }
    const current = data;
    setApplyBusy(true);
    setApplyError(null);
    setAppliedConfigId(null);
    try {
      const nextConfig = {
        ...configSnapshot,
        strategy: {
          ...configSnapshot.strategy,
          parameters: {
            ...configSnapshot.strategy.parameters,
            ...(current.best_candidate.sampled_parameters ?? {}),
          },
        },
      };
      const created = await api<{ id: string }>(`/api/v1/bots/${current.bot_id}/config-versions`, {
        method: "POST",
        body: JSON.stringify({ config: nextConfig }),
      });
      await api(`/api/v1/config-versions/${created.id}/validate`, { method: "POST" });
      await api(`/api/v1/config-versions/${created.id}/activate`, { method: "POST" });
      setAppliedConfigId(created.id);
    } catch (reason) {
      setApplyError(reason instanceof Error ? reason.message : "Could not apply best candidate");
    } finally {
      setApplyBusy(false);
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">OPTIMIZATION RESULT</span>
          <h1>{configSnapshot.market.symbol} M1</h1>
          <p>
            {configSnapshot.strategy.name} | {new Date(data.date_from).toLocaleString()}
            {" - "}{new Date(data.date_to).toLocaleString()}
          </p>
        </div>
        <div className="button-row">
          <StatusPill value={data.status} />
          <button
            className="button button-primary"
            disabled={!canApplyBest}
            onClick={() => void applyBestAsNewConfig()}
          >
            {applyBusy ? "Applying..." : "Apply best as new config"}
          </button>
          {canCancel && (
            <button className="button button-secondary" onClick={() => void cancel()}>
              Cancel
            </button>
          )}
        </div>
      </header>
      {data.error && <div className="error-box">{data.error}</div>}
      {applyError && <div className="error-box">{applyError}</div>}
      {appliedConfigId && (
        <div className="panel">
          New config created and activated.
          {" "}
          <Link className="table-link" href={`/bots/${data.bot_id}`}>
            Open bot
          </Link>
        </div>
      )}
      <div className="panel backtest-progress">
        <strong>Progress</strong>
        <progress
          max={data.progress.total_trials ?? data.n_trials}
          value={data.progress.completed_trials ?? 0}
        />
        <span>
          {data.progress.completed_trials ?? 0}
          {" / "}
          {data.progress.total_trials ?? data.n_trials}
          {" trials"}
        </span>
      </div>
      <div className="dashboard-grid collector-section">
        <Metric label="Best score" value={data.best_candidate.score ?? "--"} />
        <Metric
          label="Completed"
          value={data.summary.completed_trials ?? data.progress.successful_trials ?? 0}
        />
        <Metric
          label="Failed"
          value={data.summary.failed_trials ?? data.progress.failed_trials ?? 0}
        />
      </div>
      <div className="split-layout collector-section">
        <div className="panel">
          <h2>Best parameters</h2>
          {!Object.keys(data.best_candidate.sampled_parameters ?? {}).length ? (
            <p className="muted">No completed candidate yet.</p>
          ) : (
            <div className="key-values">
              {Object.entries(data.best_candidate.sampled_parameters ?? {}).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
              ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h2>Best candidate metrics</h2>
          {!Object.keys(data.best_candidate.metrics ?? {}).length ? (
            <p className="muted">No metrics yet.</p>
          ) : (
            <div className="key-values">
              {Object.entries(data.best_candidate.metrics ?? {}).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
              ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h2>Fixed config outside search</h2>
          <div className="key-values">
            <div><dt>session</dt><dd>{configSnapshot.session.timezone}</dd></div>
            <div>
              <dt>stop_loss_points</dt>
              <dd>{String(configSnapshot.theoretical_trade.stop_loss_points)}</dd>
            </div>
            <div>
              <dt>take_profit_points</dt>
              <dd>{String(configSnapshot.theoretical_trade.take_profit_points)}</dd>
            </div>
            <div>
              <dt>risk_per_trade_pct</dt>
              <dd>{String(configSnapshot.theoretical_trade.risk_per_trade_pct)}</dd>
            </div>
            <div>
              <dt>max_spread_points</dt>
              <dd>{String(configSnapshot.filters.max_spread_points)}</dd>
            </div>
          </div>
        </div>
      </div>
      <div className="panel collector-section">
        <h2>Top trials ({trials.data?.total ?? 0})</h2>
        {!trials.data?.items.length ? <p className="muted">No trials stored yet.</p> : (
          <div className="table-wrap borderless">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Trial</th>
                  <th>Status</th>
                  <th>Score</th>
                  <th>Net P&amp;L</th>
                  <th>Drawdown</th>
                  <th>Trades</th>
                </tr>
              </thead>
              <tbody>{trials.data.items.map((trial) => (
                <tr key={trial.id}>
                  <td>
                    <Link className="table-link" href={`/optimizations/${id}/trials/${trial.id}`}>
                      {trial.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{trial.trial_number}</td>
                  <td><StatusPill value={trial.status} /></td>
                  <td>{trial.score ?? "--"}</td>
                  <td>{String(trial.metrics.net_pnl ?? "--")}</td>
                  <td>{String(trial.metrics.max_drawdown ?? "--")}</td>
                  <td>{String(trial.metrics.total_trades ?? "--")}</td>
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
