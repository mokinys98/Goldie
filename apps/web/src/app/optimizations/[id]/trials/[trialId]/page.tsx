"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { normalizeBotConfig } from "@/lib/config";
import type { OptimizationRun, OptimizationTrial } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function OptimizationTrialDetailPage() {
  const { id, trialId } = useParams<{ id: string; trialId: string }>();
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [appliedConfigId, setAppliedConfigId] = useState<string | null>(null);
  const run = useQuery({
    queryKey: ["optimization", id],
    queryFn: () => api<OptimizationRun>(`/api/v1/optimizations/${id}`),
  });
  const trial = useQuery({
    queryKey: ["optimization-trial", id, trialId],
    queryFn: () => api<OptimizationTrial>(`/api/v1/optimizations/${id}/trials/${trialId}`),
  });

  if (run.isLoading || trial.isLoading) {
    return <div className="panel">Loading trial...</div>;
  }
  if (run.error || !run.data) {
    return <div className="error-box">{run.error?.message ?? "Optimization unavailable"}</div>;
  }
  if (trial.error || !trial.data) {
    return <div className="error-box">{trial.error?.message ?? "Trial unavailable"}</div>;
  }

  const configSnapshot = normalizeBotConfig(run.data.config_snapshot);
  const diagnostics = trial.data.metrics.diagnostics as Record<string, unknown> | undefined;
  const canApplyTrialConfig = Boolean(
    !applyBusy
    && Object.keys(trial.data.sampled_parameters ?? {}).length,
  );

  async function applyTrialAsNewConfig() {
    if (!canApplyTrialConfig || !run.data || !trial.data) return;
    if (!window.confirm("Create and activate a new config from this trial?")) {
      return;
    }
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
            ...(trial.data.sampled_parameters ?? {}),
          },
        },
        theoretical_trade: {
          ...configSnapshot.theoretical_trade,
          ...(trial.data.config_overrides?.theoretical_trade ?? {}),
        },
      };
      const created = await api<{ id: string }>(`/api/v1/bots/${run.data.bot_id}/config-versions`, {
        method: "POST",
        body: JSON.stringify({ config: nextConfig }),
      });
      await api(`/api/v1/config-versions/${created.id}/validate`, { method: "POST" });
      await api(`/api/v1/config-versions/${created.id}/activate`, { method: "POST" });
      setAppliedConfigId(created.id);
    } catch (reason) {
      setApplyError(reason instanceof Error ? reason.message : "Could not apply trial config");
    } finally {
      setApplyBusy(false);
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">OPTIMIZATION TRIAL</span>
          <h1>Trial #{trial.data.trial_number}</h1>
          <p>
            ID {trial.data.id} | {trial.data.phase ?? "STRATEGY_SEARCH"} | {configSnapshot.strategy.name} | {configSnapshot.market.symbol}
          </p>
        </div>
        <div className="button-row">
          <StatusPill value={trial.data.status} />
          <button
            className="button button-primary"
            disabled={!canApplyTrialConfig}
            onClick={() => void applyTrialAsNewConfig()}
          >
            {applyBusy ? "Applying..." : "Apply config to strategy"}
          </button>
          <Link className="button button-secondary" href={`/optimizations/${id}`}>
            Back to run
          </Link>
        </div>
      </header>

      {trial.data.error && <div className="error-box">{trial.data.error}</div>}
      {applyError && <div className="error-box">{applyError}</div>}
      {appliedConfigId && (
        <div className="panel">
          New config created and activated.
          {" "}
          <Link className="table-link" href={`/bots/${run.data.bot_id}`}>
            Open bot
          </Link>
        </div>
      )}

      <div className="dashboard-grid collector-section">
        <Metric label="Score" value={trial.data.score ?? "--"} />
        <Metric label="Net P&L" value={String(trial.data.metrics.net_pnl ?? "--")} />
        <Metric label="Drawdown" value={String(trial.data.metrics.max_drawdown ?? "--")} />
        <Metric label="Trades" value={String(trial.data.metrics.total_trades ?? "--")} />
      </div>

      <div className="split-layout collector-section">
        <div className="panel">
          <h2>Found parameters</h2>
          {!Object.keys(trial.data.sampled_parameters ?? {}).length ? (
            <p className="muted">No sampled parameters stored.</p>
          ) : (
            <dl className="key-values">
              {Object.entries(trial.data.sampled_parameters).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
              ))}
            </dl>
          )}
        </div>

        <div className="panel">
          <h2>Base snapshot values</h2>
          <dl className="key-values">
            {Object.entries(configSnapshot.strategy.parameters).map(([key, value]) => (
              <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
            ))}
          </dl>
        </div>
        {trial.data.config_overrides?.theoretical_trade && (
          <div className="panel">
            <h2>Fixed config overrides</h2>
            <dl className="key-values">
              {Object.entries(trial.data.config_overrides.theoretical_trade).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>
              ))}
            </dl>
          </div>
        )}
      </div>

      <div className="split-layout collector-section">
        <div className="panel">
          <h2>Metrics</h2>
          {!Object.keys(trial.data.metrics ?? {}).length ? (
            <p className="muted">No metrics stored.</p>
          ) : (
            <dl className="key-values">
              {Object.entries(trial.data.metrics).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{renderValue(value)}</dd></div>
              ))}
            </dl>
          )}
        </div>

        {diagnostics && (
          <div className="panel">
            <h2>Diagnostics</h2>
            <pre className="code-block">{JSON.stringify(diagnostics, null, 2)}</pre>
          </div>
        )}

        <div className="panel">
          <h2>Backtest summary</h2>
          {!Object.keys(trial.data.summary ?? {}).length ? (
            <p className="muted">No summary stored.</p>
          ) : (
            <dl className="key-values">
              {Object.entries(trial.data.summary).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{renderValue(value)}</dd></div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "--";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}
