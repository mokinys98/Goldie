"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Bot, OptimizationRun } from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function OptimizationsPage() {
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
  const botNames = new Map((bots.data ?? []).map((bot) => [bot.id, bot.name]));

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
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Created</th><th>Bot</th><th>Period</th><th>Status</th>
                <th>Progress</th><th>Best score</th><th>Trials</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((item) => (
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
                  <td>{item.best_candidate.score ?? "--"}</td>
                  <td>{item.n_trials}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString();
}
