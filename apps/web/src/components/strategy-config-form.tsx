"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { api } from "@/lib/api";
import {
  botConfigSchema,
  defaultBotConfig,
  extractStrategyConfig,
  normalizeBotConfig,
  serializeStrategyConfig,
} from "@/lib/config";
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
  onImportedFileName,
}: {
  initialConfig?: BotConfig;
  submitLabel: string;
  onSubmit: (config: BotConfig) => Promise<void>;
  onImportedFileName?: (name: string) => void;
}) {
  const initial = normalizeBotConfig(initialConfig);
  const [strategyName, setStrategyName] = useState(initial.strategy.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
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

  async function importConfiguration(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const parsed = JSON.parse(await readTextFile(file)) as unknown;
      const configuration = extractStrategyConfig(parsed);
      const validated = await api<BotConfig>("/api/v1/strategies/validate-configuration", {
        method: "POST",
        body: JSON.stringify(configuration),
      });
      const normalized = normalizeBotConfig(validated);
      form.reset(normalized);
      setStrategyName(normalized.strategy.name);
      onImportedFileName?.(strategyNameFromFile(file.name));
      setNotice(`Imported ${file.name}. Review the settings before saving.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not import strategy JSON");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function exportConfiguration() {
    setError("");
    setNotice("");
    const result = botConfigSchema.safeParse(form.getValues());
    if (!result.success) {
      setError("Fix invalid values before exporting the strategy.");
      return;
    }
    const blob = new Blob([serializeStrategyConfig(result.data)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `strategy-${result.data.strategy.name}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const meta = (section: string, field: string) => schema.data?.[section]?.[field];
  return (
    <form className="panel config-form" onSubmit={form.handleSubmit(submit)}>
      <div className="config-transfer">
        <div>
          <strong>JSON configuration</strong>
          <span>Import or export every strategy, filter, session, market and risk setting.</span>
        </div>
        <div className="button-row">
          <input
            ref={fileInput}
            className="visually-hidden"
            type="file"
            accept="application/json,.json"
            aria-label="Strategy JSON file"
            onChange={(event) => void importConfiguration(event.target.files?.[0])}
          />
          <button
            className="button button-secondary"
            type="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            Import JSON
          </button>
          <button
            className="button button-secondary"
            type="button"
            disabled={busy}
            onClick={exportConfiguration}
          >
            Export JSON
          </button>
        </div>
      </div>
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
      {notice && <div className="success-box">{notice}</div>}
      {Object.keys(form.formState.errors).length > 0 && (
        <div className="error-box">Strategy contains invalid values.</div>
      )}
      <button className="button button-primary" disabled={busy}>
        {busy ? "Saving..." : submitLabel}
      </button>
    </form>
  );
}

export function strategyNameFromFile(fileName: string): string {
  return fileName.replace(/\.json$/i, "");
}

type Register = ReturnType<typeof useForm<BotConfig>>["register"];

function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsText(file);
  });
}

function ParameterField({ name, metadata, register }: { name: string; metadata: StrategyParameterMetadata; register: Register }) {
  const label = metadata.title ?? name.replaceAll("_", " ");
  if (metadata.enum?.length) {
    return <SelectField label={label} path={`strategy.parameters.${name}`} metadata={metadata} register={register} />;
  }
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
function SelectField({ label, path, metadata, register }: { label: string; path: Parameters<Register>[0]; metadata: StrategyParameterMetadata; register: Register }) {
  return (
    <label>
      <FieldHelp label={label} metadata={metadata} />
      <select aria-label={label} {...register(path)}>
        {metadata.enum?.map((value) => (
          <option key={String(value)} value={String(value)}>
            {String(value)}
          </option>
        ))}
      </select>
    </label>
  );
}
function TimeField({ label, path, metadata, register }: { label: string; path: Parameters<Register>[0]; metadata?: StrategyParameterMetadata; register: Register }) {
  return <label><FieldHelp label={label} metadata={metadata} /><input type="time" step="1" {...register(path)} /></label>;
}
