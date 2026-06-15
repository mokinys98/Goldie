"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  BotConfig,
  BulkBotResult,
  MarketFeed,
  StrategyProfile,
} from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { StrategyConfigForm } from "@/components/strategy-config-form";

export default function StrategyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const profile = useQuery({
    queryKey: ["strategy-profile", id],
    queryFn: () => api<StrategyProfile>(`/api/v1/strategy-profiles/${id}`),
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["strategy-profile", id] }),
      client.invalidateQueries({ queryKey: ["strategy-profiles"] }),
    ]);
  };
  if (profile.isLoading) return <div className="panel">Loading strategy...</div>;
  if (!profile.data) return <div className="error-box">Strategy could not be loaded.</div>;
  const data = profile.data;
  const startEditing = () => {
    setName(data.name);
    setDescription(data.description);
    setEditing(true);
  };
  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">GLOBAL STRATEGY</span>
          <h1>{data.name}</h1>
          <p>{data.description || "No description"}</p>
        </div>
        <div className="header-statuses">
          <StatusPill value={data.status} />
          <button className="button button-secondary" onClick={startEditing}>Edit</button>
          <button
            className="button button-danger"
            onClick={async () => {
              if (!window.confirm("Archive this strategy? Existing bots and history will remain.")) return;
              await api(`/api/v1/strategy-profiles/${id}`, { method: "DELETE" });
              router.push("/strategies");
            }}
          >
            Delete
          </button>
        </div>
      </header>
      {editing && (
        <div className="strategy-editor-section">
          <div className="panel">
            <div className="section-title">
              <div>
                <h2>Edit strategy</h2>
                <p>Saving updates this strategy and activates the new configuration for linked bots.</p>
              </div>
              <button className="button button-secondary" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
            <div className="strategy-identity-grid">
              <label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
              <label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            </div>
          </div>
          <StrategyConfigForm
            initialConfig={data.config}
            submitLabel="Save strategy"
            onSubmit={async (config: BotConfig) => {
              await api(`/api/v1/strategy-profiles/${id}`, {
                method: "PATCH",
                body: JSON.stringify({ name, description, config }),
              });
              setEditing(false);
              await refresh();
            }}
          />
        </div>
      )}
      {!editing && (
        <>
          <div className="split-layout">
            <div className="panel">
              <h2>Current parameters</h2>
              <ConfigValues config={data.config} />
            </div>
            <div className="panel">
              <h2>Usage</h2>
              <dl className="key-values">
                <div><dt>Linked bots</dt><dd>{data.bot_count}</dd></div>
                <div><dt>Algorithm</dt><dd>{data.config.strategy.name}</dd></div>
                <div><dt>Updated</dt><dd>{new Date(data.updated_at).toLocaleString()}</dd></div>
              </dl>
            </div>
          </div>
          <BulkCreate strategy={data} />
        </>
      )}
    </section>
  );
}

function ConfigValues({ config }: { config: BotConfig }) {
  const rows = [
    ["Market", `${config.market.symbol} ${config.market.timeframe}`],
    ["Strategy", config.strategy.name],
    ...Object.entries(config.strategy.parameters).map(([key, value]) => [key, String(value)]),
    ...Object.entries(config.filters).map(([key, value]) => [key, String(value)]),
    ...Object.entries(config.session).map(([key, value]) => [key, String(value)]),
    ...Object.entries(config.theoretical_trade).map(([key, value]) => [key, String(value)]),
  ];
  return <dl className="key-values">{rows.map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl>;
}

function BulkCreate({ strategy }: { strategy: StrategyProfile }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<"SHADOW" | "PAPER">("SHADOW");
  const [template, setTemplate] = useState("{symbol}-{strategy}-{mode}");
  const [results, setResults] = useState<BulkBotResult[]>([]);
  const [busy, setBusy] = useState(false);
  const feeds = useQuery({
    queryKey: ["market-feeds"],
    queryFn: () => api<MarketFeed[]>("/api/v1/market-feeds"),
  });
  const previews = useMemo(
    () => (feeds.data ?? []).filter((feed) => selected.includes(feed.id)).map((feed) => ({
      feed,
      name: template
        .replaceAll("{symbol}", feed.canonical_symbol)
        .replaceAll("{strategy}", strategy.name.toLowerCase().replaceAll(" ", "-"))
        .replaceAll("{mode}", mode.toLowerCase()),
    })),
    [feeds.data, mode, selected, strategy.name, template],
  );
  return (
    <div className="panel strategy-editor-section" id="bulk">
      <div className="section-title">
        <div><h2>Create bots</h2><p>Selected bots are created and activated immediately.</p></div>
      </div>
      <div className="bulk-grid">
        <div>
          <h3>1. Market feeds</h3>
          <div className="selection-list">
            {(feeds.data ?? []).map((feed) => (
              <label className="checkbox-row" key={feed.id}>
                <input type="checkbox" checked={selected.includes(feed.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, feed.id] : current.filter((value) => value !== feed.id))} />
                {feed.canonical_symbol} · {feed.provider} · {feed.status}
              </label>
            ))}
          </div>
        </div>
        <div className="form-grid bulk-controls">
          <h3>2. Naming and mode</h3>
          <label>Mode<select value={mode} onChange={(event) => setMode(event.target.value as "SHADOW" | "PAPER")}><option value="SHADOW">SHADOW</option><option value="PAPER">PAPER</option></select></label>
          <label>Name template<input value={template} onChange={(event) => setTemplate(event.target.value)} /></label>
        </div>
      </div>
      {!!previews.length && <div className="table-wrap"><table><thead><tr><th>Feed</th><th>Generated name</th></tr></thead><tbody>{previews.map(({ feed, name }) => <tr key={feed.id}><td>{feed.canonical_symbol}</td><td>{name}</td></tr>)}</tbody></table></div>}
      <div className="button-row table-actions">
        <button
          className="button button-primary"
          disabled={!selected.length || busy}
          onClick={async () => {
            setBusy(true);
            try {
              setResults(await api<BulkBotResult[]>("/api/v1/bots/bulk", {
                method: "POST",
                body: JSON.stringify({
                  request_id: crypto.randomUUID(),
                  strategy_profile_id: strategy.id,
                  market_feed_ids: selected,
                  mode,
                  name_template: template,
                }),
              }));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Creating..." : `Create ${selected.length} bot(s)`}
        </button>
      </div>
      {!!results.length && <div className="table-wrap table-actions"><table><thead><tr><th>Name</th><th>Status</th><th>Result</th></tr></thead><tbody>{results.map((result) => <tr key={result.market_feed_id}><td>{result.bot ? <Link className="table-link" href={`/bots/${result.bot.id}`}>{result.name}</Link> : result.name || "--"}</td><td><StatusPill value={result.status} /></td><td>{result.error ?? "Created and activated"}</td></tr>)}</tbody></table></div>}
    </div>
  );
}
