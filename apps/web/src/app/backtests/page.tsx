"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { BacktestExperiment, Bot } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function BacktestsPage() {
  const [search, setSearch] = useState("");
  const [botFilter, setBotFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [fillModeFilter, setFillModeFilter] = useState("");
  const [resultFilter, setResultFilter] = useState("");
  const experiments = useQuery({
    queryKey: ["backtests"],
    queryFn: () => api<BacktestExperiment[]>("/api/v1/backtests"),
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
  const rows = useMemo(() => experiments.data ?? [], [experiments.data]);
  const botOptions = useMemo(
    () => [...new Set(rows.map((item) => item.bot_id))]
      .map((id) => ({ id, name: botNames.get(id) ?? id }))
      .sort((left, right) => left.name.localeCompare(right.name)),
    [rows, botNames],
  );
  const statuses = useMemo(() => [...new Set(rows.map((item) => item.status))].sort(), [rows]);
  const fillModes = useMemo(
    () => [...new Set(rows.map((item) => item.fill_mode).filter(Boolean))].sort(),
    [rows],
  );
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredRows = rows.filter((item) => {
    const botName = botNames.get(item.bot_id) ?? item.bot_id;
    const pnl = Number(item.summary.net_pnl ?? Number.NaN);
    return (
      (!normalizedSearch || botName.toLocaleLowerCase().includes(normalizedSearch))
      && (!botFilter || item.bot_id === botFilter)
      && (!statusFilter || item.status === statusFilter)
      && (!fillModeFilter || item.fill_mode === fillModeFilter)
      && (!resultFilter
        || (resultFilter === "profit" && Number.isFinite(pnl) && pnl > 0)
        || (resultFilter === "loss" && Number.isFinite(pnl) && pnl < 0)
        || (resultFilter === "flat" && (!Number.isFinite(pnl) || pnl === 0)))
    );
  });
  const filtersActive = Boolean(search || botFilter || statusFilter || fillModeFilter || resultFilter);

  function clearFilters() {
    setSearch("");
    setBotFilter("");
    setStatusFilter("");
    setFillModeFilter("");
    setResultFilter("");
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">HISTORICAL RESEARCH</span>
          <h1>Backtests</h1>
          <p>Deterministic M1 simulations using immutable strategy configurations.</p>
        </div>
        <div className="button-row">
          <Link className="button button-secondary" href="/backtests/batch">Batch backtest</Link>
          <Link className="button button-primary" href="/backtests/new">New backtest</Link>
        </div>
      </header>
      {experiments.isLoading && <div className="panel">Loading backtests...</div>}
      {experiments.error && <div className="error-box">{experiments.error.message}</div>}
      {experiments.data?.length === 0 && (
        <div className="empty-state">
          <h2>No backtests yet</h2>
          <p>Run the first historical experiment from stored completed M1 candles.</p>
        </div>
      )}
      {!!experiments.data?.length && (
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
              Net P&amp;L
              <select value={resultFilter} onChange={(event) => setResultFilter(event.target.value)}>
                <option value="">Any result</option>
                <option value="profit">Profit</option>
                <option value="loss">Loss</option>
                <option value="flat">Flat / missing</option>
              </select>
            </label>
            <div className="bot-filter-summary">
              <span aria-live="polite">Showing <strong>{filteredRows.length}</strong> of {rows.length} backtests</span>
              <button className="button button-secondary" disabled={!filtersActive} type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          </div>
          {!filteredRows.length ? (
            <div className="empty-state bot-filter-empty">
              <h2>No matching backtests</h2>
              <p>Adjust the search or filters to show more rows.</p>
              <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Created</th><th>Bot</th><th>Period</th><th>Status</th>
                    <th>Progress</th><th>Trades</th><th>Net P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link className="table-link" href={`/backtests/${item.id}`}>
                          {new Date(item.created_at).toLocaleString()}
                        </Link>
                      </td>
                      <td>{botNames.get(item.bot_id) ?? item.bot_id}</td>
                      <td>{shortDate(item.date_from)} - {shortDate(item.date_to)}</td>
                      <td><StatusPill value={item.status} /></td>
                      <td>{progress(item)}</td>
                      <td>{item.summary.total_trades ?? "--"}</td>
                      <td>{item.summary.net_pnl ?? "--"}</td>
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

function progress(item: BacktestExperiment): string {
  const processed = item.progress.processed ?? 0;
  const total = item.progress.total ?? 0;
  if (!total) return item.status === "PENDING" ? "Queued" : "--";
  return `${processed} / ${total}`;
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString();
}
