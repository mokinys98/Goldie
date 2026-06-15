"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  BotConfig,
  BulkBotResult,
  MarketFeed,
  StrategyProfile,
  StrategyVersion,
} from "@/lib/types";
import { StatusPill } from "@/components/status-pill";
import { StrategyConfigForm } from "@/components/strategy-config-form";

export default function StrategyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const profile = useQuery({
    queryKey: ["strategy-profile", id],
    queryFn: () => api<StrategyProfile>(`/api/v1/strategy-profiles/${id}`),
  });
  const versions = useQuery({
    queryKey: ["strategy-versions", id],
    queryFn: () => api<StrategyVersion[]>(`/api/v1/strategy-profiles/${id}/versions`),
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["strategy-profile", id] }),
      client.invalidateQueries({ queryKey: ["strategy-versions", id] }),
      client.invalidateQueries({ queryKey: ["strategy-profiles"] }),
    ]);
  };
  if (profile.isLoading || versions.isLoading) return <div className="panel">Loading strategy...</div>;
  if (!profile.data) return <div className="error-box">Strategy could not be loaded.</div>;
  const latest = versions.data?.[0];
  return (
    <section>
      <header className="page-header">
        <div>
          <span className="eyebrow">GLOBAL STRATEGY</span>
          <h1>{profile.data.name}</h1>
          <p>{profile.data.description || "No description"}</p>
        </div>
        <div className="header-statuses">
          <StatusPill value={profile.data.status} />
          {profile.data.current_published_version_id && (
            <Link className="button button-primary" href={`/strategies/${id}#bulk`}>Create bots</Link>
          )}
        </div>
      </header>
      <div className="split-layout">
        <div className="panel">
          <div className="section-title">
            <div><h2>Version history</h2><p>Published versions are immutable.</p></div>
            <button className="button button-secondary" onClick={() => setEditing((value) => !value)}>
              {editing ? "Close editor" : "Create new version"}
            </button>
          </div>
          <div className="version-list">
            {(versions.data ?? []).map((version) => (
              <div className="version-card" key={version.id}>
                <div><strong>Version {version.version}</strong><span>{version.config.strategy.name} · {new Date(version.created_at).toLocaleString()}</span></div>
                <StatusPill value={version.status} />
                <div className="button-row">
                  {version.status === "DRAFT" && <button className="button button-secondary" onClick={async () => { await api(`/api/v1/strategy-versions/${version.id}/validate`, { method: "POST" }); await refresh(); }}>Validate</button>}
                  {version.status === "VALIDATED" && <button className="button button-primary" onClick={async () => { await api(`/api/v1/strategy-versions/${version.id}/publish`, { method: "POST" }); await refresh(); }}>Publish</button>}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <h2>Usage</h2>
          <dl className="key-values">
            <div><dt>Linked bots</dt><dd>{profile.data.bot_count}</dd></div>
            <div><dt>Published version</dt><dd>{profile.data.published_version ? `v${profile.data.published_version.version}` : "--"}</dd></div>
            <div><dt>Algorithm</dt><dd>{profile.data.published_version?.config.strategy.name ?? "--"}</dd></div>
          </dl>
        </div>
      </div>
      {editing && latest && (
        <div className="strategy-editor-section">
          <StrategyConfigForm
            initialConfig={latest.config}
            submitLabel="Save as new strategy version"
            onSubmit={async (config: BotConfig) => {
              await api(`/api/v1/strategy-profiles/${id}/versions`, {
                method: "POST",
                body: JSON.stringify({ config }),
              });
              setEditing(false);
              await refresh();
            }}
          />
        </div>
      )}
      {profile.data.published_version && (
        <BulkCreate
          strategy={profile.data}
          version={profile.data.published_version}
        />
      )}
    </section>
  );
}

function BulkCreate({ strategy, version }: { strategy: StrategyProfile; version: StrategyVersion }) {
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
    () =>
      (feeds.data ?? [])
        .filter((feed) => selected.includes(feed.id))
        .map((feed) => ({
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
        <div><h2>Create bots</h2><p>One draft bot will be created for every selected market feed using strategy v{version.version}.</p></div>
      </div>
      <div className="bulk-grid">
        <div>
          <h3>1. Market feeds</h3>
          <div className="selection-list">
            {(feeds.data ?? []).map((feed) => (
              <label className="checkbox-row" key={feed.id}>
                <input type="checkbox" checked={selected.includes(feed.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, feed.id] : current.filter((id) => id !== feed.id))} />
                {feed.canonical_symbol} · {feed.provider} · {feed.status}
              </label>
            ))}
          </div>
        </div>
        <div className="form-grid">
          <h3>2. Naming and mode</h3>
          <label>Mode<select value={mode} onChange={(event) => setMode(event.target.value as "SHADOW" | "PAPER")}><option value="SHADOW">SHADOW</option><option value="PAPER">PAPER</option></select></label>
          <label>Name template<input value={template} onChange={(event) => setTemplate(event.target.value)} /><small>Available: {"{symbol} {strategy} {mode}"}</small></label>
        </div>
      </div>
      {!!previews.length && (
        <div className="table-wrap">
          <table><thead><tr><th>Feed</th><th>Generated name</th></tr></thead><tbody>{previews.map(({ feed, name }) => <tr key={feed.id}><td>{feed.canonical_symbol}</td><td>{name}</td></tr>)}</tbody></table>
        </div>
      )}
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
                  strategy_version_id: version.id,
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
          {busy ? "Creating..." : `Create ${selected.length} draft bot(s)`}
        </button>
      </div>
      {!!results.length && (
        <div className="table-wrap table-actions">
          <table><thead><tr><th>Name</th><th>Status</th><th>Result</th></tr></thead><tbody>{results.map((result) => <tr key={result.market_feed_id}><td>{result.bot ? <Link className="table-link" href={`/bots/${result.bot.id}`}>{result.name}</Link> : result.name || "--"}</td><td><StatusPill value={result.status} /></td><td>{result.error ?? "Draft created"}</td></tr>)}</tbody></table>
        </div>
      )}
    </div>
  );
}
