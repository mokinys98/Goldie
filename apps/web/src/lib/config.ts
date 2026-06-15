import { z } from "zod";
import type { BotConfig } from "./types";

export const STRATEGY_CONFIG_FORMAT = "goldie-strategy-configuration";
export const STRATEGY_CONFIG_FORMAT_VERSION = 1;

export const botConfigSchema = z.object({
  market: z.object({
    symbol: z.string().min(1).max(32),
    timeframe: z.literal("M1"),
  }),
  strategy: z.object({
    name: z.string().min(1),
    parameters: z.record(
      z.string(),
      z.union([z.string(), z.number(), z.boolean()]),
    ),
  }),
  filters: z.object({
    max_spread_points: z.coerce.number().positive().max(10000),
    stale_after_seconds: z.coerce.number().int().min(2).max(300),
  }),
  session: z.object({
    timezone: z.string().min(1),
    start_time: z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/),
    end_time: z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/),
  }),
  theoretical_trade: z.object({
    stop_loss_points: z.coerce.number().positive().max(100000),
    take_profit_points: z.coerce.number().positive().max(100000),
    risk_per_trade_pct: z.coerce.number().positive().max(100),
    max_trade_duration_minutes: z.coerce.number().int().min(1).max(1440),
    max_open_shadow_positions: z.coerce.number().int().min(1).max(1),
  }),
});

export function serializeStrategyConfig(config: BotConfig): string {
  return JSON.stringify({
    format: STRATEGY_CONFIG_FORMAT,
    version: STRATEGY_CONFIG_FORMAT_VERSION,
    exported_at: new Date().toISOString(),
    configuration: config,
  }, null, 2);
}

export function extractStrategyConfig(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("JSON file must contain an object.");
  }
  const record = value as Record<string, unknown>;
  if (record.format === STRATEGY_CONFIG_FORMAT) {
    if (record.version !== STRATEGY_CONFIG_FORMAT_VERSION) {
      throw new Error(`Unsupported strategy JSON version: ${String(record.version)}.`);
    }
    if (!record.configuration) {
      throw new Error("Strategy JSON does not contain configuration.");
    }
    return record.configuration;
  }
  return record.configuration ?? record.config ?? record;
}

export const defaultBotConfig = {
  market: { symbol: "EURUSD", timeframe: "M1" as const },
  strategy: {
    name: "basic_momentum",
    parameters: {
      lookback_candles: 5,
      min_momentum_points: 50,
    },
  },
  filters: { max_spread_points: 30, stale_after_seconds: 15 },
  session: {
    timezone: "Europe/Vilnius",
    start_time: "10:00:00",
    end_time: "18:00:00",
  },
  theoretical_trade: {
    stop_loss_points: 70,
    take_profit_points: 100,
    risk_per_trade_pct: 0.25,
    max_trade_duration_minutes: 5,
    max_open_shadow_positions: 1,
  },
};

export function normalizeBotConfig(config: Partial<BotConfig> & Record<string, unknown>): BotConfig {
  const strategy = (config.strategy ?? {}) as Record<string, unknown>;
  const parameters = {
    ...((strategy.parameters ?? {}) as Record<string, string | number | boolean>),
  };
  if ("lookback_candles" in strategy) {
    parameters.lookback_candles = strategy.lookback_candles as number;
  }
  if ("min_momentum_points" in strategy) {
    parameters.min_momentum_points = strategy.min_momentum_points as number;
  }
  return {
    ...defaultBotConfig,
    ...config,
    market: { ...defaultBotConfig.market, ...(config.market ?? {}) },
    strategy: {
      name: String(strategy.name ?? defaultBotConfig.strategy.name),
      parameters:
        Object.keys(parameters).length > 0
          ? parameters
          : defaultBotConfig.strategy.parameters,
    },
    filters: { ...defaultBotConfig.filters, ...(config.filters ?? {}) },
    session: { ...defaultBotConfig.session, ...(config.session ?? {}) },
    theoretical_trade: {
      ...defaultBotConfig.theoretical_trade,
      ...(config.theoretical_trade ?? {}),
    },
  } as BotConfig;
}

