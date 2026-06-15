import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { defaultBotConfig, serializeStrategyConfig } from "@/lib/config";
import { StrategyConfigForm } from "./strategy-config-form";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const strategies = [
  {
    name: "basic_momentum",
    description: "Momentum",
    required_candles: 6,
    defaults: { lookback_candles: 5, min_momentum_points: 50 },
    parameters: {
      lookback_candles: { title: "Lookback", type: "integer", minimum: 2 },
      min_momentum_points: { title: "Minimum momentum", type: "number" },
    },
  },
  {
    name: "future_strategy",
    description: "A strategy added after the UI was built.",
    required_candles: 12,
    defaults: { window: 12, enabled: true },
    parameters: {
      window: { title: "Window", type: "integer", minimum: 2 },
      enabled: { title: "Enabled", type: "boolean" },
    },
  },
];

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StrategyConfigForm submitLabel="Save" onSubmit={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("StrategyConfigForm JSON transfer", () => {
  afterEach(() => cleanup());
  beforeEach(() => {
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === "/api/v1/strategies") return strategies as never;
      if (path === "/api/v1/strategies/configuration-schema") return {} as never;
      if (path === "/api/v1/strategies/validate-configuration") {
        return JSON.parse(String(options?.body)) as never;
      }
      return {} as never;
    });
  });

  it("imports a dynamically registered strategy and all configuration sections", async () => {
    const { container } = renderForm();
    const configuration = {
      ...defaultBotConfig,
      strategy: {
        name: "future_strategy",
        parameters: { window: 24, enabled: false },
      },
      filters: { max_spread_points: 44, stale_after_seconds: 22 },
    };
    const file = new File(
      [serializeStrategyConfig(configuration)],
      "future-strategy.json",
      { type: "application/json" },
    );

    fireEvent.change(screen.getByLabelText("Strategy JSON file"), {
      target: { files: [file] },
    });

    expect(await screen.findByDisplayValue("future_strategy")).toBeInTheDocument();
    expect(container.querySelector('[name="strategy.parameters.window"]')).toHaveValue(24);
    expect(container.querySelector('[name="filters.max_spread_points"]')).toHaveValue(44);
    expect(screen.getByText(/Imported future-strategy.json/)).toBeInTheDocument();
    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        "/api/v1/strategies/validate-configuration",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("shows server validation errors without replacing the form", async () => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/v1/strategies") return strategies as never;
      if (path === "/api/v1/strategies/configuration-schema") return {} as never;
      throw new Error("Unknown strategy: missing");
    });
    renderForm();
    const file = new File(
      [JSON.stringify({
        ...defaultBotConfig,
        strategy: { name: "missing", parameters: {} },
      })],
      "invalid.json",
      { type: "application/json" },
    );

    fireEvent.change(screen.getByLabelText("Strategy JSON file"), {
      target: { files: [file] },
    });

    expect(await screen.findByText("Unknown strategy: missing")).toBeInTheDocument();
    expect(screen.getByDisplayValue("basic_momentum")).toBeInTheDocument();
  });
});
