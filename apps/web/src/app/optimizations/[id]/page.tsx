"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, downloadAuthenticated } from "@/lib/api";
import { displayJson, displayValue } from "@/lib/display";
import { normalizeBotConfig } from "@/lib/config";
import type {
  Bot,
  OptimizationLlmContext,
  OptimizationResultsExport,
  OptimizationRun,
  OptimizationTrialPage,
  ResearchQualityGates,
} from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function OptimizationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [appliedConfigId, setAppliedConfigId] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const downloadMenuRef = useRef<HTMLDetailsElement>(null);
  const run = useQuery({
    queryKey: ["optimization", id],
    queryFn: () => api<OptimizationRun>(`/api/v1/optimizations/${id}`),
    refetchInterval: (query) =>
      ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(query.state.data?.status ?? "")
        ? 2000
        : false,
  });
  const bot = useQuery({
    queryKey: ["bot", run.data?.bot_id],
    queryFn: () => api<Bot>(`/api/v1/bots/${run.data!.bot_id}`),
    enabled: Boolean(run.data?.bot_id),
  });
  const strategyTrialQuery = useQuery({
    queryKey: ["optimization-trials", id, "STRATEGY_SEARCH"],
    queryFn: () => api<OptimizationTrialPage>(
      `/api/v1/optimizations/${id}/trials?limit=500&phase=STRATEGY_SEARCH`,
    ),
    refetchInterval:
      run.data && ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(run.data.status)
        ? 3000
        : false,
  });
  const validationTrialQuery = useQuery({
    queryKey: ["optimization-trials", id, "CANDIDATE_VALIDATION"],
    queryFn: () => api<OptimizationTrialPage>(
      `/api/v1/optimizations/${id}/trials?limit=500&phase=CANDIDATE_VALIDATION`,
    ),
    refetchInterval:
      run.data && ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(run.data.status)
        ? 3000
        : false,
  });
  const legacyValidationTrialQuery = useQuery({
    queryKey: ["optimization-trials", id, "FIXED_CONFIG_VALIDATION"],
    queryFn: () => api<OptimizationTrialPage>(
      `/api/v1/optimizations/${id}/trials?limit=500&phase=FIXED_CONFIG_VALIDATION`,
    ),
    refetchInterval: false,
  });
  const data = run.data;
  if (run.isLoading) return <div className="panel">Loading optimization...</div>;
  if (run.error || !data) {
    return <div className="error-box">{run.error?.message ?? "Optimization unavailable"}</div>;
  }
  const configSnapshot = normalizeBotConfig(data.config_snapshot);
  const optimizationName = bot.data?.name;
  const canCancel = ["PENDING", "RUNNING"].includes(data.status);
  const canApplyBest = Boolean(
    !applyBusy
    && Object.keys(data.best_candidate.sampled_parameters ?? {}).length,
  );
  const timings = data.summary.timings;
  const strategyTrials = strategyTrialQuery.data?.items ?? [];
  const validationTrials = [
    ...(validationTrialQuery.data?.items ?? []),
    ...(legacyValidationTrialQuery.data?.items ?? []),
  ];
  const tradeOverrides = data.best_candidate.config_overrides?.theoretical_trade
    ?? data.best_candidate.fixed_config_overrides?.theoretical_trade;
  const researchQuality = data.summary.research_quality_gates;
  const objectiveFormula = getObjectiveFormula(data);
  const searchSpace = data.search_space_snapshot?.length
    ? data.search_space_snapshot
    : data.summary.search_space ?? [];

  async function cancel() {
    if (!window.confirm("Cancel this optimization?")) return;
    await api(`/api/v1/optimizations/${id}/cancel`, { method: "POST" });
    await client.invalidateQueries({ queryKey: ["optimization", id] });
  }

  async function applyBestAsNewConfig() {
    if (!canApplyBest || !data) return;
    if (
      researchQuality?.overall_status === "BLOCK"
      && !window.confirm(
        "Research gates block this candidate. Apply it anyway as a new active config?",
      )
    ) {
      return;
    }
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
        theoretical_trade: {
          ...configSnapshot.theoretical_trade,
          ...(current.best_candidate.config_overrides?.theoretical_trade
            ?? current.best_candidate.fixed_config_overrides?.theoretical_trade
            ?? {}),
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

  async function loadExport(): Promise<OptimizationResultsExport> {
    setExportBusy(true);
    setExportMessage(null);
    setExportError(null);
    try {
      return await api<OptimizationResultsExport>(`/api/v1/optimizations/${id}/export`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Could not export results";
      setExportError(message);
      throw reason;
    } finally {
      setExportBusy(false);
    }
  }

  async function loadLlmContext(): Promise<OptimizationLlmContext> {
    setExportBusy(true);
    setExportMessage(null);
    setExportError(null);
    try {
      return await api<OptimizationLlmContext>(`/api/v1/optimizations/${id}/llm-context`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Could not export LLM context";
      setExportError(message);
      throw reason;
    } finally {
      setExportBusy(false);
    }
  }

  async function exportResultsToJson() {
    if (!optimizationName) return;
    try {
      const payload = await loadExport();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = exportFilename(optimizationName, id);
      anchor.click();
      URL.revokeObjectURL(url);
      setExportMessage(`Exported ${payload.trials.length} trials to JSON.`);
    } catch {
      // loadExport exposes the actionable error in the page.
    }
  }

  async function copyResultsToClipboard() {
    try {
      const payload = await loadExport();
      await writeClipboardText(JSON.stringify(payload, null, 2));
      setExportMessage(`Copied ${payload.trials.length} trials to clipboard.`);
    } catch (reason) {
      if (!exportError) {
        setExportError(reason instanceof Error ? reason.message : "Could not copy results");
      }
    }
  }

  async function exportLlmContextToJson() {
    if (!optimizationName) return;
    try {
      const payload = await loadLlmContext();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = llmContextFilename(optimizationName, id);
      anchor.click();
      URL.revokeObjectURL(url);
      setExportMessage(`Exported LLM context with ${llmContextTrialCount(payload)} trials.`);
    } catch {
      // loadLlmContext exposes the actionable error in the page.
    }
  }

  async function exportLlmContextToToon() {
    if (!optimizationName) return;
    setExportBusy(true);
    setExportMessage(null);
    setExportError(null);
    try {
      await downloadAuthenticated(
        `/api/v1/optimizations/${id}/llm-context?format=toon`,
        llmContextToonFilename(optimizationName, id),
      );
      setExportMessage("Exported token-optimized LLM context to TOON.");
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "Could not export TOON context");
    } finally {
      setExportBusy(false);
    }
  }

  async function copyLlmContextToClipboard() {
    try {
      const payload = await loadLlmContext();
      await writeClipboardText(JSON.stringify(payload, null, 2));
      setExportMessage(`Copied LLM context with ${llmContextTrialCount(payload)} trials.`);
    } catch (reason) {
      if (!exportError) {
        setExportError(reason instanceof Error ? reason.message : "Could not copy LLM context");
      }
    }
  }

  function runDownloadMenuAction(action: () => Promise<void>) {
    downloadMenuRef.current?.removeAttribute("open");
    void action();
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">OPTIMIZATION RESULT</span>
          <h1>{optimizationName ?? "Loading bot name..."}</h1>
          <p>
            {configSnapshot.strategy.name} | {new Date(data.date_from).toLocaleString()}
            {" - "}{new Date(data.date_to).toLocaleString()}
          </p>
        </div>
        <div className="button-row">
          <StatusPill value={data.status} />
          <details className="download-menu" ref={downloadMenuRef}>
            <summary
              aria-label={exportBusy ? "Preparing download options" : "Download optimization data"}
              className="button button-secondary download-menu-trigger"
            >
              {exportBusy ? "Preparing..." : "Download"}
              <span aria-hidden="true">v</span>
            </summary>
            <div className="download-menu-panel">
              <span className="download-menu-heading">Download as...</span>
              <button
                disabled={exportBusy || !optimizationName}
                onClick={() => runDownloadMenuAction(exportResultsToJson)}
                type="button"
              >
                Results JSON
              </button>
              <button
                disabled={exportBusy || !optimizationName}
                onClick={() => runDownloadMenuAction(exportLlmContextToJson)}
                type="button"
              >
                LLM context JSON
              </button>
              <button
                disabled={exportBusy || !optimizationName}
                onClick={() => runDownloadMenuAction(exportLlmContextToToon)}
                type="button"
              >
                LLM context TOON
              </button>
              <span className="download-menu-divider" />
              <span className="download-menu-heading">Copy as...</span>
              <button
                disabled={exportBusy}
                onClick={() => runDownloadMenuAction(copyResultsToClipboard)}
                type="button"
              >
                Results JSON
              </button>
              <button
                disabled={exportBusy}
                onClick={() => runDownloadMenuAction(copyLlmContextToClipboard)}
                type="button"
              >
                LLM context JSON
              </button>
            </div>
          </details>
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
      {bot.error && <div className="error-box">Could not load the optimization bot name.</div>}
      {applyError && <div className="error-box">{applyError}</div>}
      {exportError && <div className="error-box">{exportError}</div>}
      {exportMessage && <div className="panel">{exportMessage}</div>}
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
        <Metric
          label="Best objective score"
          value={formatScore(data.best_candidate.score)}
          title={objectiveFormula}
        />
        <Metric
          label="Completed"
          value={data.summary.completed_trials ?? data.progress.successful_trials ?? 0}
        />
        <Metric
          label="Failed"
          value={data.summary.failed_trials ?? data.progress.failed_trials ?? 0}
        />
      </div>
      {researchQuality && (
        <ResearchReadinessPanel quality={researchQuality} />
      )}
      {researchQuality?.overall_status === "BLOCK" && (
        <div className="error-box collector-alert">
          Research gates block this candidate. Applying it should be treated as an explicit
          override, not as V1 promotion.
        </div>
      )}
      {data.progress.strategy_trials_total !== undefined && (
        <div className="split-layout collector-section">
          <PhaseProgress
            label="Strategy search"
            completed={data.progress.strategy_trials_completed ?? 0}
            total={data.progress.strategy_trials_total}
          />
          <PhaseProgress
            label="Candidate validation"
            completed={data.progress.validation_trials_completed ?? 0}
            total={data.progress.validation_trials_total ?? 0}
          />
        </div>
      )}
      <div
        id="performance-timings"
        className="split-layout collector-section"
        style={{ gridTemplateColumns: "repeat(3, 1fr)" }}
      >
        {(data.summary.search_period || data.summary.validation_period) && (
          <div className="panel collector-section">
            <h2>Optimization periods</h2>
            <div className="key-values">
              {data.summary.search_period && (
                <div><dt>Strategy search</dt><dd>{formatPeriod(data.summary.search_period)}</dd></div>
              )}
              {data.summary.validation_period && (
                <div><dt>Candidate validation</dt><dd>{formatPeriod(data.summary.validation_period)}</dd></div>
              )}
            </div>
          </div>
        )}
        <div className="panel collector-section">
          <h2>Performance timings</h2>
          <div className="key-values">
            <div><dt>Candle load</dt><dd>{formatSeconds(timings?.candle_load_seconds)}</dd></div>
            <div><dt>Optuna sampling</dt><dd>{formatSeconds(timings?.optuna_sampling_seconds)}</dd></div>
            <div><dt>Backtests</dt><dd>{formatSeconds(timings?.backtest_seconds)}</dd></div>
            <div><dt>Database commits</dt><dd>{formatSeconds(timings?.database_commit_seconds)}</dd></div>
            <div><dt>Total</dt><dd>{formatSeconds(timings?.total_seconds)}</dd></div>
          </div>
        </div>
        <div className="panel collector-section">
          <h2>Optuna search ranges</h2>
          {!searchSpace.length ? (
            <p className="muted">No search-space snapshot is available.</p>
          ) : (
            <div className="table-wrap borderless">
              <table>
                <thead>
                  <tr><th>Parameter</th><th>Type</th><th>Search range</th></tr>
                </thead>
                <tbody>
                  {searchSpace.map((parameter) => (
                    <tr key={parameter.name}>
                      <td>{parameter.name.replaceAll("_", " ")}</td>
                      <td>{parameter.type ?? "--"}</td>
                      <td>{formatSearchRange(parameter)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      {(data.summary.data_profile || data.summary.robustness || data.summary.parameter_insights) && (
        <div id="collector-section" className="split-layout collector-section" style={{ gridTemplateColumns: 'repeat(3, 1fr)'}}>
          {data.summary.data_profile && (
            <JsonPanel title="Data profile" value={data.summary.data_profile} />
          )}
          {data.summary.robustness && (
            <JsonPanel title="Robustness" value={data.summary.robustness} />
          )}
          {data.summary.parameter_insights && (
            <JsonPanel title="Parameter insights" value={data.summary.parameter_insights} />
          )}
        </div>
      )}
      <div className="split-layout collector-section" style={{ gridTemplateColumns: 'repeat(4, 1fr)'}}>
        <div className="panel">
          <h2>Best parameters</h2>
          {!Object.keys(data.best_candidate.sampled_parameters ?? {}).length ? (
            <p className="muted">No completed candidate yet.</p>
          ) : (
            <div className="key-values">
              {Object.entries(data.best_candidate.sampled_parameters ?? {}).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>
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
              {Object.entries(data.best_candidate.metrics ?? {})
                .filter(([key]) => key !== "timings")
                .map(([key, value]) => (
                  <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>
                ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h2>{tradeOverrides ? "Optimized trade exits" : "Fixed trade exits"}</h2>
          <div className="key-values">
            <div><dt>session</dt><dd>{configSnapshot.session.timezone}</dd></div>
            <div>
              <dt>stop_loss_points</dt>
              <dd>{displayValue(tradeOverrides?.stop_loss_points ?? configSnapshot.theoretical_trade.stop_loss_points)}</dd>
            </div>
            <div>
              <dt>take_profit_points</dt>
              <dd>{displayValue(tradeOverrides?.take_profit_points ?? configSnapshot.theoretical_trade.take_profit_points)}</dd>
            </div>
            <div>
              <dt>risk_per_trade_pct</dt>
              <dd>{String(configSnapshot.theoretical_trade.risk_per_trade_pct)}</dd>
            </div>
            <div>
              <dt>max_spread_points</dt>
              <dd>{String(configSnapshot.filters.max_spread_points)}</dd>
            </div>
            <div>
              <dt>stale_after_seconds</dt>
              <dd>{String(configSnapshot.filters.stale_after_seconds)}</dd>
            </div>
          </div>
        </div>
        <div className="panel">
          <h2>Execution model</h2>
          <div className="key-values">
            {Object.entries(data.summary.execution_model ?? {
              fill_mode: data.fill_mode,
              fee_maker: data.fee_maker,
              fee_taker: data.fee_taker,
              taker_slippage: data.taker_slippage,
              slippage_small: data.slippage_small,
              medium_impact: data.medium_impact,
              impact_model: data.impact_model,
              model_sqrt_limit: data.model_sqrt_limit,
              limit_fill_timeout_s: data.limit_fill_timeout_s,
              min_qty_threshold: data.min_qty_threshold,
              min_qty_check: data.min_qty_check,
            }).map(([key, value]) => (
              <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>
            ))}
          </div>
        </div>
      </div>
      <div className="panel collector-section">
        <h2>Strategy trials ({strategyTrials.length})</h2>
        {!strategyTrials.length ? <p className="muted">No trials stored yet.</p> : (
          <div className="table-wrap borderless">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Trial</th>
                  <th>Status</th>
                  <th>Search objective score</th>
                  <th>Net P&amp;L</th>
                  <th>Drawdown</th>
                  <th>Trades</th>
                  <th>Backtest</th>
                </tr>
              </thead>
              <tbody>{strategyTrials.map((trial) => (
                <tr key={trial.id}>
                  <td>
                    <Link className="table-link" href={`/optimizations/${id}/trials/${trial.id}`}>
                      {trial.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{trial.trial_number}</td>
                  <td><StatusPill value={trial.status} /></td>
                  <td>{formatScore(trial.score)}</td>
                  <td>{displayValue(trial.metrics.net_pnl ?? "--")}</td>
                  <td>{displayValue(trial.metrics.max_drawdown ?? "--")}</td>
                  <td>{displayValue(trial.metrics.total_trades ?? "--")}</td>
                  <td>{formatSeconds(trial.metrics.timings?.backtest_seconds)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
      {validationTrials.length > 0 && (
        <div className="panel collector-section">
          <h2>Candidate validation ({validationTrials.length})</h2>
          <div className="table-wrap borderless">
            <table>
              <thead><tr><th>Trial</th><th>Stop loss</th><th>Take profit</th><th>Status</th><th>Validation objective score</th><th>Net P&amp;L</th><th>Drawdown</th><th>Trades</th></tr></thead>
              <tbody>{validationTrials.map((trial) => (
                <tr key={trial.id}>
                  <td><Link className="table-link" href={`/optimizations/${id}/trials/${trial.id}`}>{trial.trial_number}</Link></td>
                  <td>{displayValue(trial.config_overrides?.theoretical_trade?.stop_loss_points ?? "--")}</td>
                  <td>{displayValue(trial.config_overrides?.theoretical_trade?.take_profit_points ?? "--")}</td>
                  <td><StatusPill value={trial.status} /></td>
                  <td>{formatScore(trial.score)}</td>
                  <td>{displayValue(trial.metrics.net_pnl ?? "--")}</td>
                  <td>{displayValue(trial.metrics.max_drawdown ?? "--")}</td>
                  <td>{displayValue(trial.metrics.total_trades ?? "--")}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value, title }: { label: string; value: string | number; title?: string }) {
  return <div className="metric-card" title={title}><span>{label}</span><strong>{value}</strong></div>;
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      <pre className="code-block">{displayJson(value)}</pre>
    </div>
  );
}

function ResearchReadinessPanel({ quality }: { quality: ResearchQualityGates }) {
  return (
    <div className="ResearchReadinessPanel collector-section">
      <div className="section-title">
        <div>
          <h2>Research readiness</h2>
          <p>{quality.recommendation}</p>
        </div>
        <StatusPill value={quality.overall_status} />
      </div>
      <div className="table-wrap borderless">
        <table>
          <thead>
            <tr>
              <th>Gate</th>
              <th>Status</th>
              <th>Severity</th>
              <th>Message</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {quality.gates.map((gate) => (
              <tr key={gate.id}>
                <td>{formatGateName(gate.id)}</td>
                <td><StatusPill value={gate.status} /></td>
                <td>{gate.severity}</td>
                <td>{gate.message}</td>
                <td>{formatEvidence(gate.evidence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatSeconds(value: number | undefined): string {
  return value === undefined ? "--" : `${value.toFixed(6)} s`;
}

function formatSearchRange(parameter: {
  minimum?: number;
  maximum?: number;
  step?: number;
  choices?: Array<string | number | boolean>;
}): string {
  if (parameter.choices?.length) {
    return parameter.choices.map(displayValue).join(", ");
  }
  if (parameter.minimum !== undefined && parameter.maximum !== undefined) {
    const range = `${displayValue(parameter.minimum)} – ${displayValue(parameter.maximum)}`;
    return parameter.step === undefined ? range : `${range} (step ${displayValue(parameter.step)})`;
  }
  return "--";
}

function formatScore(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : String(value);
}

function getObjectiveFormula(data: OptimizationRun): string {
  const formula = data.summary.decision_context?.objective_formula;
  return typeof formula === "string"
    ? formula
    : "BALANCED = net_pnl - 1.5 * max_drawdown - 50 * missing_trades_below_30; no-trade trials score -99999";
}

function bestScoreSource(data: OptimizationRun): string {
  if (
    data.best_candidate.validation_score !== undefined
    || data.best_candidate.config_overrides
    || data.best_candidate.fixed_config_overrides
  ) {
    return "Best candidate validation trial";
  }
  if (
    data.progress.phase === "CANDIDATE_VALIDATION"
    || data.progress.phase === "FIXED_CONFIG_VALIDATION"
  ) {
    return "Best strategy search candidate pending validation";
  }
  return "Best strategy search trial";
}

function PhaseProgress({ label, completed, total }: { label: string; completed: number; total: number }) {
  return (
    <div className="panel backtest-progress">
      <strong>{label}</strong>
      <progress max={Math.max(total, 1)} value={completed} />
      <span>{completed} / {total} trials</span>
    </div>
  );
}

function formatPeriod(period: { date_from: string; date_to: string }): string {
  return `${new Date(period.date_from).toLocaleString()} - ${new Date(period.date_to).toLocaleString()}`;
}

function formatGateName(value: string): string {
  return value.replaceAll("_", " ");
}

function formatEvidence(evidence: Record<string, unknown>): string {
  return Object.entries(evidence)
    .map(([key, value]) => `${formatGateName(key)}: ${displayValue(value)}`)
    .join(", ");
}

async function writeClipboardText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  try {
    const copied = document.execCommand?.("copy") ?? false;
    if (!copied) {
      throw new Error("Clipboard is unavailable in this browser.");
    }
  } finally {
    textarea.remove();
  }
}

function exportFilename(optimizationName: string, optimizationId: string): string {
  const safe = safeFilenamePart(optimizationName);
  return `${safe}-optimization-${optimizationId.slice(0, 8)}.json`;
}

function llmContextFilename(optimizationName: string, optimizationId: string): string {
  const safe = safeFilenamePart(optimizationName);
  return `${safe}-optimization-${optimizationId.slice(0, 8)}-llm-context.json`;
}

function llmContextToonFilename(optimizationName: string, optimizationId: string): string {
  const safe = safeFilenamePart(optimizationName);
  return `${safe}-optimization-${optimizationId.slice(0, 8)}-llm-context.toon`;
}

function safeFilenamePart(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase();
}

function llmContextTrialCount(payload: OptimizationLlmContext): number {
  const legacyTrials = (payload as unknown as { trials?: unknown[] }).trials;
  if (legacyTrials) return legacyTrials.length;
  return (payload.top_trials ?? []).length
    + (payload.validation_winners ?? []).length
    + (payload.worst_trials ?? []).length;
}
