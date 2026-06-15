"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { addDays, performanceRange } from "@/lib/performance-dates";
import type { BotsPerformance, Performance } from "@/lib/types";

const periods = [1, 3, 7, 30] as const;

export default function BotsPerformancePage() {
  const [date, setDate] = useState(todayInVilnius());
  const [days, setDays] = useState<(typeof periods)[number]>(1);
  const range = performanceRange(date, days);
  const query = useQuery({
    queryKey: ["bots-performance", date, days],
    queryFn: () => api<BotsPerformance>(
      `/api/v1/bots/performance?date_from=${encodeURIComponent(range.from)}&date_to=${encodeURIComponent(range.to)}`,
    ),
    refetchInterval: 10000,
  });
  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">BOT INSTANCES</span>
          <h1>Performance</h1>
          <p>Aggregated theoretical results using Europe/Vilnius calendar days.</p>
        </div>
        <Link className="button button-secondary" href="/bots">Instances</Link>
      </header>
      <div className="panel performance-controls">
        <button className="button button-secondary" onClick={() => setDate(addDays(date, -1))}>Previous</button>
        <label>Date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <button className="button button-secondary" onClick={() => setDate(addDays(date, 1))}>Next</button>
        <label>Period<select value={days} onChange={(event) => setDays(Number(event.target.value) as typeof days)}>{periods.map((value) => <option key={value} value={value}>{value}d</option>)}</select></label>
      </div>
      {query.isLoading && <div className="panel table-actions">Loading performance...</div>}
      {query.error && <div className="error-box table-actions">{query.error.message}</div>}
      {query.data && (
        <div className="performance-stack table-actions">
          <section>
            <h2>All bots</h2>
            <PerformanceMetrics performance={query.data.total} />
          </section>
          <div className="performance-card-grid">
            {query.data.items.map((item) => (
              <article className="panel performance-bot-card" key={item.bot.id}>
                <div className="section-title">
                  <div><h2>{item.bot.name}</h2><p>{item.bot.mode} · {item.bot.state}</p></div>
                  <Link className="table-link" href={`/bots/${item.bot.id}`}>Open</Link>
                </div>
                <PerformanceMetrics performance={item.performance} />
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function PerformanceMetrics({ performance }: { performance: Performance }) {
  return (
    <div className="performance-metrics">
      <Metric label="Trades" value={String(performance.closed_trades)} />
      <Metric label="Net P&L" value={number(performance.net_pnl)} />
      <Metric label="Win rate" value={performance.win_rate === null ? "--" : `${number(performance.win_rate)}%`} />
      <Metric label="Profit factor" value={number(performance.profit_factor)} />
      <Metric label="Drawdown" value={number(performance.max_drawdown)} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function number(value: string | number | null): string {
  if (value === null) return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : "--";
}

function todayInVilnius(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Vilnius",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}
