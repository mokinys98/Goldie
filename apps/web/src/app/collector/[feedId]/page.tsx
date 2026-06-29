"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, openCollectorStream } from "@/lib/api";
import type {
  CollectorCommand,
  CollectorContinuity,
  CollectorContinuityScope,
  CollectorFeedDetail,
  CollectorSettingsResponse,
} from "@/lib/types";
import { StatusPill } from "@/components/status-pill";

const tabs = ["Overview", "Data", "Commands", "Settings"] as const;
type Tab = (typeof tabs)[number];
type BackfillRange = { start: string; end: string };

export default function CollectorFeedPage() {
  const { feedId } = useParams<{ feedId: string }>();
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("Overview");
  const [backfillRange, setBackfillRange] = useState<BackfillRange>();
  const detail = useQuery({
    queryKey: ["collector-feed", feedId],
    queryFn: () => api<CollectorFeedDetail>(`/api/v1/collector/feeds/${feedId}`),
    refetchInterval: 60_000,
  });
  const continuity = useQuery({
    queryKey: ["collector-continuity", feedId],
    queryFn: () => api<CollectorContinuity>(`/api/v1/collector/feeds/${feedId}/continuity`),
    enabled: tab === "Data",
    refetchInterval: tab === "Data" ? 60_000 : false,
  });
  const settings = useQuery({
    queryKey: ["collector-settings"],
    queryFn: () => api<CollectorSettingsResponse>("/api/v1/collector/settings"),
  });

  useEffect(
    () =>
      openCollectorStream((event) => {
        if (event.event_type === "market.quote" && event.market_feed_id === feedId) {
          client.setQueryData<CollectorFeedDetail>(
            ["collector-feed", feedId],
            (current) => {
              if (!current || !event.data?.observed_at || !event.data.bid || !event.data.ask) {
                return current;
              }
              return {
                ...current,
                feed: {
                  ...current.feed,
                  data_lag_seconds: 0,
                  latest_tick: {
                    observed_at: event.data.observed_at,
                    bid: event.data.bid,
                    ask: event.data.ask,
                    spread: current.feed.latest_tick?.spread ?? "0",
                  },
                },
              };
            },
          );
          return;
        }
        if (event.event_type === "collector.configuration") {
          void client.invalidateQueries({ queryKey: ["collector-settings"] });
        }
        if (
          event.market_feed_id === feedId
          && ["market.candle", "collector.command", "instrument.specification"].includes(
            event.event_type ?? "",
          )
        ) {
          void client.invalidateQueries({ queryKey: ["collector-feed", feedId] });
        }
      }),
    [client, feedId],
  );

  if (detail.isLoading) return <div className="panel">Loading feed...</div>;
  if (detail.error || !detail.data) {
    return <div className="error-box">{detail.error?.message ?? "Feed unavailable"}</div>;
  }
  const data = detail.data;
  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">COLLECTOR FEED</span>
          <h1>{data.feed.provider_symbol}</h1>
          <p>{data.feed.provider.toUpperCase()} {data.feed.environment} market data.</p>
        </div>
        <div className="header-statuses">
          <StatusPill value={data.feed.status} />
          <span className="readonly-badge">NO ORDER EXECUTION</span>
        </div>
      </header>
      <div className="tabs">
        {tabs.map((item) => (
          <button className={tab === item ? "active" : ""} key={item} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </div>
      {tab === "Overview" && <Overview detail={data} />}
      {tab === "Data" && (
        <DataContinuity
          continuity={continuity.data}
          error={continuity.error}
          loading={continuity.isLoading}
          onSelectGap={(gap) => {
            setBackfillRange({
              start: gap.from,
              end: new Date(new Date(gap.to).getTime() + 60_000).toISOString(),
            });
            setTab("Commands");
          }}
        />
      )}
      {tab === "Commands" && (
        <Commands feedId={feedId} commands={data.commands} initialRange={backfillRange} />
      )}
      {tab === "Settings" && settings.data && (
        <Settings
          feedId={feedId}
          response={settings.data}
          current={data.instrument_settings}
        />
      )}
    </section>
  );
}

function Overview({ detail }: { detail: CollectorFeedDetail }) {
  const feed = detail.feed;
  return (
    <div className="dashboard-grid">
      <Metric label="Status" value={feed.status} />
      <Metric label="Data lag" value={feed.data_lag_seconds === null ? "--" : `${feed.data_lag_seconds}s`} />
      <Metric label="M1 gaps (recent)" value={detail.gap_count} />
      <Metric label="Bid" value={feed.latest_tick?.bid ?? "--"} />
      <Metric label="Ask" value={feed.latest_tick?.ask ?? "--"} />
      <Metric label="Spread" value={feed.latest_tick?.spread ?? "--"} />
      <div className="panel grid-span-2">
        <h2>Feed diagnostics</h2>
        <KeyValues values={{
          provider: feed.provider,
          environment: feed.environment,
          canonical_symbol: feed.canonical_symbol,
          provider_symbol: feed.provider_symbol,
          last_heartbeat_at: displayDate(feed.last_heartbeat_at),
          earliest_candle_at: displayDate(feed.earliest_candle_at),
          latest_candle_at: displayDate(feed.latest_candle_at),
          bot_count: feed.bot_count,
        }} />
      </div>
      <div className="panel">
        <h2>Agent</h2>
        <KeyValues values={detail.agent} />
      </div>
    </div>
  );
}

function DataContinuity({
  continuity,
  error,
  loading,
  onSelectGap,
}: {
  continuity: CollectorContinuity | undefined;
  error: Error | null;
  loading: boolean;
  onSelectGap: (gap: CollectorContinuityScope["gaps"][number]) => void;
}) {
  if (loading) return <div className="panel">Loading continuity analysis...</div>;
  if (error || !continuity) {
    return <div className="error-box">{error?.message ?? "Continuity analysis unavailable"}</div>;
  }
  const history = continuity.full_history;
  const recent = continuity.recent_24h;
  const qualityLabel = history.missing_minutes
    ? `${history.missing_minutes.toLocaleString()} missing M1 candles across full history`
    : "Continuous M1 sequence across full history";

  return (
    <div className="performance-stack">
      <ContinuitySummary title="Full history continuity" scope={history} primary />
      <div className="panel">
        <div className="section-title">
          <div>
            <h2>Full history gap map</h2>
            <p>{qualityLabel}</p>
          </div>
          <StatusPill value={history.status} />
        </div>
        <div className="continuity-plot" aria-label={qualityLabel}>
          <div className="continuity-axis">
            <span className="continuity-dot" />
            <span className="continuity-line" />
            {history.gaps.map((gap, index) => {
              const fullSpan = history.date_from && history.date_to
                ? new Date(history.date_to).getTime() - new Date(history.date_from).getTime()
                : 0;
              const offset = history.date_from && fullSpan
                ? ((new Date(gap.from).getTime() - new Date(history.date_from).getTime()) / fullSpan) * 100
                : 50;
              const width = fullSpan ? (gap.missing_minutes * 60_000 / fullSpan) * 100 : 2;
              return (
                <button
                  aria-label={`Backfill gap ${displayDate(gap.from)} to ${displayDate(gap.to)}`}
                  className="continuity-gap"
                  key={`${gap.from}-${gap.to}-${index}`}
                  onClick={() => onSelectGap(gap)}
                  style={{
                    left: `${Math.max(2, Math.min(96, offset))}%`,
                    width: `${Math.max(2, Math.min(38, width))}%`,
                  }}
                  type="button"
                  data-tooltip={`${displayDate(gap.from)} - ${displayDate(gap.to)} (${gap.missing_minutes}m)`}
                />
              );
            })}
            <span className="continuity-dot continuity-dot-end" />
          </div>
          <div className="continuity-labels">
            <span>{displayDate(history.date_from)}</span>
            <strong>{qualityLabel}</strong>
            <span>{displayDate(history.date_to)}</span>
          </div>
        </div>
      </div>
      <ContinuitySummary title="Latest 24 hours" scope={recent} />
      <GapList scope={history} onSelectGap={onSelectGap} />
    </div>
  );
}

function ContinuitySummary({
  title,
  scope,
  primary = false,
}: {
  title: string;
  scope: CollectorContinuityScope;
  primary?: boolean;
}) {
  return (
    <div className="panel">
      <div className="section-title">
        <div>
          <h2>{title}</h2>
          <p>{displayDate(scope.date_from)} – {displayDate(scope.date_to)}</p>
        </div>
        <StatusPill value={scope.status} />
      </div>
      <div className="dashboard-grid">
        <Metric label={primary ? "Full history status" : "Recent status"} value={scope.status} />
        <Metric label="Coverage" value={scope.coverage_pct === null ? "--" : `${scope.coverage_pct.toFixed(1)}%`} />
        <Metric label="Observed M1 candles" value={scope.observed_candles.toLocaleString()} />
        <Metric label="Expected M1 candles" value={scope.expected_candles.toLocaleString()} />
        <Metric label="Missing M1 minutes" value={scope.missing_minutes.toLocaleString()} />
        <Metric label="Gap segments" value={scope.gap_segment_count.toLocaleString()} />
      </div>
      {scope.market_closed_missing_minutes > 0 && (
        <p className="muted">
          {scope.market_closed_missing_minutes.toLocaleString()} provider market-closure minutes were excluded.
        </p>
      )}
    </div>
  );
}

function GapList({
  scope,
  onSelectGap,
}: {
  scope: CollectorContinuityScope;
  onSelectGap: (gap: CollectorContinuityScope["gaps"][number]) => void;
}) {
  if (!scope.gap_segment_count) {
    return (
      <div className="success-box">
        <strong>No historical gap action</strong>
        <p>Complete M1 candles are contiguous across the stored feed history.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="section-title">
        <div>
          <h2>Detected gaps</h2>
          <p>Largest missing M1 ranges across full history.</p>
        </div>
        <StatusPill value={scope.status} />
      </div>
      {scope.gaps.length ? (
        <div className="gap-list">
          {scope.gaps.map((gap, index) => (
            <button
              aria-label={`Backfill gap ${displayDate(gap.from)} to ${displayDate(gap.to)}`}
              className="gap-row"
              key={`${gap.from}-${gap.to}-${index}`}
              onClick={() => onSelectGap(gap)}
              type="button"
            >
              <span>{displayDate(gap.from)}</span>
              <strong>{gap.missing_minutes.toLocaleString()}m</strong>
              <span>{displayDate(gap.to)}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="muted">Gap count is available, but this API response does not include ranges yet.</p>
      )}
      {scope.gaps_truncated && (
        <p className="muted">Showing largest 100 of {scope.gap_segment_count.toLocaleString()} gaps.</p>
      )}
      <div className="error-box table-actions">
        Run a targeted backfill from Commands for the listed range, then confirm this panel returns to PASS.
      </div>
    </div>
  );
}

function Commands({
  feedId,
  commands,
  initialRange,
}: {
  feedId: string;
  commands: CollectorCommand[];
  initialRange?: BackfillRange;
}) {
  const client = useQueryClient();
  const [start, setStart] = useState(
    localInput(initialRange ? new Date(initialRange.start) : new Date(Date.now() - 24 * 3600_000)),
  );
  const [end, setEnd] = useState(
    localInput(initialRange ? new Date(initialRange.end) : new Date()),
  );
  const [error, setError] = useState("");

  const send = async (command: CollectorCommand["command"]) => {
    const expensive = command === "BACKFILL" || command === "RECONNECT";
    if (expensive && !window.confirm(`Run ${command} for this feed?`)) return;
    setError("");
    try {
      await api("/api/v1/collector/commands", {
        method: "POST",
        body: JSON.stringify({
          command,
          market_feed_id: feedId,
          payload: command === "BACKFILL"
            ? { start: new Date(start).toISOString(), end: new Date(end).toISOString() }
            : {},
        }),
      });
      await client.invalidateQueries({ queryKey: ["collector-feed", feedId] });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Command failed");
    }
  };

  return (
    <div className="performance-stack">
      <div className="panel">
        <h2>Live controls</h2>
        <div className="button-row">
          <button className="button button-secondary" onClick={() => void send("PAUSE")}>Pause</button>
          <button className="button button-primary" onClick={() => void send("RESUME")}>Resume</button>
          <button className="button button-secondary" onClick={() => void send("RECONNECT")}>Reconnect</button>
        </div>
      </div>
      <div className="panel">
        <h2>Historical backfill</h2>
        <p className="muted">One backfill per feed at a time, up to 365 days.</p>
        <div className="form-grid compact-form">
          <label>Start<input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
          <label>End<input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
          <button className="button button-primary" onClick={() => void send("BACKFILL")}>Start backfill</button>
        </div>
        {error && <div className="error-box">{error}</div>}
      </div>
      <CommandHistory commands={commands} />
    </div>
  );
}

function Settings({
  feedId,
  response,
  current,
}: {
  feedId: string;
  response: CollectorSettingsResponse;
  current: CollectorFeedDetail["instrument_settings"];
}) {
  const client = useQueryClient();
  const [global, setGlobal] = useState(() => ({ ...response.configuration }));
  const [enabled, setEnabled] = useState(current.enabled);
  const [overrides, setOverrides] = useState(JSON.stringify(current.overrides, null, 2));
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const saveGlobal = async () => {
    setError(""); setMessage("");
    try {
      await api("/api/v1/collector/settings", {
        method: "PUT",
        body: JSON.stringify({
          expected_version: response.configuration.version,
          quote_interval_seconds: Number(global.quote_interval_seconds),
          candle_poll_seconds: Number(global.candle_poll_seconds),
          heartbeat_seconds: Number(global.heartbeat_seconds),
          backfill_days: Number(global.backfill_days),
          backfill_batch_size: Number(global.backfill_batch_size),
          configuration_retry_seconds: Number(global.configuration_retry_seconds),
        }),
      });
      setMessage("Global settings saved.");
      await client.invalidateQueries({ queryKey: ["collector-settings"] });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save settings");
    }
  };
  const saveInstrument = async () => {
    setError(""); setMessage("");
    try {
      const parsed = JSON.parse(overrides) as Record<string, number>;
      await api(`/api/v1/collector/feeds/${feedId}/settings`, {
        method: "PUT",
        body: JSON.stringify({ enabled, overrides: parsed }),
      });
      setMessage("Instrument settings saved.");
      await Promise.all([
        client.invalidateQueries({ queryKey: ["collector-feed", feedId] }),
        client.invalidateQueries({ queryKey: ["collector-settings"] }),
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invalid overrides");
    }
  };

  return (
    <div className="split-layout">
      <div className="panel">
        <h2>Global defaults</h2>
        <div className="form-grid compact-form">
          {([
            ["quote_interval_seconds", "Quote interval (seconds)"],
            ["candle_poll_seconds", "Candle poll (seconds)"],
            ["heartbeat_seconds", "Heartbeat (seconds)"],
            ["backfill_days", "Default backfill days"],
            ["backfill_batch_size", "Backfill batch size"],
            ["configuration_retry_seconds", "Configuration retry (seconds)"],
          ] as const).map(([key, label]) => (
            <label key={key}>{label}
              <input type="number" value={global[key]} onChange={(event) => setGlobal({ ...global, [key]: event.target.value })} />
            </label>
          ))}
          <button className="button button-primary" onClick={() => void saveGlobal()}>
            Save global settings
          </button>
        </div>
      </div>
      <div className="panel">
        <h2>Instrument override</h2>
        <label className="checkbox-row">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          Enabled
        </label>
        <label>Overrides JSON
          <textarea value={overrides} onChange={(event) => setOverrides(event.target.value)} />
        </label>
        <p className="muted">Use only global setting field names. Empty object inherits all defaults.</p>
        <button className="button button-primary" onClick={() => void saveInstrument()}>
          Save instrument settings
        </button>
        {message && <p className="success-text">{message}</p>}
        {error && <div className="error-box">{error}</div>}
      </div>
    </div>
  );
}

function CommandHistory({ commands }: { commands: CollectorCommand[] }) {
  const client = useQueryClient();
  const { feedId } = useParams<{ feedId: string }>();
  const [error, setError] = useState("");

  const deleteCommand = async (command: CollectorCommand) => {
    if (!window.confirm(`Delete ${command.command} command?`)) return;
    setError("");
    try {
      await api(`/api/v1/collector/commands/${command.id}`, { method: "DELETE" });
      await Promise.all([
        client.invalidateQueries({ queryKey: ["collector-feed", feedId] }),
        client.invalidateQueries({ queryKey: ["collector-overview"] }),
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Command could not be deleted.");
    }
  };

  return <div className="panel">
    <h2>Command history</h2>
    {!commands.length ? <p className="muted">No commands for this feed.</p> : (
      <div className="table-wrap borderless"><table>
        <thead>
          <tr><th>Created</th><th>Command</th><th>Status</th><th>Progress</th><th>Error</th><th>Actions</th></tr>
        </thead>
        <tbody>{commands.map((item) => (
          <tr key={item.id}>
            <td>{displayDate(item.created_at)}</td>
            <td>{item.command}</td>
            <td><StatusPill value={item.status} /></td>
            <td>{item.progress.processed !== undefined ? `${item.progress.processed} / ${item.progress.total ?? "?"}` : "--"}</td>
            <td className="error-text">{item.error ?? "--"}</td>
            <td>
              {["PENDING", "RUNNING"].includes(item.status) ? (
                <button className="button button-danger" onClick={() => void deleteCommand(item)}>
                  Delete
                </button>
              ) : "--"}
            </td>
          </tr>
        ))}</tbody>
      </table></div>
    )}
    {error && <div className="error-box table-actions">{error}</div>}
  </div>;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function KeyValues({ values }: { values: Record<string, unknown> | null }) {
  if (!values) return <p className="muted">Waiting for data.</p>;
  return <dl className="key-values">{Object.entries(values).map(([key, value]) => (
    <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(value)}</dd></div>
  ))}</dl>;
}

function Table({ headers, rows }: { headers: string[]; rows: Array<Array<string | number | boolean>> }) {
  return <div className="table-wrap borderless"><table>
    <thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={index}>
      {row.map((cell, cellIndex) => <td key={cellIndex}>{String(cell)}</td>)}
    </tr>)}</tbody>
  </table></div>;
}

function displayDate(value: string | null): string {
  return value
    ? `${new Date(value).toLocaleString(undefined, { timeZone: "UTC" })} UTC`
    : "--";
}

function localInput(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}
