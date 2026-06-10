import { z } from "zod";

export const botConfigSchema = z.object({
  market: z.object({
    symbol: z.string().min(1).max(32),
    timeframe: z.literal("M1"),
  }),
  strategy: z.object({
    name: z.literal("basic_momentum"),
    lookback_candles: z.coerce.number().int().min(2).max(100),
    min_momentum_points: z.coerce.number().positive().max(10000),
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
  }),
});

export const defaultBotConfig = {
  market: { symbol: "XAUUSD", timeframe: "M1" as const },
  strategy: {
    name: "basic_momentum" as const,
    lookback_candles: 5,
    min_momentum_points: 50,
  },
  filters: { max_spread_points: 30, stale_after_seconds: 15 },
  session: {
    timezone: "Europe/Vilnius",
    start_time: "10:00:00",
    end_time: "18:00:00",
  },
  theoretical_trade: { stop_loss_points: 70, take_profit_points: 100 },
};

