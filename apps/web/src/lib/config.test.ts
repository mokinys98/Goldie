import { describe, expect, it } from "vitest";
import { botConfigSchema, defaultBotConfig } from "./config";

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
});

