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
    refetchInterval: 60_000,
  });
  const settings = useQuery({
    queryKey: ["collector-settings"],
    queryFn: () => api<CollectorSettingsResponse>("/api/v1/collector/settings"),
  });

  useEffect(
    () =>
      openCollectorStream((event) => {
        if (event.event_type === "market.quote" && event.market_feed_id && event.data) {
          client.setQueryData<CollectorOverview>(["collector-overview"], (current) => {
            if (!current || !event.data?.observed_at || !event.data.bid || !event.data.ask) {
              return current;
            }
            return {
              ...current,
              feeds: current.feeds.map((feed) =>
                feed.id === event.market_feed_id
                  ? {
                      ...feed,
                      data_lag_seconds: 0,
                      latest_tick: {
                        observed_at: event.data!.observed_at!,
                        bid: event.data!.bid!,
                        ask: event.data!.ask!,
                        spread: feed.latest_tick?.spread ?? "0",
                      },
                    }
                  : feed,
              ),
            };
          });
          return;
        }
        if (event.event_type === "collector.heartbeat") {
          client.setQueryData<CollectorOverview>(["collector-overview"], (current) => {
            if (!current?.instance || current.instance.id !== event.collector_instance_id) {
              return current;
            }
            return {
              ...current,
              instance: {
                ...current.instance,
                status: event.status ?? current.instance.status,
                reported_status: event.status ?? current.instance.reported_status,
                last_heartbeat_at: event.occurred_at ?? current.instance.last_heartbeat_at,
              },
            };
          });
          return;
        }
        if (event.event_type === "collector.configuration") {
          void client.invalidateQueries({ queryKey: ["collector-settings"] });
        }
        if (
          ["market.candle", "collector.command", "collector.configuration"].includes(
            event.event_type ?? "",
          )
        ) {
          void client.invalidateQueries({ queryKey: ["collector-overview"] });
        }
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

  const data = overview.data;
  const isLoading = overview.isLoading || !data;
  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">MARKET DATA CONTROL</span>
          <h1>Collector</h1>
          <p>OANDA read-only ingestion, health, configuration and data operations.</p>
        </div>
        <div className="button-row">
          <StatusPill value={data?.instance?.status ?? (isLoading ? "LOADING" : "OFFLINE")} />
          <button className="button button-secondary" disabled={isLoading} onClick={() => void command("PAUSE")}>
            Pause all
          </button>
          <button className="button button-primary" disabled={isLoading} onClick={() => void command("RESUME")}>
            Resume all
          </button>
        </div>
      </header>
      <div className="theoretical-banner">
        READ ONLY MARKET DATA. No broker orders or Railway secrets are exposed.
      </div>
      {(error || overview.error) && (
        <div className="error-box collector-alert">
          {error || overview.error?.message || "Collector overview unavailable"}
        </div>
      )}
      {settings.error && (
        <div className="error-box collector-alert">
          Settings unavailable: {settings.error.message}
        </div>
      )}

      <div className="dashboard-grid collector-metrics">
        <Metric label="Worker" value={data?.instance?.status ?? "--"} loading={isLoading} />
        <Metric label="Online feeds" value={data?.counts.online ?? "--"} loading={isLoading} />
        <Metric label="Paused feeds" value={data?.counts.paused ?? "--"} loading={isLoading} />
        <Metric label="Feed errors" value={data?.counts.error ?? "--"} loading={isLoading} />
        <Metric label="Candles / 24h" value={data?.counts.candles_24h ?? "--"} loading={isLoading} />
        <Metric label="Ticks / 24h" value={data?.counts.ticks_24h ?? "--"} loading={isLoading} />
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
        {isLoading ? (
          <div className="collector-skeleton-table" aria-label="Loading instruments">
            {Array.from({ length: 4 }, (_, index) => (
              <div className="skeleton-row" key={index} />
            ))}
          </div>
        ) : !data?.feeds.length ? (
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
                  <th>Earliest M1</th><th>Latest M1</th><th>Lag</th><th>Bots</th>
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
                    <td>{date(feed.earliest_candle_at)}</td>
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

      <CommandTable commands={data?.recent_commands ?? []} loading={isLoading} />
    </section>
  );
}

function Metric({
  label,
  value,
  loading = false,
}: {
  label: string;
  value: string | number;
  loading?: boolean;
}) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong className={loading ? "skeleton-value" : ""}>{value}</strong>
    </div>
  );
}

function CommandTable({
  commands,
  loading,
}: {
  commands: CollectorCommand[];
  loading: boolean;
}) {
  return (
    <div className="panel collector-section">
      <h2>Recent commands</h2>
      {loading ? <div className="skeleton-row" /> : !commands.length ? (
        <p className="muted">No collector commands yet.</p>
      ) : (
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
