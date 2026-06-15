"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { api } from "@/lib/api";
import {
  botConfigSchema,
  defaultBotConfig,
  normalizeBotConfig,
} from "@/lib/config";
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
  strategyVersionId,
  configOverrides = {},
}: {
  botId: string;
  versions: ConfigVersion[];
  onChanged: () => void;
  strategyVersionId?: string | null;
  configOverrides?: Record<string, unknown>;
}) {
  const latest = versions[0];
  const strategies = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api<StrategyMetadata[]>("/api/v1/strategies"),
  });
  const initialConfig = latest ? normalizeBotConfig(latest.config) : defaultBotConfig;
  const [strategyName, setStrategyName] = useState(initialConfig.strategy.name);
  const form = useForm<BotConfig>({
    resolver: zodResolver(botConfigSchema),
    defaultValues: initialConfig,
  });
  const selected = strategies.data?.find((item) => item.name === strategyName);
  const configSchema = useQuery({
    queryKey: ["strategy-configuration-schema"],
    queryFn: () =>
      api<ConfigurationSchema>("/api/v1/strategies/configuration-schema"),
  });
  const inherited = useQuery({
    queryKey: ["strategy-version", strategyVersionId],
    queryFn: () => api<{ config: BotConfig }>(`/api/v1/strategy-versions/${strategyVersionId}`),
    enabled: Boolean(strategyVersionId),
  });

  async function create(values: BotConfig) {
    await api(`/api/v1/bots/${botId}/config-versions`, {
      method: "POST",
      body: JSON.stringify({ config: values }),
    });
    onChanged();
  }

  async function transition(version: ConfigVersion, action: "validate" | "activate") {
    await api(`/api/v1/config-versions/${version.id}/${action}`, { method: "POST" });
    onChanged();
  }

  function selectStrategy(name: string) {
    const metadata = strategies.data?.find((item) => item.name === name);
    setStrategyName(name);
    form.setValue("strategy.name", name, { shouldValidate: true });
    form.setValue("strategy.parameters", metadata?.defaults ?? {}, {
      shouldDirty: true,
      shouldValidate: true,
    });
  }

  if (!latest) return <div className="panel">No configuration found.</div>;
  if (strategyVersionId && inherited.data) {
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

  return (
    <div className="split-layout">
      <form className="panel config-form" onSubmit={form.handleSubmit(create)}>
        <div className="section-title">
          <div>
            <h2>Configuration editor</h2>
            <p>Saving always creates a new immutable draft.</p>
          </div>
          <StatusPill value={latest.status} />
        </div>
        <fieldset>
          <legend>Market and strategy</legend>
          <label>
            <FieldHelp label="Symbol" metadata={configSchema.data?.market?.symbol} />
            <input {...form.register("market.symbol")} readOnly />
            <small>Controlled by the bot&apos;s assigned market feed.</small>
          </label>
          <label><FieldHelp label="Timeframe" metadata={configSchema.data?.market?.timeframe} /><input {...form.register("market.timeframe")} readOnly /></label>
          <label>
            <FieldHelp label="Strategy" metadata={configSchema.data?.strategy?.name} />
            <select
              aria-label="Strategy"
              name="strategy.name"
              value={strategyName}
              disabled={strategies.isLoading || !strategies.data?.length}
              onChange={(event) => selectStrategy(event.target.value)}
            >
              {!strategies.data?.length && (
                <option value="">Loading strategies...</option>
              )}
              {(strategies.data ?? []).map((strategy) => (
                <option key={strategy.name} value={strategy.name}>
                  {strategy.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Required history
            <input value={selected ? `${selected.required_candles} M1 candles` : "--"} disabled />
          </label>
          {selected && (
            <p className="fieldset-description">{selected.description}</p>
          )}
          {selected &&
            Object.entries(selected.parameters).map(([name, metadata]) => (
              <StrategyParameter
                key={name}
                name={name}
                metadata={metadata}
                register={form.register}
              />
            ))}
        </fieldset>
        <fieldset>
          <legend>Filters</legend>
          <label><FieldHelp label="Maximum spread points" metadata={configSchema.data?.filters?.max_spread_points} /><input type="number" step="0.01" {...form.register("filters.max_spread_points")} /></label>
          <label><FieldHelp label="Stale after seconds" metadata={configSchema.data?.filters?.stale_after_seconds} /><input type="number" {...form.register("filters.stale_after_seconds")} /></label>
        </fieldset>
        <fieldset>
          <legend>Session</legend>
          <label><FieldHelp label="Timezone" metadata={configSchema.data?.session?.timezone} /><input {...form.register("session.timezone")} /></label>
          <label><FieldHelp label="Start time" metadata={configSchema.data?.session?.start_time} /><input type="time" step="1" {...form.register("session.start_time")} /></label>
          <label><FieldHelp label="End time" metadata={configSchema.data?.session?.end_time} /><input type="time" step="1" {...form.register("session.end_time")} /></label>
        </fieldset>
        <fieldset>
          <legend>Shadow trade model</legend>
          <label><FieldHelp label="Stop loss points" metadata={configSchema.data?.theoretical_trade?.stop_loss_points} /><input type="number" step="0.01" {...form.register("theoretical_trade.stop_loss_points")} /></label>
          <label><FieldHelp label="Take profit points" metadata={configSchema.data?.theoretical_trade?.take_profit_points} /><input type="number" step="0.01" {...form.register("theoretical_trade.take_profit_points")} /></label>
          <label><FieldHelp label="Risk per trade %" metadata={configSchema.data?.theoretical_trade?.risk_per_trade_pct} /><input type="number" step="0.01" {...form.register("theoretical_trade.risk_per_trade_pct")} /></label>
          <label><FieldHelp label="Maximum duration minutes" metadata={configSchema.data?.theoretical_trade?.max_trade_duration_minutes} /><input type="number" {...form.register("theoretical_trade.max_trade_duration_minutes")} /></label>
          <label><FieldHelp label="Maximum open shadow positions" metadata={configSchema.data?.theoretical_trade?.max_open_shadow_positions} /><input type="number" min="1" max="1" {...form.register("theoretical_trade.max_open_shadow_positions")} /></label>
        </fieldset>
        {Object.keys(form.formState.errors).length > 0 && (
          <div className="error-box">Configuration contains invalid values.</div>
        )}
        <button className="button button-primary">Save as new draft</button>
      </form>
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
        {busy ? "Saving..." : "Save overrides as new draft"}
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

function StrategyParameter({
  name,
  metadata,
  register,
}: {
  name: string;
  metadata: StrategyParameterMetadata;
  register: ReturnType<typeof useForm<BotConfig>>["register"];
}) {
  const label = metadata.title ?? name.replaceAll("_", " ");
  if (metadata.type === "boolean") {
    return (
      <label className="checkbox-row">
        <input aria-label={label} type="checkbox" {...register(`strategy.parameters.${name}`)} />
        <FieldHelp label={label} metadata={metadata} />
      </label>
    );
  }
  return (
    <label>
      <FieldHelp label={label} metadata={metadata} />
      <input
        aria-label={label}
        type="number"
        step={metadata.type === "integer" ? 1 : "any"}
        min={metadata.minimum ?? metadata.exclusiveMinimum}
        max={metadata.maximum}
        {...register(`strategy.parameters.${name}`, {
          valueAsNumber: true,
        })}
      />
    </label>
  );
}
