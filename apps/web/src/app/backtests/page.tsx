"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { BacktestExperiment, Bot } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function BacktestsPage() {
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
  const botNames = new Map((bots.data ?? []).map((bot) => [bot.id, bot.name]));

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">HISTORICAL RESEARCH</span>
          <h1>Backtests</h1>
          <p>Deterministic M1 simulations using immutable strategy configurations.</p>
        </div>
        <Link className="button button-primary" href="/backtests/new">
          New backtest
        </Link>
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
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Created</th><th>Bot</th><th>Period</th><th>Status</th>
                <th>Progress</th><th>Trades</th><th>Net P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {experiments.data.map((item) => (
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
