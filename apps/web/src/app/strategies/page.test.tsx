import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StrategiesPage from "./page";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

afterEach(cleanup);

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StrategiesPage />
    </QueryClientProvider>,
  );
}

const strategy = {
  id: "strategy-1",
  name: "Gold Momentum",
  description: "Momentum profile",
  status: "ACTIVE",
  config: { strategy: { name: "basic_momentum", parameters: {} } },
  bot_count: 2,
  created_at: "2026-06-20T10:00:00Z",
  updated_at: "2026-06-20T10:00:00Z",
};

describe("StrategiesPage delete", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(api).mockImplementation(async (path, options) => {
      if (path === "/api/v1/strategy-profiles" && !options) return [strategy] as never;
      if (path === "/api/v1/strategy-profiles/strategy-1" && options?.method === "DELETE") {
        return { ...strategy, status: "ARCHIVED" } as never;
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
  });

  it("confirms and deletes a strategy from the list", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    expect(confirm).toHaveBeenCalledWith(
      "Archive Gold Momentum? 2 linked bots and historical results will remain.",
    );
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      "/api/v1/strategy-profiles/strategy-1",
      { method: "DELETE" },
    ));
  });

  it("does not delete when confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    expect(api).not.toHaveBeenCalledWith(
      "/api/v1/strategy-profiles/strategy-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
