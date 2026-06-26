"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
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
  const [newProvider, setNewProvider] = useState("binance_spot");
  const [newSymbol, setNewSymbol] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [environmentFilter, setEnvironmentFilter] = useState("");
  const [botUsageFilter, setBotUsageFilter] = useState("");
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

  const command = async (
    name: "PAUSE" | "RESUME",
    feed?: { id: string; provider_symbol: string },
  ) => {
    const target = feed ? feed.provider_symbol : "all collector instruments";
    if (!window.confirm(`${name} ${target}?`)) return;
    setError("");
    try {
      await api<CollectorCommand>("/api/v1/collector/commands", {
        method: "POST",
        body: JSON.stringify({
          command: name,
          market_feed_id: feed?.id,
          payload: {},
        }),
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
        body: JSON.stringify({
          provider: newProvider,
          environment: newProvider === "binance_spot" ? "spot" : "practice",
          provider_symbol: symbol,
        }),
      });
      setNewSymbol("");
      await client.invalidateQueries({ queryKey: ["collector-settings"] });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add instrument");
    }
  };

  const data = overview.data;
  const isLoading = overview.isLoading || !data;
  const feeds = useMemo(() => data?.feeds ?? [], [data?.feeds]);
  const statuses = useMemo(() => [...new Set(feeds.map((feed) => feed.status))].sort(), [feeds]);
  const environments = useMemo(
    () => [...new Set(feeds.map((feed) => feed.environment))].sort(),
    [feeds],
  );
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredFeeds = feeds.filter((feed) => (
    (!normalizedSearch
      || feed.provider_symbol.toLocaleLowerCase().includes(normalizedSearch)
      || feed.canonical_symbol.toLocaleLowerCase().includes(normalizedSearch)
      || feed.environment.toLocaleLowerCase().includes(normalizedSearch)
      || feed.provider.toLocaleLowerCase().includes(normalizedSearch))
    && (!statusFilter || feed.status === statusFilter)
    && (!environmentFilter || feed.environment === environmentFilter)
    && (!botUsageFilter
      || (botUsageFilter === "with-bots" ? feed.bot_count > 0 : feed.bot_count === 0))
  ));
  const filtersActive = Boolean(search || statusFilter || environmentFilter || botUsageFilter);

  function clearFilters() {
    setSearch("");
    setStatusFilter("");
    setEnvironmentFilter("");
    setBotUsageFilter("");
  }

  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">MARKET DATA CONTROL</span>
          <h1>Collector</h1>
          <p>Read-only market data ingestion, health, configuration and data operations.</p>
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

      <div className="panel bot-filter-panel collector-section">
        <label className="bot-filter-search">
          Search instrument
          <input
            type="search"
            placeholder="Instrument, symbol or environment..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All statuses</option>
            {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <label>
          Environment
          <select value={environmentFilter} onChange={(event) => setEnvironmentFilter(event.target.value)}>
            <option value="">All environments</option>
            {environments.map((environment) => <option key={environment} value={environment}>{environment}</option>)}
          </select>
        </label>
        <label>
          Bots
          <select value={botUsageFilter} onChange={(event) => setBotUsageFilter(event.target.value)}>
            <option value="">Any bot count</option>
            <option value="with-bots">With bots</option>
            <option value="without-bots">No bots</option>
          </select>
        </label>
        <div className="bot-filter-summary">
          <span aria-live="polite">Showing <strong>{filteredFeeds.length}</strong> of {feeds.length} instruments</span>
          <button className="button button-secondary" disabled={!filtersActive} type="button" onClick={clearFilters}>Clear filters</button>
        </div>
      </div>

      <div className="panel collector-section">
        <div className="section-title">
          <div>
            <h2>Instruments</h2>
            <p>New instruments are validated by their provider when the collector starts them.</p>
          </div>
          <div className="inline-form">
            <select
              aria-label="Provider"
              value={newProvider}
              onChange={(event) => setNewProvider(event.target.value)}
            >
              <option value="binance_spot">Binance Spot</option>
              <option value="oanda">OANDA</option>
            </select>
            <input
              aria-label="Provider instrument"
              placeholder={newProvider === "binance_spot" ? "BTCUSDT" : "XAU_USD"}
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
        ) : !filteredFeeds.length ? (
          <div className="empty-state bot-filter-empty">
            <h2>No matching instruments</h2>
            <p>Adjust the search or filters to show more rows.</p>
            <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button>
          </div>
        ) : (
          <div className="table-wrap borderless">
            <table>
              <thead>
                <tr>
                  <th>Instrument</th><th>Status</th><th>Bid / Ask</th><th>Spread</th>
                  <th>Earliest M1</th><th>Latest M1</th><th>Lag</th><th>Bots</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredFeeds.map((feed) => (
                  <tr key={feed.id}>
                    <td>
                      <Link className="table-link" href={`/collector/${feed.id}`}>
                        {feed.provider_symbol}
                      </Link>
                      <span className="table-subtitle">
                        {feed.provider} / {feed.environment}
                      </span>
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
                    <td>
                      <div className="button-row">
                        <button
                          className="button button-secondary"
                          onClick={() => void command("PAUSE", feed)}
                        >
                          Pause
                        </button>
                        <button
                          className="button button-primary"
                          onClick={() => void command("RESUME", feed)}
                        >
                          Resume
                        </button>
                      </div>
                    </td>
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
  const client = useQueryClient();
  const [error, setError] = useState("");

  const deleteCommand = async (command: CollectorCommand) => {
    if (!window.confirm(`Delete ${command.command} command?`)) return;
    setError("");
    try {
      await api(`/api/v1/collector/commands/${command.id}`, { method: "DELETE" });
      await client.invalidateQueries({ queryKey: ["collector-overview"] });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Command could not be deleted.");
    }
  };

  return (
    <div className="panel collector-section">
      <h2>Recent commands</h2>
      {loading ? <div className="skeleton-row" /> : !commands.length ? (
        <p className="muted">No collector commands yet.</p>
      ) : (
        <div className="table-wrap borderless">
          <table>
            <thead><tr><th>Created</th><th>Command</th><th>Status</th><th>Progress</th><th>Error</th><th>Actions</th></tr></thead>
            <tbody>{commands.map((item) => (
              <tr key={item.id}>
                <td>{date(item.created_at)}</td><td>{item.command}</td>
                <td><StatusPill value={item.status} /></td>
                <td>{progress(item)}</td><td className="error-text">{item.error ?? "--"}</td>
                <td>
                  {["PENDING", "RUNNING"].includes(item.status) ? (
                    <button className="button button-danger" onClick={() => void deleteCommand(item)}>
                      Delete
                    </button>
                  ) : "--"}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {error && <div className="error-box table-actions">{error}</div>}
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
