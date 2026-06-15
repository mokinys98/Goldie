import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BulkBotsCreationPage from "./page";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

afterEach(cleanup);

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BulkBotsCreationPage />
    </QueryClientProvider>,
  );
}

describe("BulkBotsCreationPage", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "request-id") });
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === "/api/v1/strategy-profiles") {
        return [
          {
            id: "strategy-1",
            name: "Momentum",
            config: { strategy: { name: "basic_momentum" } },
          },
          {
            id: "strategy-2",
            name: "Mean Reversion",
            config: { strategy: { name: "mean_reversion" } },
          },
        ] as never;
      }
      if (path === "/api/v1/market-feeds") {
        return [
          { id: "feed-1", canonical_symbol: "EURUSD", provider: "oanda", environment: "practice", status: "ONLINE" },
          { id: "feed-2", canonical_symbol: "XAUUSD", provider: "oanda", environment: "practice", status: "ONLINE" },
        ] as never;
      }
      if (path === "/api/v1/bots/bulk") {
        const body = JSON.parse(String(options?.body)) as {
          strategy_profile_id: string;
          market_feed_ids: string[];
        };
        return body.market_feed_ids.map((feedId) => ({
          market_feed_id: feedId,
          name: `${feedId}-${body.strategy_profile_id}`,
          status: "CREATED",
          bot: { id: `${feedId}-${body.strategy_profile_id}` },
          error: null,
        })) as never;
      }
      throw new Error(`Unexpected API path: ${path}`);
    });
  });

  it("creates every selected strategy and pair combination", async () => {
    renderPage();
    expect(await screen.findByText("Momentum")).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Select all")[0]);
    fireEvent.click(screen.getAllByText("Select all")[1]);

    expect(screen.getByText("Create 4 bot(s)")).toBeEnabled();
    expect(screen.getByText("EURUSD-momentum-shadow")).toBeInTheDocument();
    expect(screen.getByText("XAUUSD-mean-reversion-shadow")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Create 4 bot(s)"));

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        "/api/v1/bots/bulk",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(vi.mocked(api).mock.calls.filter(([path]) => path === "/api/v1/bots/bulk")).toHaveLength(2);
    expect(await screen.findByText("4 created, 0 already existed, 0 failed.")).toBeInTheDocument();
  });
});
