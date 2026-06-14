import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CollectorPage from "./page";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  openCollectorStream: vi.fn(() => () => undefined),
}));

const overview = {
  instance: {
    id: "instance-1",
    name: "railway-collector",
    status: "ONLINE",
    reported_status: "ONLINE",
    last_heartbeat_at: "2026-06-14T12:00:00Z",
    applied_config_version: 2,
    details: {},
  },
  counts: {
    online: 1,
    paused: 0,
    error: 0,
    market_closed: 0,
    ticks_24h: 120,
    candles_24h: 60,
  },
  feeds: [{
    id: "feed-1",
    provider: "oanda",
    environment: "practice",
    canonical_symbol: "EURUSD",
    provider_symbol: "EUR_USD",
    status: "ONLINE",
    last_heartbeat_at: "2026-06-14T12:00:00Z",
    latest_tick: {
      observed_at: "2026-06-14T12:00:00Z",
      bid: "1.08000",
      ask: "1.08020",
      spread: "0.00020",
    },
    latest_candle_at: "2026-06-14T11:59:00Z",
    data_lag_seconds: 2,
    bot_count: 1,
  }],
  recent_commands: [],
};

const settings = {
  configuration: {
    id: "config-1",
    version: 2,
    quote_interval_seconds: 5,
    candle_poll_seconds: 15,
    heartbeat_seconds: 10,
    backfill_days: 30,
    backfill_batch_size: 250,
    configuration_retry_seconds: 900,
    updated_at: "2026-06-14T12:00:00Z",
  },
  instruments: [],
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CollectorPage />
    </QueryClientProvider>,
  );
}

describe("CollectorPage", () => {
  beforeEach(() => {
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (options?.method === "POST") {
        return {
          id: "command-1",
          command: "PAUSE",
          status: "PENDING",
        } as never;
      }
      if (path === "/api/v1/collector/overview") return overview as never;
      if (path === "/api/v1/collector/settings") return settings as never;
      throw new Error(`Unexpected API path: ${path}`);
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("renders worker metrics and feed diagnostics", async () => {
    renderPage();
    expect(await screen.findByText("EUR_USD")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("0.00020")).toBeInTheDocument();
    expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0);
  });

  it("creates a confirmed global pause command", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Pause all" }));
    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        "/api/v1/collector/commands",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
