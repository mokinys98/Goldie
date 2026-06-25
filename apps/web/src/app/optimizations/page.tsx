"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Bot, OptimizationRun } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function OptimizationsPage() {
  const [search, setSearch] = useState("");
  const [botFilter, setBotFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [fillModeFilter, setFillModeFilter] = useState("");
  const [scoreFilter, setScoreFilter] = useState("");
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

  function clearFilters() {
    setSearch("");
    setBotFilter("");
    setStatusFilter("");
    setFillModeFilter("");
    setScoreFilter("");
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
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Created</th><th>Bot</th><th>Period</th><th>Status</th>
                    <th>Progress</th><th>Best objective score</th><th>Trials</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((item) => (
                    <tr key={item.id}>
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
