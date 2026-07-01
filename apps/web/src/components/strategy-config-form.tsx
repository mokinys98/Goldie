"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { api } from "@/lib/api";
import {
  exclusiveZeroInputValue,
  exclusiveZeroStoredValue,
} from "@/lib/display";
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
  OptimizationRanges,
  StrategyMetadata,
  StrategyParameterMetadata,
  TradeRanges,
} from "@/lib/types";
import { FieldHelp } from "./field-help";

const EMPTY_OPTIMIZATION_RANGES: OptimizationRanges = {};
const EMPTY_TRADE_RANGES: TradeRanges = {};

export function StrategyConfigForm({
  initialConfig = defaultBotConfig,
  initialOptimizationRanges = EMPTY_OPTIMIZATION_RANGES,
  initialTradeRanges = EMPTY_TRADE_RANGES,
  submitLabel,
  onSubmit,
  onImportedFileName,
}: {
  initialConfig?: BotConfig;
  initialOptimizationRanges?: OptimizationRanges;
  initialTradeRanges?: TradeRanges;
  submitLabel: string;
  onSubmit: (
    config: BotConfig,
    optimizationRanges: OptimizationRanges,
    tradeRanges: TradeRanges,
  ) => Promise<void>;
  onImportedFileName?: (name: string) => void;
}) {
  const initial = normalizeBotConfig(initialConfig);
  const [strategyName, setStrategyName] = useState(initial.strategy.name);
  const [optimizationRanges, setOptimizationRanges] = useState<OptimizationRanges>(
    initialOptimizationRanges,
  );
  const [tradeRanges, setTradeRanges] = useState<TradeRanges>(initialTradeRanges);
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
    setOptimizationRanges(initialOptimizationRanges);
    setTradeRanges(initialTradeRanges);
  }, [form, initialConfig, initialOptimizationRanges, initialTradeRanges]);

  async function submit(values: BotConfig) {
    setBusy(true);
    setError("");
    try {
      await onSubmit(
        values,
        resolvedOptimizationRanges(selected, optimizationRanges),
        tradeRanges,
      );
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
    setOptimizationRanges(defaultOptimizationRanges(metadata));
    setTradeRanges({});
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
      const importedMetadata = strategies.data?.find(
        (item) => item.name === normalized.strategy.name,
      );
      setOptimizationRanges(defaultOptimizationRanges(importedMetadata));
      setTradeRanges({});
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
      <fieldset className="algorithm-fieldset">
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
              range={optimizationRanges[name]}
              onRangeChange={(range) => setOptimizationRanges((current) => ({
                ...current,
                [name]: range,
              }))}
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
      <fieldset>
        <legend>Trade exit optimization</legend>
        <p className="fieldset-description">
          Enabled exits are sampled with Optuna. Disabled exits keep their configured value.
        </p>
        <TradeRangeField
          label="Stop loss points"
          range={tradeRanges.stop_loss_points}
          fixedValue={form.watch("theoretical_trade.stop_loss_points")}
          onChange={(range) => setTradeRanges((current) => updateTradeRange(
            current,
            "stop_loss_points",
            range,
          ))}
        />
        <TradeRangeField
          label="Take profit points"
          range={tradeRanges.take_profit_points}
          fixedValue={form.watch("theoretical_trade.take_profit_points")}
          onChange={(range) => setTradeRanges((current) => updateTradeRange(
            current,
            "take_profit_points",
            range,
          ))}
        />
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

function ParameterField({ name, metadata, register, range, onRangeChange }: { name: string; metadata: StrategyParameterMetadata; register: Register; range?: { minimum: number; maximum: number }; onRangeChange: (range: { minimum: number; maximum: number }) => void }) {
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
  if (!hasOptimizationRange(metadata)) {
    return <NumberField label={label} path={`strategy.parameters.${name}`} metadata={metadata} register={register} integer={metadata.type === "integer"} />;
  }
  const defaults = defaultParameterRange(metadata);
  return (
    <div className="parameter-range-row">
      <NumberField label={label} path={`strategy.parameters.${name}`} metadata={metadata} register={register} integer={metadata.type === "integer"} />
      <label>
        {label} Min
        <input
          aria-label={`${label} Min`}
          type="number"
          step={metadata.type === "integer" ? 1 : "any"}
          value={exclusiveZeroInputValue(range?.minimum ?? defaults.minimum)}
          onChange={(event) => onRangeChange({
            minimum: exclusiveZeroStoredValue(
              Number(event.target.value),
              metadata.exclusiveMinimum,
            ),
            maximum: range?.maximum ?? defaults.maximum,
          })}
        />
      </label>
      <label>
        {label} Max
        <input
          aria-label={`${label} Max`}
          type="number"
          step={metadata.type === "integer" ? 1 : "any"}
          value={exclusiveZeroInputValue(range?.maximum ?? defaults.maximum)}
          onChange={(event) => onRangeChange({
            minimum: range?.minimum ?? defaults.minimum,
            maximum: Number(event.target.value),
          })}
        />
      </label>
    </div>
  );
}

function defaultParameterRange(metadata: StrategyParameterMetadata) {
  const exclusiveMinimum = metadata.exclusiveMinimum;
  return {
    minimum: Number(
      metadata.optimization_minimum
      ?? metadata.minimum
      ?? (exclusiveMinimum === undefined
        ? 0
        : exclusiveMinimum + (metadata.type === "integer" ? 1 : 1e-9)),
    ),
    maximum: Number(metadata.optimization_maximum ?? metadata.maximum ?? 0),
  };
}

function hasOptimizationRange(metadata: StrategyParameterMetadata): boolean {
  const hasMinimum = metadata.optimization_minimum !== undefined
    || metadata.minimum !== undefined
    || metadata.exclusiveMinimum !== undefined;
  const hasMaximum = metadata.optimization_maximum !== undefined
    || metadata.maximum !== undefined;
  return (metadata.type === "integer" || metadata.type === "number")
    && hasMinimum
    && hasMaximum;
}

function defaultOptimizationRanges(metadata?: StrategyMetadata): OptimizationRanges {
  if (!metadata) return {};
  return Object.fromEntries(
    Object.entries(metadata.parameters)
      .filter(([, field]) => hasOptimizationRange(field))
      .map(([name, field]) => [name, defaultParameterRange(field)]),
  );
}

function resolvedOptimizationRanges(
  metadata: StrategyMetadata | undefined,
  ranges: OptimizationRanges,
): OptimizationRanges {
  return { ...defaultOptimizationRanges(metadata), ...ranges };
}

function updateTradeRange(
  ranges: TradeRanges,
  name: keyof TradeRanges,
  range: TradeRanges[typeof name],
): TradeRanges {
  if (range) return { ...ranges, [name]: range };
  const next = { ...ranges };
  delete next[name];
  return next;
}

function TradeRangeField({
  label,
  range,
  fixedValue,
  onChange,
}: {
  label: string;
  range?: { minimum: number; maximum: number; step: number };
  fixedValue: number;
  onChange: (range: { minimum: number; maximum: number; step: number } | undefined) => void;
}) {
  const enabled = Boolean(range);
  const current = range ?? { minimum: Number(fixedValue), maximum: Number(fixedValue), step: 1 };
  return (
    <div className="parameter-range-row">
      <label className="checkbox-row">
        <input
          aria-label={`Optimize ${label}`}
          type="checkbox"
          checked={enabled}
          onChange={(event) => onChange(event.target.checked ? current : undefined)}
        />
        Optimize {label}
      </label>
      <label>
        {label} Min
        <input
          aria-label={`${label} Min`}
          type="number"
          min="0"
          step="any"
          disabled={!enabled}
          value={current.minimum}
          onChange={(event) => onChange({ ...current, minimum: Number(event.target.value) })}
        />
      </label>
      <label>
        {label} Max
        <input
          aria-label={`${label} Max`}
          type="number"
          min="0"
          step="any"
          disabled={!enabled}
          value={current.maximum}
          onChange={(event) => onChange({ ...current, maximum: Number(event.target.value) })}
        />
      </label>
      <label>
        {label} Step
        <input
          aria-label={`${label} Step`}
          type="number"
          min="0"
          step="any"
          disabled={!enabled}
          value={current.step}
          onChange={(event) => onChange({ ...current, step: Number(event.target.value) })}
        />
      </label>
    </div>
  );
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
