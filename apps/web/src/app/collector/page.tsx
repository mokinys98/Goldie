"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, openCollectorStream } from "@/lib/api";
import type {
  CollectorCommand,
  CollectorOverview,
  CollectorSettingsResponse,
} from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

export default function CollectorPage() {
  const client = useQueryClient();
  const [error, setError] = useState("");
  const [newSymbol, setNewSymbol] = useState("");
  const overview = useQuery({
    queryKey: ["collector-overview"],
    queryFn: () => api<CollectorOverview>("/api/v1/collector/overview"),
    refetchInterval: 5000,
  });
  const settings = useQuery({
    queryKey: ["collector-settings"],
    queryFn: () => api<CollectorSettingsResponse>("/api/v1/collector/settings"),
  });

  useEffect(
    () =>
      openCollectorStream(() => {
        client.invalidateQueries({ queryKey: ["collector-overview"] });
        client.invalidateQueries({ queryKey: ["collector-settings"] });
      }),
    [client],
  );

  const command = async (name: "PAUSE" | "RESUME") => {
    if (!window.confirm(`${name} all collector instruments?`)) return;
    setError("");
    try {
      await api<CollectorCommand>("/api/v1/collector/commands", {
        method: "POST",
        body: JSON.stringify({ command: name, payload: {} }),
      });
      await client.invalidateQueries({ queryKey: ["collector-overview"] });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Command failed");
    }
  };

  const addInstrument = async () => {
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol) return;
    setError("");
    try {
      await api("/api/v1/collector/instruments", {
        method: "POST",
        body: JSON.stringify({ provider_symbol: symbol }),
      });
      setNewSymbol("");
      await client.invalidateQueries({ queryKey: ["collector-settings"] });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add instrument");
    }
  };

  if (overview.isLoading) return <div className="panel">Loading collector...</div>;
  if (overview.error || !overview.data) {
    return <div className="error-box">{overview.error?.message ?? "Collector unavailable"}</div>;
  }
  const data = overview.data;
  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">MARKET DATA CONTROL</span>
          <h1>Collector</h1>
          <p>OANDA read-only ingestion, health, configuration and data operations.</p>
        </div>
        <div className="button-row">
          <StatusPill value={data.instance?.status ?? "OFFLINE"} />
          <button className="button button-secondary" onClick={() => void command("PAUSE")}>
            Pause all
          </button>
          <button className="button button-primary" onClick={() => void command("RESUME")}>
            Resume all
          </button>
        </div>
      </header>
      <div className="theoretical-banner">
        READ ONLY MARKET DATA. No broker orders or Railway secrets are exposed.
      </div>
      {(error || overview.error) && <div className="error-box collector-alert">{error}</div>}

      <div className="dashboard-grid collector-metrics">
        <Metric label="Worker" value={data.instance?.status ?? "OFFLINE"} />
        <Metric label="Online feeds" value={data.counts.online} />
        <Metric label="Paused feeds" value={data.counts.paused} />
        <Metric label="Feed errors" value={data.counts.error} />
        <Metric label="Candles / 24h" value={data.counts.candles_24h} />
        <Metric label="Ticks / 24h" value={data.counts.ticks_24h} />
      </div>

      <div className="panel collector-section">
        <div className="section-title">
          <div>
            <h2>Instruments</h2>
            <p>New instruments are validated by OANDA when the collector starts them.</p>
          </div>
          <div className="inline-form">
            <input
              aria-label="OANDA instrument"
              placeholder="XAU_USD"
              value={newSymbol}
              onChange={(event) => setNewSymbol(event.target.value)}
            />
            <button className="button button-secondary" onClick={() => void addInstrument()}>
              Add
            </button>
          </div>
        </div>
        {!data.feeds.length ? (
          <p className="muted">
            Waiting for enabled instruments to register their market feeds.
            {(settings.data?.instruments.length ?? 0) > 0
              ? ` ${settings.data?.instruments.length} instrument(s) configured.`
              : ""}
          </p>
        ) : (
          <div className="table-wrap borderless">
            <table>
              <thead>
                <tr>
                  <th>Instrument</th><th>Status</th><th>Bid / Ask</th><th>Spread</th>
                  <th>Latest M1</th><th>Lag</th><th>Bots</th>
                </tr>
              </thead>
              <tbody>
                {data.feeds.map((feed) => (
                  <tr key={feed.id}>
                    <td>
                      <Link className="table-link" href={`/collector/${feed.id}`}>
                        {feed.provider_symbol}
                      </Link>
                      <span className="table-subtitle">{feed.environment}</span>
                    </td>
                    <td><StatusPill value={feed.status} /></td>
                    <td>
                      {feed.latest_tick
                        ? `${feed.latest_tick.bid} / ${feed.latest_tick.ask}`
                        : "--"}
                    </td>
                    <td>{feed.latest_tick?.spread ?? "--"}</td>
                    <td>{date(feed.latest_candle_at)}</td>
                    <td>{feed.data_lag_seconds === null ? "--" : `${feed.data_lag_seconds}s`}</td>
                    <td>{feed.bot_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <CommandTable commands={data.recent_commands} />
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function CommandTable({ commands }: { commands: CollectorCommand[] }) {
  return (
    <div className="panel collector-section">
      <h2>Recent commands</h2>
      {!commands.length ? <p className="muted">No collector commands yet.</p> : (
        <div className="table-wrap borderless">
          <table>
            <thead><tr><th>Created</th><th>Command</th><th>Status</th><th>Progress</th><th>Error</th></tr></thead>
            <tbody>{commands.map((item) => (
              <tr key={item.id}>
                <td>{date(item.created_at)}</td><td>{item.command}</td>
                <td><StatusPill value={item.status} /></td>
                <td>{progress(item)}</td><td className="error-text">{item.error ?? "--"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function progress(command: CollectorCommand): string {
  const processed = command.progress.processed;
  const total = command.progress.total;
  return processed !== undefined ? `${processed} / ${total ?? "?"}` : "--";
}

function date(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "--";
}
