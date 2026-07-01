"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, downloadAuthenticated } from "@/lib/api";
import type {
  Bot,
  OptimizationLlmContext,
  OptimizationResultsExport,
  OptimizationRun,
} from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function OptimizationsPage() {
  const [search, setSearch] = useState("");
  const [botFilter, setBotFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [fillModeFilter, setFillModeFilter] = useState("");
  const [scoreFilter, setScoreFilter] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const runs = useQuery({
    queryKey: ["optimizations"],
    queryFn: () => api<OptimizationRun[]>("/api/v1/optimizations"),
    refetchInterval: (query) =>
      query.state.data?.some((item) =>
        ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(item.status),
      )
        ? 3000
        : false,
  });
  const bots = useQuery({
    queryKey: ["bots"],
    queryFn: () => api<Bot[]>("/api/v1/bots"),
  });
  const botNames = useMemo(
    () => new Map((bots.data ?? []).map((bot) => [bot.id, bot.name])),
    [bots.data],
  );
  const rows = useMemo(() => runs.data ?? [], [runs.data]);
  const botOptions = useMemo(
    () => [...new Set(rows.map((item) => item.bot_id))]
      .map((id) => ({ id, name: botNames.get(id) ?? id }))
      .sort((left, right) => left.name.localeCompare(right.name)),
    [rows, botNames],
  );
  const statuses = useMemo(() => [...new Set(rows.map((item) => item.status))].sort(), [rows]);
  const fillModes = useMemo(() => [...new Set(rows.map((item) => item.fill_mode))].sort(), [rows]);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredRows = rows.filter((item) => {
    const botName = botNames.get(item.bot_id) ?? item.bot_id;
    const score = Number(item.best_candidate.score ?? Number.NaN);
    return (
      (!normalizedSearch || botName.toLocaleLowerCase().includes(normalizedSearch))
      && (!botFilter || item.bot_id === botFilter)
      && (!statusFilter || item.status === statusFilter)
      && (!fillModeFilter || item.fill_mode === fillModeFilter)
      && (!scoreFilter
        || (scoreFilter === "with-score" && Number.isFinite(score))
        || (scoreFilter === "without-score" && !Number.isFinite(score)))
    );
  });
  const filtersActive = Boolean(search || botFilter || statusFilter || fillModeFilter || scoreFilter);
  const visibleIds = filteredRows.map((item) => item.id);
  const visibleSelectedCount = visibleIds.filter((id) => selectedIds.has(id)).length;
  const allVisibleSelected = visibleIds.length > 0 && visibleSelectedCount === visibleIds.length;
  const selectedRows = rows.filter((item) => selectedIds.has(item.id));

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = visibleSelectedCount > 0 && !allVisibleSelected;
    }
  }, [allVisibleSelected, visibleSelectedCount]);

  function clearFilters() {
    setSearch("");
    setBotFilter("");
    setStatusFilter("");
    setFillModeFilter("");
    setScoreFilter("");
  }

  function toggleSelection(id: string, checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function toggleAllVisible(checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current);
      visibleIds.forEach((id) => {
        if (checked) next.add(id);
        else next.delete(id);
      });
      return next;
    });
  }

  async function exportSelected(kind: "results" | "llm-context" | "llm-context-toon") {
    if (!selectedRows.length || exportBusy) return;
    setExportBusy(true);
    setExportError(null);
    setExportMessage(null);

    try {
      for (const item of selectedRows) {
        const isLlmContext = kind !== "results";
        const optimizationName = botNames.get(item.bot_id)
          ?? (await api<Bot>(`/api/v1/bots/${item.bot_id}`)).name;
        if (kind === "llm-context-toon") {
          await downloadAuthenticated(
            `/api/v1/optimizations/${item.id}/llm-context?format=toon`,
            optimizationExportFilename(optimizationName, item.id, "toon"),
          );
          continue;
        }
        const payload = isLlmContext
          ? await api<OptimizationLlmContext>(`/api/v1/optimizations/${item.id}/llm-context`)
          : await api<OptimizationResultsExport>(`/api/v1/optimizations/${item.id}/export`);
        downloadJson(
          payload,
          optimizationExportFilename(
            optimizationName,
            item.id,
            isLlmContext ? "json" : "results",
          ),
        );
      }
      setExportMessage(
        `Exported ${selectedRows.length} ${selectedRows.length === 1 ? "optimization" : "optimizations"}.`,
      );
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "Could not export selected optimizations");
    } finally {
      setExportBusy(false);
    }
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">SEARCH AND TUNING</span>
          <h1>Optimization</h1>
          <p>Optuna trials over immutable strategy snapshots using the Goldie backtest engine.</p>
        </div>
        <div className="button-row">
          <Link className="button button-primary" href="/optimizations/new">New optimization</Link>
        </div>
      </header>
      {runs.isLoading && <div className="panel">Loading optimization runs...</div>}
      {runs.error && <div className="error-box">{runs.error.message}</div>}
      {runs.data?.length === 0 && (
        <div className="empty-state">
          <h2>No optimization runs yet</h2>
          <p>Start a parameter search for one validated strategy configuration.</p>
        </div>
      )}
      {!!runs.data?.length && (
        <>
          <div className="panel bot-filter-panel">
            <label className="bot-filter-search">
              Search bot
              <input type="search" placeholder="Bot name..." value={search} onChange={(event) => setSearch(event.target.value)} />
            </label>
            <label>
              Bot
              <select value={botFilter} onChange={(event) => setBotFilter(event.target.value)}>
                <option value="">All bots</option>
                {botOptions.map((bot) => <option key={bot.id} value={bot.id}>{bot.name}</option>)}
              </select>
            </label>
            <label>
              Status
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">All statuses</option>
                {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
            <label>
              Fill mode
              <select value={fillModeFilter} onChange={(event) => setFillModeFilter(event.target.value)}>
                <option value="">All fill modes</option>
                {fillModes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
              </select>
            </label>
            <label>
              Objective score
              <select value={scoreFilter} onChange={(event) => setScoreFilter(event.target.value)}>
                <option value="">Any objective score</option>
                <option value="with-score">With objective score</option>
                <option value="without-score">No objective score</option>
              </select>
            </label>
            <div className="bot-filter-summary">
              <span aria-live="polite">Showing <strong>{filteredRows.length}</strong> of {rows.length} optimizations</span>
              <button className="button button-secondary" disabled={!filtersActive} type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          </div>
          {!filteredRows.length ? (
            <div className="empty-state bot-filter-empty">
              <h2>No matching optimizations</h2>
              <p>Adjust the search or filters to show more rows.</p>
              <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          ) : (
            <>
              {exportError && <div className="error-box optimization-export-feedback">{exportError}</div>}
              {exportMessage && <div className="success-box optimization-export-feedback">{exportMessage}</div>}
              {!!selectedRows.length && (
                <div className="button-row optimization-selection-actions" aria-live="polite">
                  <span>
                    <strong>{selectedRows.length}</strong>
                    {" selected"}
                  </span>
                  <button
                    className="button button-secondary"
                    disabled={exportBusy}
                    onClick={() => void exportSelected("results")}
                    type="button"
                  >
                    {exportBusy ? "Preparing..." : "Results JSON"}
                  </button>
                  <button
                    className="button button-secondary"
                    disabled={exportBusy}
                    onClick={() => void exportSelected("llm-context")}
                    type="button"
                  >
                    {exportBusy ? "Preparing..." : "LLM context JSON"}
                  </button>
                  <button
                    className="button button-secondary"
                    disabled={exportBusy}
                    onClick={() => void exportSelected("llm-context-toon")}
                    type="button"
                  >
                    {exportBusy ? "Preparing..." : "LLM context TOON"}
                  </button>
                  <button
                    className="button button-ghost"
                    disabled={exportBusy}
                    onClick={() => setSelectedIds(new Set())}
                    type="button"
                  >
                    Clear selection
                  </button>
                </div>
              )}
              <div className="table-wrap optimization-table">
                <table>
                <thead>
                  <tr>
                    <th className="optimization-select-cell">
                      <input
                        ref={selectAllRef}
                        aria-label="Select all visible optimizations"
                        checked={allVisibleSelected}
                        className="optimization-select"
                        onChange={(event) => toggleAllVisible(event.target.checked)}
                        type="checkbox"
                      />
                    </th>
                    <th>Created</th>
                    <th>Bot</th>
                    <th>Period</th>
                    <th>Status</th>
                    <th>Progress</th>
                    <th>Best objective score</th>
                    <th>Trials</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((item) => (
                    <tr className={selectedIds.has(item.id) ? "is-selected" : undefined} key={item.id}>
                      <td className="optimization-select-cell">
                        <input
                          aria-label={`Select optimization created ${new Date(item.created_at).toLocaleString()}`}
                          checked={selectedIds.has(item.id)}
                          className="optimization-select"
                          onChange={(event) => toggleSelection(item.id, event.target.checked)}
                          type="checkbox"
                        />
                      </td>
                      <td>
                        <Link className="table-link" href={`/optimizations/${item.id}`}>
                          {new Date(item.created_at).toLocaleString()}
                        </Link>
                      </td>
                      <td>{botNames.get(item.bot_id) ?? item.bot_id}</td>
                      <td>{shortDate(item.date_from)} - {shortDate(item.date_to)}</td>
                      <td><StatusPill value={item.status} /></td>
                      <td>
                        {item.progress.completed_trials ?? 0}
                        {" / "}
                        {item.progress.total_trials ?? item.n_trials}
                      </td>
                      <td>{formatScore(item.best_candidate.score)}</td>
                      <td>{item.n_trials}</td>
                    </tr>
                  ))}
                </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

function formatScore(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : String(value);
}

function downloadJson(payload: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function optimizationExportFilename(
  optimizationName: string,
  optimizationId: string,
  format: "results" | "json" | "toon",
): string {
  const safe = optimizationName
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
  const suffix = format === "results" ? "" : "-llm-context";
  const extension = format === "toon" ? "toon" : "json";
  return `${safe}-optimization-${optimizationId.slice(0, 8)}${suffix}.${extension}`;
}
