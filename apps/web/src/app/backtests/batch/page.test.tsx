import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BatchBacktestPage from "./page";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

afterEach(cleanup);

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BatchBacktestPage />
    </QueryClientProvider>,
  );
}

describe("BatchBacktestPage filters", () => {
  beforeEach(() => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/v1/bots") {
        return [
          {
            id: "bot-1",
            name: "London Gold Momentum",
            mode: "SHADOW",
            state: "ACTIVE",
            active_config_version_id: "config-1",
            market_feed_id: "feed-1",
            strategy_profile_id: "strategy-1",
          },
          {
            id: "bot-2",
            name: "New York Euro Reversion",
            mode: "PAPER",
            state: "PAUSED",
            active_config_version_id: "config-2",
            market_feed_id: "feed-2",
            strategy_profile_id: "strategy-2",
          },
          {
            id: "bot-3",
            name: "Gold Standalone",
            mode: "PAPER",
            state: "ACTIVE",
            active_config_version_id: "config-3",
            market_feed_id: "feed-1",
            strategy_profile_id: null,
          },
        ] as never;
      }
      if (path === "/api/v1/market-feeds") {
        return [
          { id: "feed-1", canonical_symbol: "XAUUSD" },
          { id: "feed-2", canonical_symbol: "EURUSD" },
        ] as never;
      }
      if (path === "/api/v1/strategy-profiles") {
        return [
          { id: "strategy-1", name: "Momentum" },
          { id: "strategy-2", name: "Mean reversion" },
        ] as never;
      }
      throw new Error(`Unexpected API path: ${path}`);
    });
  });

  it("searches by any case-insensitive part of the bot name", async () => {
    renderPage();
    expect(await screen.findByText("London Gold Momentum")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search by bot name"), {
      target: { value: "GOLD M" },
    });

    expect(screen.getByText("London Gold Momentum")).toBeInTheDocument();
    expect(screen.queryByText("New York Euro Reversion")).not.toBeInTheDocument();
    expect(screen.queryByText("Gold Standalone")).not.toBeInTheDocument();
    expect(screen.getByTestId("bot-filter-count")).toHaveTextContent("Showing 1 of 3 bots");
  });

  it("combines currency, strategy, mode, and state filters", async () => {
    renderPage();
    expect(await screen.findByText("London Gold Momentum")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "XAUUSD" } });
    fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "standalone" } });
    fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "PAPER" } });
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "ACTIVE" } });

    expect(screen.getByText("Gold Standalone")).toBeInTheDocument();
    expect(screen.queryByText("London Gold Momentum")).not.toBeInTheDocument();
    expect(screen.queryByText("New York Euro Reversion")).not.toBeInTheDocument();
  });
});
