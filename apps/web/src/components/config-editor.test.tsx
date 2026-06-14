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
];

function renderEditor() {
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
      />
    </QueryClientProvider>,
  );
}

describe("ConfigEditor", () => {
  afterEach(() => cleanup());
  beforeEach(() => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/v1/strategies") return strategies as never;
      return {} as never;
    });
  });

  it("renders dynamic parameters and switches defaults", async () => {
    renderEditor();
    const select = await screen.findByLabelText("Strategy");
    await screen.findByRole("option", { name: "ema_rsi" });
    fireEvent.change(select, { target: { value: "ema_rsi" } });
    expect(await screen.findByLabelText("Fast EMA Period")).toHaveValue(9);
    expect(screen.getByDisplayValue("21 M1 candles")).toBeInTheDocument();
  });

  it("submits the selected strategy parameters", async () => {
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Save as new draft" }));
    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        "/api/v1/bots/bot-1/config-versions",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
