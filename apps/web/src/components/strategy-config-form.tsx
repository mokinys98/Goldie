"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { api } from "@/lib/api";
import { botConfigSchema, defaultBotConfig, normalizeBotConfig } from "@/lib/config";
import type {
  BotConfig,
  ConfigurationSchema,
  StrategyMetadata,
  StrategyParameterMetadata,
} from "@/lib/types";
import { FieldHelp } from "./field-help";

export function StrategyConfigForm({
  initialConfig = defaultBotConfig,
  submitLabel,
  onSubmit,
}: {
  initialConfig?: BotConfig;
  submitLabel: string;
  onSubmit: (config: BotConfig) => Promise<void>;
}) {
  const initial = normalizeBotConfig(initialConfig);
  const [strategyName, setStrategyName] = useState(initial.strategy.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const strategies = useQuery({
    queryKey: ["strategies"],
    queryFn: () => api<StrategyMetadata[]>("/api/v1/strategies"),
  });
  const schema = useQuery({
    queryKey: ["strategy-configuration-schema"],
    queryFn: () =>
      api<ConfigurationSchema>("/api/v1/strategies/configuration-schema"),
  });
  const form = useForm<BotConfig>({
    resolver: zodResolver(botConfigSchema),
    defaultValues: initial,
  });
  const selected = strategies.data?.find((item) => item.name === strategyName);

  useEffect(() => {
    form.reset(normalizeBotConfig(initialConfig));
    setStrategyName(initialConfig.strategy.name);
  }, [form, initialConfig]);

  async function submit(values: BotConfig) {
    setBusy(true);
    setError("");
    try {
      await onSubmit(values);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save strategy");
    } finally {
      setBusy(false);
    }
  }

  function selectStrategy(name: string) {
    const metadata = strategies.data?.find((item) => item.name === name);
    setStrategyName(name);
    form.setValue("strategy.name", name);
    form.setValue("strategy.parameters", metadata?.defaults ?? {});
  }

  const meta = (section: string, field: string) => schema.data?.[section]?.[field];
  return (
    <form className="panel config-form" onSubmit={form.handleSubmit(submit)}>
      <fieldset>
        <legend>Algorithm</legend>
        <label>
          <FieldHelp label="Strategy algorithm" metadata={meta("strategy", "name")} />
          <select
            value={strategyName}
            onChange={(event) => selectStrategy(event.target.value)}
          >
            {(strategies.data ?? []).map((strategy) => (
              <option key={strategy.name} value={strategy.name}>{strategy.name}</option>
            ))}
          </select>
        </label>
        <label>
          <FieldHelp label="Required history" metadata={{ description: "Minimum completed candle history required before this algorithm can evaluate a signal.", unit: "candles", impact: "More required history delays evaluation after startup." }} />
          <input value={selected ? `${selected.required_candles} M1 candles` : "--"} disabled />
        </label>
        {selected && <p className="fieldset-description">{selected.description}</p>}
        {selected &&
          Object.entries(selected.parameters).map(([name, metadata]) => (
            <ParameterField
              key={name}
              name={name}
              metadata={metadata}
              register={form.register}
            />
          ))}
      </fieldset>
      <fieldset>
        <legend>Filters and session</legend>
        <NumberField label="Maximum spread points" path="filters.max_spread_points" metadata={meta("filters", "max_spread_points")} register={form.register} />
        <NumberField label="Stale after seconds" path="filters.stale_after_seconds" metadata={meta("filters", "stale_after_seconds")} register={form.register} integer />
        <TextField label="Timezone" path="session.timezone" metadata={meta("session", "timezone")} register={form.register} />
        <TimeField label="Start time" path="session.start_time" metadata={meta("session", "start_time")} register={form.register} />
        <TimeField label="End time" path="session.end_time" metadata={meta("session", "end_time")} register={form.register} />
      </fieldset>
      <fieldset>
        <legend>Trade and risk model</legend>
        <NumberField label="Stop loss points" path="theoretical_trade.stop_loss_points" metadata={meta("theoretical_trade", "stop_loss_points")} register={form.register} />
        <NumberField label="Take profit points" path="theoretical_trade.take_profit_points" metadata={meta("theoretical_trade", "take_profit_points")} register={form.register} />
        <NumberField label="Risk per trade %" path="theoretical_trade.risk_per_trade_pct" metadata={meta("theoretical_trade", "risk_per_trade_pct")} register={form.register} />
        <NumberField label="Maximum duration minutes" path="theoretical_trade.max_trade_duration_minutes" metadata={meta("theoretical_trade", "max_trade_duration_minutes")} register={form.register} integer />
        <NumberField label="Maximum open shadow positions" path="theoretical_trade.max_open_shadow_positions" metadata={meta("theoretical_trade", "max_open_shadow_positions")} register={form.register} integer />
      </fieldset>
      {error && <div className="error-box">{error}</div>}
      {Object.keys(form.formState.errors).length > 0 && (
        <div className="error-box">Strategy contains invalid values.</div>
      )}
      <button className="button button-primary" disabled={busy}>
        {busy ? "Saving..." : submitLabel}
      </button>
    </form>
  );
}

type Register = ReturnType<typeof useForm<BotConfig>>["register"];

function ParameterField({ name, metadata, register }: { name: string; metadata: StrategyParameterMetadata; register: Register }) {
  const label = metadata.title ?? name.replaceAll("_", " ");
  if (metadata.type === "boolean") {
    return (
      <label className="checkbox-row">
        <input type="checkbox" {...register(`strategy.parameters.${name}`)} />
        <FieldHelp label={label} metadata={metadata} />
      </label>
    );
  }
  return <NumberField label={label} path={`strategy.parameters.${name}`} metadata={metadata} register={register} integer={metadata.type === "integer"} />;
}

function NumberField({ label, path, metadata, register, integer = false }: { label: string; path: Parameters<Register>[0]; metadata?: StrategyParameterMetadata; register: Register; integer?: boolean }) {
  return <label><FieldHelp label={label} metadata={metadata} /><input type="number" step={integer ? 1 : "any"} min={metadata?.minimum ?? metadata?.exclusiveMinimum} max={metadata?.maximum} {...register(path, { valueAsNumber: true })} /></label>;
}
function TextField({ label, path, metadata, register }: { label: string; path: Parameters<Register>[0]; metadata?: StrategyParameterMetadata; register: Register }) {
  return <label><FieldHelp label={label} metadata={metadata} /><input {...register(path)} /></label>;
}
function TimeField({ label, path, metadata, register }: { label: string; path: Parameters<Register>[0]; metadata?: StrategyParameterMetadata; register: Register }) {
  return <label><FieldHelp label={label} metadata={metadata} /><input type="time" step="1" {...register(path)} /></label>;
}
