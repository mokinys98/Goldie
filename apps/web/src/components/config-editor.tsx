"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type {
  BotConfig,
  ConfigurationSchema,
  ConfigVersion,
  StrategyMetadata,
  StrategyParameterMetadata,
} from "@/lib/types";
import { StatusPill } from "./status-pill";
import { FieldHelp } from "./field-help";

export function ConfigEditor({
  botId,
  versions,
  onChanged,
  strategyProfileId,
  configOverrides = {},
}: {
  botId: string;
  versions: ConfigVersion[];
  onChanged: () => void;
  strategyProfileId?: string | null;
  configOverrides?: Record<string, unknown>;
}) {
  const latest = versions[0];
  const strategies = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api<StrategyMetadata[]>("/api/v1/strategies"),
  });
  const configSchema = useQuery({
    queryKey: ["strategy-configuration-schema"],
    queryFn: () =>
      api<ConfigurationSchema>("/api/v1/strategies/configuration-schema"),
  });
  const inherited = useQuery({
    queryKey: ["strategy-profile", strategyProfileId],
    queryFn: () => api<{ config: BotConfig }>(`/api/v1/strategy-profiles/${strategyProfileId}`),
    enabled: Boolean(strategyProfileId),
  });

  async function transition(version: ConfigVersion, action: "validate" | "activate") {
    await api(`/api/v1/config-versions/${version.id}/${action}`, { method: "POST" });
    onChanged();
  }

  if (!latest) return <div className="panel">No configuration found.</div>;
  if (!strategyProfileId) {
    return (
      <div className="panel">
        <h2>Global strategy required</h2>
        <p>Assign a global strategy above to configure inheritance and bot-specific overrides.</p>
      </div>
    );
  }
  if (inherited.isLoading) return <div className="panel">Loading strategy configuration...</div>;
  if (inherited.error || !inherited.data) {
    return <div className="error-box">Could not load the assigned strategy configuration.</div>;
  }
  return (
    <div className="split-layout">
      <OverrideEditor
        botId={botId}
        inherited={inherited.data.config}
        effective={latest.config}
        overrides={configOverrides}
        strategies={strategies.data ?? []}
        configSchema={configSchema.data}
        onChanged={onChanged}
      />
      <VersionHistory versions={versions} transition={transition} />
    </div>
  );
}

