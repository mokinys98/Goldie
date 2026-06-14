import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BacktestsPage from "./page";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BacktestsPage />
    </QueryClientProvider>,
  );
}

describe("BacktestsPage", () => {
  beforeEach(() => {
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/api/v1/bots") {
        return [{ id: "bot-1", name: "Gold bot" }] as never;
      }
      if (path === "/api/v1/backtests") {
        return [{
          id: "test-1",
          bot_id: "bot-1",
          status: "SUCCEEDED",
          date_from: "2026-01-01T00:00:00Z",
          date_to: "2026-01-31T00:00:00Z",
          created_at: "2026-02-01T00:00:00Z",
          progress: { processed: 100, total: 100 },
          summary: { total_trades: 12, net_pnl: "42.50" },
        }] as never;
      }
      throw new Error(`Unexpected API path: ${path}`);
    });
  });

  it("renders completed experiment metrics", async () => {
    renderPage();
    expect(await screen.findByText("Gold bot")).toBeInTheDocument();
    expect(screen.getByText("SUCCEEDED")).toBeInTheDocument();
    expect(screen.getByText("42.50")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New backtest" })).toHaveAttribute(
      "href",
      "/backtests/new",
    );
  });
});
