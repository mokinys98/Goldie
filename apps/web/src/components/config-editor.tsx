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
  ConfigVersion,
  StrategyMetadata,
  StrategyParameterMetadata,
} from "@/lib/types";
import { StatusPill } from "./status-pill";

export function ConfigEditor({
  botId,
  versions,
  onChanged,
}: {
  botId: string;
  versions: ConfigVersion[];
  onChanged: () => void;
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
            Symbol
            <input {...form.register("market.symbol")} readOnly />
            <small>Controlled by the bot&apos;s assigned market feed.</small>
          </label>
          <label>Timeframe<input {...form.register("market.timeframe")} readOnly /></label>
          <label>
            Strategy
            <select
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
          <label>Maximum spread points<input type="number" step="0.01" {...form.register("filters.max_spread_points")} /></label>
          <label>Stale after seconds<input type="number" {...form.register("filters.stale_after_seconds")} /></label>
        </fieldset>
        <fieldset>
          <legend>Session</legend>
          <label>Timezone<input {...form.register("session.timezone")} /></label>
          <label>Start time<input type="time" step="1" {...form.register("session.start_time")} /></label>
          <label>End time<input type="time" step="1" {...form.register("session.end_time")} /></label>
        </fieldset>
        <fieldset>
          <legend>Shadow trade model</legend>
          <label>Stop loss points<input type="number" step="0.01" {...form.register("theoretical_trade.stop_loss_points")} /></label>
          <label>Take profit points<input type="number" step="0.01" {...form.register("theoretical_trade.take_profit_points")} /></label>
          <label>Risk per trade %<input type="number" step="0.01" {...form.register("theoretical_trade.risk_per_trade_pct")} /></label>
          <label>Maximum duration minutes<input type="number" {...form.register("theoretical_trade.max_trade_duration_minutes")} /></label>
          <label>Maximum open shadow positions<input type="number" min="1" max="1" {...form.register("theoretical_trade.max_open_shadow_positions")} /></label>
        </fieldset>
        {Object.keys(form.formState.errors).length > 0 && (
          <div className="error-box">Configuration contains invalid values.</div>
        )}
        <button className="button button-primary">Save as new draft</button>
      </form>
      <div className="panel">
        <div className="section-title">
          <div>
            <h2>Version history</h2>
            <p>PostgreSQL is the active configuration source.</p>
          </div>
        </div>
        <div className="version-list">
          {versions.map((version) => (
            <div className="version-card" key={version.id}>
              <div>
                <strong>Version {version.version}</strong>
                <span>{new Date(version.created_at).toLocaleString()}</span>
              </div>
              <StatusPill value={version.status} />
              <div className="button-row">
                {version.status === "DRAFT" && (
                  <button className="button button-secondary" onClick={() => transition(version, "validate")}>
                    Validate
                  </button>
                )}
                {version.status === "VALIDATED" && (
                  <button className="button button-primary" onClick={() => transition(version, "activate")}>
                    Activate
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
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
        <input type="checkbox" {...register(`strategy.parameters.${name}`)} />
        {label}
      </label>
    );
  }
  return (
    <label>
      {label}
      <input
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
