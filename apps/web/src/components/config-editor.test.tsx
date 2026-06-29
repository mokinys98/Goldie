import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfigEditor } from "./config-editor";
import { api } from "@/lib/api";
import { defaultBotConfig } from "@/lib/config";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const strategies = [
  {
    name: "basic_momentum",
    description: "Momentum",
    required_candles: 6,
    defaults: { lookback_candles: 5, min_momentum_points: 50 },
    parameters: {
      lookback_candles: { title: "Lookback Candles", type: "integer", minimum: 2 },
      min_momentum_points: { title: "Min Momentum Points", type: "number" },
    },
  },
  {
    name: "ema_rsi",
    description: "EMA and RSI",
    required_candles: 21,
    defaults: {
      fast_ema_period: 9,
      slow_ema_period: 21,
      rsi_period: 14,
      buy_rsi_max: 70,
      sell_rsi_min: 30,
      min_trend_points: 0,
      require_crossover: false,
    },
    parameters: {
      fast_ema_period: { title: "Fast EMA Period", type: "integer", minimum: 2 },
      require_crossover: { title: "Require Crossover", type: "boolean" },
    },
  },
  {
    name: "fvg_ma_volume_profile",
    description: "FVG strategy",
    required_candles: 50,
    defaults: { trade_direction: "BOTH" },
    parameters: {
      trade_direction: {
        title: "Trade Direction",
        type: "string",
        enum: ["BOTH", "BUY_ONLY", "SELL_ONLY"],
      },
    },
  },
];

function renderEditor(strategyProfileId: string | null = "strategy-1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConfigEditor
        botId="bot-1"
        versions={[{
          id: "config-1",
          bot_id: "bot-1",
          version: 1,
          status: "DRAFT",
          config: defaultBotConfig,
          validation_errors: null,
          created_at: "2026-01-01T00:00:00Z",
          activated_at: null,
        }]}
        onChanged={() => undefined}
        strategyProfileId={strategyProfileId}
      />
    </QueryClientProvider>,
  );
}

describe("ConfigEditor", () => {
  afterEach(() => cleanup());
  beforeEach(() => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/v1/strategies") return strategies as never;
      if (path === "/api/v1/strategy-profiles/strategy-1") {
        return { config: defaultBotConfig } as never;
      }
      return {} as never;
    });
  });

  it("renders inherited strategy fields", async () => {
    renderEditor();
    expect(await screen.findByRole("heading", { name: "Strategy inheritance" })).toBeInTheDocument();
    expect(screen.getAllByText(/Inherited:/).length).toBeGreaterThan(0);
  });

  it("submits enabled overrides", async () => {
    renderEditor();
    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save and activate overrides" }));
    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        "/api/v1/bots/bot-1/overrides",
        expect.objectContaining({ method: "PUT" }),
      );
    });
  });

  it("does not render the legacy editor for an unlinked bot", () => {
    renderEditor(null);
    expect(screen.getByRole("heading", { name: "Global strategy required" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Configuration editor" })).not.toBeInTheDocument();
  });
});
