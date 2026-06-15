"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, openBotStream } from "@/lib/api";
import type {
  Bot,
  BotStatus,
  ConfigVersion,
  MarketFeed,
  Performance,
  Run,
  ShadowTrade,
  Signal,
  StrategyProfile,
} from "@/lib/types";
import { ConfigEditor } from "@/components/config-editor";
import { MarketChart } from "@/components/market-chart";
import { useNotifications } from "@/components/notification-center";
import { PerformancePanel } from "@/components/performance-panel";
import { StatusPill } from "@/components/status-pill";

const tabs = [
  "Overview",
  "Configuration",
  "Live Monitor",
  "Signals",
  "Performance",
  "Run History",
] as const;
type Tab = (typeof tabs)[number];

export default function BotDetailPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const { notify } = useNotifications();
  const [tab, setTab] = useState<Tab>("Overview");
  const [selectedFeedId, setSelectedFeedId] = useState("");
  const [isAssigningFeed, setIsAssigningFeed] = useState(false);
  const [editingBot, setEditingBot] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editMode, setEditMode] = useState<"SHADOW" | "PAPER">("SHADOW");

  const bot = useQuery({
    queryKey: ["bot", id],
    queryFn: () => api<Bot>(`/api/v1/bots/${id}`),
  });
  const status = useQuery({
    queryKey: ["bot-status", id],
    queryFn: () => api<BotStatus>(`/api/v1/bots/${id}/status`),
    refetchInterval: 5000,
  });
  const configs = useQuery({
    queryKey: ["configs", id],
    queryFn: () => api<ConfigVersion[]>(`/api/v1/bots/${id}/config-versions`),
  });
  const signals = useQuery({
    queryKey: ["signals", id],
    queryFn: () => api<Signal[]>(`/api/v1/bots/${id}/signals`),
  });
  const runs = useQuery({
    queryKey: ["runs", id],
    queryFn: () => api<Run[]>(`/api/v1/bots/${id}/runs`),
  });
  const feeds = useQuery({
    queryKey: ["market-feeds"],
    queryFn: () => api<MarketFeed[]>("/api/v1/market-feeds"),
  });
  const performance = useQuery({
    queryKey: ["performance", id],
    queryFn: () => api<Performance>(`/api/v1/bots/${id}/performance`),
    refetchInterval: 10000,
  });
  const shadowTrades = useQuery({
    queryKey: ["shadow-trades", id],
    queryFn: () => api<ShadowTrade[]>(`/api/v1/bots/${id}/shadow-trades?limit=200`),
    refetchInterval: 10000,
  });
  const strategyProfiles = useQuery({
    queryKey: ["strategy-profiles"],
    queryFn: () => api<StrategyProfile[]>("/api/v1/strategy-profiles"),
  });
  const [selectedStrategyProfileId, setSelectedStrategyProfileId] = useState("");

  useEffect(
    () =>
      openBotStream(id, () => {
        client.invalidateQueries({ queryKey: ["bot-status", id] });
        client.invalidateQueries({ queryKey: ["signals", id] });
        client.invalidateQueries({ queryKey: ["performance", id] });
        client.invalidateQueries({ queryKey: ["shadow-trades", id] });
      }),
    [client, id],
  );

  useEffect(() => {
    setSelectedFeedId(bot.data?.market_feed_id ?? "");
  }, [bot.data?.market_feed_id]);

  const refreshConfig = () => {
    client.invalidateQueries({ queryKey: ["configs", id] });
    client.invalidateQueries({ queryKey: ["bot", id] });
    client.invalidateQueries({ queryKey: ["bot-status", id] });
    client.invalidateQueries({ queryKey: ["runs", id] });
  };

  const assignFeed = async () => {
    if (!selectedFeedId || selectedFeedId === bot.data?.market_feed_id) return;
    const selectedFeed = feeds.data?.find((feed) => feed.id === selectedFeedId);
    setIsAssigningFeed(true);
    try {
      await api<Bot>(`/api/v1/bots/${id}/market-feed`, {
        method: "PUT",
        body: JSON.stringify({ market_feed_id: selectedFeedId }),
      });
      await Promise.all([
        client.invalidateQueries({ queryKey: ["bot", id] }),
        client.invalidateQueries({ queryKey: ["bot-status", id] }),
      ]);
      notify({
        kind: "success",
        position: "right",
        title: "Market feed updated",
        message: selectedFeed
          ? `${selectedFeed.provider.toUpperCase()} ${selectedFeed.provider_symbol} was assigned successfully.`
          : "The selected market feed was assigned successfully.",
      });
    } catch (caught) {
      setSelectedFeedId(bot.data?.market_feed_id ?? "");
      notify({
        kind: "error",
        position: "left",
        title: "Market feed update failed",
        message: caught instanceof Error ? caught.message : "Could not assign market feed.",
      });
    } finally {
      setIsAssigningFeed(false);
    }
  };

  if (bot.isLoading) return <div className="panel">Loading bot...</div>;
  if (bot.error || !bot.data) {
    return (
      <div className="error-box">
        Could not load bot. <button onClick={() => router.push("/bots")}>Back</button>
      </div>
    );
  }

  const live = status.data;
  return (
    <section>
      <header className="page-header bot-header">
        <div>
          <span className="eyebrow">BOT INSTANCE</span>
          <h1>{bot.data.name}</h1>
          <p>{bot.data.description || "No description"}</p>
        </div>
        <div className="header-statuses">
          <StatusPill value={bot.data.mode} />
          <StatusPill value={live?.agent_effective_status ?? "OFFLINE"} />
          <span className="readonly-badge">NO ORDER EXECUTION</span>
          <button className="button button-secondary" onClick={() => {
            setEditName(bot.data.name);
            setEditDescription(bot.data.description);
            setEditMode(bot.data.mode);
            setEditingBot(true);
          }}>Edit</button>
          <button className="button button-danger" onClick={async () => {
            if (!window.confirm("Archive this bot? Historical results will remain.")) return;
            await api(`/api/v1/bots/${id}`, { method: "DELETE" });
            router.push("/bots");
          }}>Delete</button>
        </div>
      </header>
      {editingBot && (
        <form className="panel compact-form form-grid" onSubmit={async (event) => {
          event.preventDefault();
          await api(`/api/v1/bots/${id}`, {
            method: "PATCH",
            body: JSON.stringify({
              name: editName,
              description: editDescription,
              mode: editMode,
            }),
          });
          setEditingBot(false);
          await client.invalidateQueries({ queryKey: ["bot", id] });
        }}>
          <label>Name<input required value={editName} onChange={(event) => setEditName(event.target.value)} /></label>
          <label>Description<input value={editDescription} onChange={(event) => setEditDescription(event.target.value)} /></label>
          <label>Mode<select value={editMode} onChange={(event) => setEditMode(event.target.value as "SHADOW" | "PAPER")}><option value="SHADOW">SHADOW</option><option value="PAPER">PAPER</option></select></label>
          <div className="button-row"><button className="button button-primary">Save</button><button type="button" className="button button-secondary" onClick={() => setEditingBot(false)}>Cancel</button></div>
        </form>
      )}
      <div className="tabs">
        {tabs.map((item) => (
          <button
            className={tab === item ? "active" : ""}
            key={item}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === "Overview" && (
        <div className="dashboard-grid">
          <Metric label="Agent" value={live?.agent_effective_status ?? "OFFLINE"} />
          <Metric label="Data" value={live?.data_state ?? "MISSING"} />
          <Metric label="Bid" value={live?.latest_tick?.bid ?? "--"} />
          <Metric label="Ask" value={live?.latest_tick?.ask ?? "--"} />
          <Metric label="Latest signal" value={live?.latest_signal?.signal ?? "--"} />
          <Metric label="Run" value={live?.active_run_id?.slice(0, 8) ?? "Not active"} />
          <Metric label="Shadow net P&L" value={money(performance.data?.net_pnl)} />
          <Metric label="Win rate" value={percent(performance.data?.win_rate)} />
          <Metric label="Profit factor" value={metric(performance.data?.profit_factor)} />
          <Metric label="Max drawdown" value={money(performance.data?.max_drawdown)} />
          <div className="panel grid-span-2">
            <h2>Market feed</h2>
            <div className="market-feed-control">
              <select
                value={selectedFeedId}
                onChange={(event) => setSelectedFeedId(event.target.value)}
                disabled={!feeds.data?.length || isAssigningFeed}
              >
                <option value="">No feed assigned</option>
                {(feeds.data ?? []).map((feed) => (
                  <option key={feed.id} value={feed.id}>
                    {feed.provider.toUpperCase()} {feed.provider_symbol} ({feed.status})
                  </option>
                ))}
              </select>
              <button
                className="button button-primary"
                disabled={
                  !selectedFeedId ||
                  selectedFeedId === bot.data.market_feed_id ||
                  isAssigningFeed
                }
                onClick={() => void assignFeed()}
                type="button"
              >
                {isAssigningFeed ? "Confirming..." : "Confirm change"}
              </button>
            </div>
          </div>
          <div className="panel grid-span-2">
            <h2>Completed M1 close</h2>
            <MarketChart
              candles={live?.recent_candles ?? []}
              precision={symbolPrecision(live?.symbol_specification)}
              bid={live?.latest_tick?.bid}
              ask={live?.latest_tick?.ask}
              symbol={live?.latest_tick?.symbol}
            />
          </div>
          <div className="panel">
            <h2>Paper account</h2>
            <KeyValues values={live?.paper_account ?? null} />
          </div>
          <div className="panel">
            <h2>Symbol specification</h2>
            <KeyValues values={live?.symbol_specification ?? null} />
          </div>
          <div className="panel">
            <h2>Active shadow position</h2>
            <KeyValues values={live?.active_shadow_trade ?? null} />
          </div>
        </div>
      )}

      {tab === "Configuration" && configs.data && (
        <>
          <div className="panel strategy-assignment">
            <div>
              <h2>Global strategy</h2>
              <p className="muted">{bot.data.strategy_profile_id ? "This bot inherits the current global strategy." : "Standalone configuration. Assign a strategy to start inheriting it."}</p>
            </div>
            <select value={selectedStrategyProfileId} onChange={(event) => setSelectedStrategyProfileId(event.target.value)}>
              <option value="">Select strategy</option>
              {(strategyProfiles.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <button className="button button-secondary" disabled={!selectedStrategyProfileId} onClick={async () => { await api(`/api/v1/bots/${id}/apply-strategy`, { method: "POST", body: JSON.stringify({ strategy_profile_id: selectedStrategyProfileId }) }); setSelectedStrategyProfileId(""); refreshConfig(); }}>Apply and activate</button>
          </div>
          <ConfigEditor
            botId={id}
            versions={configs.data}
            onChanged={refreshConfig}
            strategyProfileId={bot.data.strategy_profile_id}
            configOverrides={bot.data.config_overrides}
          />
        </>
      )}

      {tab === "Live Monitor" && (
        <div className="dashboard-grid">
          <div className="panel grid-span-2">
            <div className="section-title">
              <div>
                <h2>Market stream</h2>
                <p>Only completed M1 candles feed the strategy.</p>
              </div>
              <StatusPill value={live?.data_state ?? "MISSING"} />
            </div>
            <MarketChart
              candles={live?.recent_candles ?? []}
              precision={symbolPrecision(live?.symbol_specification)}
              bid={live?.latest_tick?.bid}
              ask={live?.latest_tick?.ask}
              symbol={live?.latest_tick?.symbol}
            />
          </div>
          <div className="panel">
            <h2>Latest tick</h2>
            <KeyValues values={live?.latest_tick ?? null} />
          </div>
          <div className="panel">
            <h2>Latest decision</h2>
            <KeyValues values={live?.latest_signal ?? null} />
          </div>
          <div className="panel">
            <h2>Active shadow position</h2>
            <KeyValues values={live?.active_shadow_trade ?? null} />
          </div>
        </div>
      )}

      {tab === "Signals" && (
        <DataTable
          empty="No theoretical signals yet."
          headers={[
            "Time",
            "Decision",
            "Reason",
            "Momentum",
            "Spread",
            "Entry",
            "SL",
            "TP",
            "Indicators",
            "Outcome",
          ]}
          rows={(signals.data ?? []).map((signal) => [
            new Date(signal.observed_at).toLocaleString(),
            signal.signal,
            signal.reason_code,
            signal.momentum_points ?? "--",
            signal.spread_points ?? "--",
            signal.entry_price ?? "--",
            signal.stop_loss ?? "--",
            signal.take_profit ?? "--",
            formatInputs(signal.inputs),
            signal.outcome?.result ??
              signal.outcome?.skip_reason ??
              signal.outcome?.status ??
              "--",
          ])}
        />
      )}

      {tab === "Performance" && (
        <PerformancePanel
          performance={performance.data}
          trades={shadowTrades.data ?? []}
        />
      )}

      {tab === "Run History" && (
        <DataTable
          empty="Activate a validated configuration to create the first run."
          headers={["Run", "Mode", "Status", "Started", "Ended"]}
          rows={(runs.data ?? []).map((run) => [
            run.id.slice(0, 8),
            run.mode,
            run.status,
            new Date(run.created_at).toLocaleString(),
            run.ended_at ? new Date(run.ended_at).toLocaleString() : "--",
          ])}
        />
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function KeyValues({ values }: { values: Record<string, unknown> | null }) {
  if (!values) return <p className="muted">Waiting for data.</p>;
  return (
    <dl className="key-values">
      {Object.entries(values).map(([key, value]) => (
        <div key={key}>
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function DataTable({
  headers,
  rows,
  empty,
}: {
  headers: string[];
  rows: string[][];
  empty: string;
}) {
  if (!rows.length) {
    return (
      <div className="empty-state">
        <p>{empty}</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function money(value: string | number | null | undefined): string {
  return formatDecimal(value, 2);
}

function percent(value: string | number | null | undefined): string {
  const formatted = formatDecimal(value, 1);
  return formatted === "--" ? formatted : `${formatted}%`;
}

function metric(value: string | number | null | undefined): string {
  return formatDecimal(value, 2);
}

function formatDecimal(
  value: string | number | null | undefined,
  digits: number,
): string {
  if (value === null || value === undefined) return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "--";
}

function symbolPrecision(
  specification: Record<string, string | number> | null | undefined,
): number {
  const value = Number(specification?.display_precision);
  return Number.isInteger(value) && value >= 0 && value <= 10 ? value : 4;
}

function formatInputs(inputs: Record<string, unknown>): string {
  return Object.entries(inputs)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");
}