function VersionHistory({
  versions,
  transition,
}: {
  versions: ConfigVersion[];
  transition: (version: ConfigVersion, action: "validate" | "activate") => Promise<void>;
}) {
  return (
    <div className="panel">
      <div className="section-title"><div><h2>Version history</h2><p>Every effective configuration is stored as an immutable snapshot.</p></div></div>
      <div className="version-list">
        {versions.map((version) => (
          <div className="version-card" key={version.id}>
            <div><strong>Version {version.version}</strong><span>{new Date(version.created_at).toLocaleString()}</span></div>
            <StatusPill value={version.status} />
            <div className="button-row">
              {version.status === "DRAFT" && <button className="button button-secondary" onClick={() => transition(version, "validate")}>Validate</button>}
              {version.status === "VALIDATED" && <button className="button button-primary" onClick={() => transition(version, "activate")}>Activate</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OverrideEditor({
  botId,
  inherited,
  effective,
  overrides,
  strategies,
  configSchema,
  onChanged,
}: {
  botId: string;
  inherited: BotConfig;
  effective: BotConfig;
  overrides: Record<string, unknown>;
  strategies: StrategyMetadata[];
  configSchema?: ConfigurationSchema;
  onChanged: () => void;
}) {
  const fields = flattenConfig(inherited, effective, overrides, strategies, configSchema);
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(fields.map((field) => [field.path, field.overridden])),
  );
  const [values, setValues] = useState<Record<string, string | number | boolean>>(
    Object.fromEntries(fields.map((field) => [field.path, field.effective])),
  );
  const [busy, setBusy] = useState(false);
  return (
    <div className="panel config-form">
      <div className="section-title">
        <div><h2>Strategy inheritance</h2><p>Enable only fields that this bot must override. Market fields always come from the assigned feed.</p></div>
      </div>
      <div className="override-table">
        {fields.map((field) => (
          <div className="override-row" key={field.path}>
            <label className="checkbox-row">
              <input type="checkbox" checked={enabled[field.path] ?? false} onChange={(event) => setEnabled((current) => ({ ...current, [field.path]: event.target.checked }))} />
              <FieldHelp label={field.label} metadata={field.metadata} />
            </label>
            <span className="inherited-value">Inherited: {String(field.inherited)}</span>
            {typeof field.effective === "boolean" ? (
              <select disabled={!enabled[field.path]} value={String(values[field.path])} onChange={(event) => setValues((current) => ({ ...current, [field.path]: event.target.value === "true" }))}><option value="false">false</option><option value="true">true</option></select>
            ) : (
              <input disabled={!enabled[field.path]} type={typeof field.effective === "number" ? "number" : "text"} value={String(values[field.path])} onChange={(event) => setValues((current) => ({ ...current, [field.path]: typeof field.effective === "number" ? Number(event.target.value) : event.target.value }))} />
            )}
          </div>
        ))}
      </div>
      <button
        className="button button-primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const next: Record<string, unknown> = {};
            for (const field of fields) if (enabled[field.path]) setNested(next, field.path, values[field.path]);
            await api(`/api/v1/bots/${botId}/overrides`, { method: "PUT", body: JSON.stringify({ overrides: next }) });
            onChanged();
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Saving..." : "Save and activate overrides"}
      </button>
    </div>
  );
}

function flattenConfig(
  inherited: BotConfig,
  effective: BotConfig,
  overrides: Record<string, unknown>,
  strategies: StrategyMetadata[],
  configSchema?: ConfigurationSchema,
) {
  const strategy = strategies.find((item) => item.name === inherited.strategy.name);
  const entries: Array<{ path: string; label: string; inherited: string | number | boolean; effective: string | number | boolean; overridden: boolean; metadata?: StrategyParameterMetadata }> = [];
  const add = (path: string, label: string, base: string | number | boolean, current: string | number | boolean, metadata?: StrategyParameterMetadata) => entries.push({ path, label, inherited: base, effective: current, overridden: hasNested(overrides, path), metadata });
  for (const [name, value] of Object.entries(inherited.strategy.parameters)) add(`strategy.parameters.${name}`, strategy?.parameters[name]?.title ?? name.replaceAll("_", " "), value, effective.strategy.parameters[name], strategy?.parameters[name]);
  add("filters.max_spread_points", "Maximum spread points", inherited.filters.max_spread_points, effective.filters.max_spread_points, configSchema?.filters?.max_spread_points);
  add("filters.stale_after_seconds", "Stale after seconds", inherited.filters.stale_after_seconds, effective.filters.stale_after_seconds, configSchema?.filters?.stale_after_seconds);
  add("session.timezone", "Timezone", inherited.session.timezone, effective.session.timezone, configSchema?.session?.timezone);
  add("session.start_time", "Start time", inherited.session.start_time, effective.session.start_time, configSchema?.session?.start_time);
  add("session.end_time", "End time", inherited.session.end_time, effective.session.end_time, configSchema?.session?.end_time);
  for (const key of Object.keys(inherited.theoretical_trade) as Array<keyof BotConfig["theoretical_trade"]>) add(`theoretical_trade.${key}`, key.replaceAll("_", " "), inherited.theoretical_trade[key], effective.theoretical_trade[key], configSchema?.theoretical_trade?.[key]);
  return entries;
}

function hasNested(value: Record<string, unknown>, path: string): boolean {
  let current: unknown = value;
  for (const part of path.split(".")) {
    if (!current || typeof current !== "object" || !(part in current)) return false;
    current = (current as Record<string, unknown>)[part];
  }
  return true;
}

function setNested(target: Record<string, unknown>, path: string, value: unknown) {
  const parts = path.split(".");
  let current = target;
  parts.slice(0, -1).forEach((part) => {
    current[part] = (current[part] as Record<string, unknown>) ?? {};
    current = current[part] as Record<string, unknown>;
  });
  current[parts.at(-1)!] = value;
}
