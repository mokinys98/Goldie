import { describe, expect, it } from "vitest";
import {
  botConfigSchema,
  defaultBotConfig,
  extractStrategyConfig,
  normalizeBotConfig,
  serializeStrategyConfig,
} from "./config";

describe("botConfigSchema", () => {
  it("accepts the shared default configuration", () => {
    expect(botConfigSchema.safeParse(defaultBotConfig).success).toBe(true);
  });

  it("rejects unsupported timeframe", () => {
    const invalid = {
      ...defaultBotConfig,
      market: { ...defaultBotConfig.market, timeframe: "M5" },
    };
    expect(botConfigSchema.safeParse(invalid).success).toBe(false);
  });

  it("rejects unsafe negative risk distances", () => {
    const invalid = {
      ...defaultBotConfig,
      theoretical_trade: {
        ...defaultBotConfig.theoretical_trade,
        stop_loss_points: -1,
      },
    };
    expect(botConfigSchema.safeParse(invalid).success).toBe(false);
  });

  it("rejects invalid shadow risk and duration", () => {
    const invalid = {
      ...defaultBotConfig,
      theoretical_trade: {
        ...defaultBotConfig.theoretical_trade,
        risk_per_trade_pct: 0,
        max_trade_duration_minutes: 0,
      },
    };
    expect(botConfigSchema.safeParse(invalid).success).toBe(false);
  });

  it("normalizes legacy momentum parameters", () => {
    const normalized = normalizeBotConfig({
      strategy: {
        name: "basic_momentum",
        lookback_candles: 8,
        min_momentum_points: 12,
      },
    } as never);
    expect(normalized.strategy.parameters).toEqual({
      lookback_candles: 8,
      min_momentum_points: 12,
    });
  });

  it("round-trips the versioned strategy JSON format", () => {
    const exported = JSON.parse(serializeStrategyConfig(defaultBotConfig));
    expect(extractStrategyConfig(exported)).toEqual(defaultBotConfig);
  });

  it("accepts raw configurations for backwards-compatible imports", () => {
    expect(extractStrategyConfig(defaultBotConfig)).toEqual(defaultBotConfig);
  });

  it("rejects unsupported strategy JSON versions", () => {
    expect(() => extractStrategyConfig({
      format: "goldie-strategy-configuration",
      version: 2,
      configuration: defaultBotConfig,
    })).toThrow("Unsupported strategy JSON version");
  });
});

