import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OptimizationRun } from "@/lib/types";
import OptimizationDetailPage from "./page";

const useQuery = vi.fn();

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "optimization-1" }) }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: unknown) => useQuery(options),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("@/lib/config", () => ({
  normalizeBotConfig: () => ({
    market: { symbol: "EURUSD" },
    strategy: { name: "ema_rsi", parameters: {} },
    session: { timezone: "UTC" },
    theoretical_trade: {
      stop_loss_points: 20,
      take_profit_points: 30,
      risk_per_trade_pct: 0.25,
    },
    filters: { max_spread_points: 2 },
  }),
}));
vi.mock("@/components/status-pill", () => ({
  StatusPill: ({ value }: { value: string }) => <span>{value}</span>,
}));

const optimization = {
  id: "optimization-1",
  bot_id: "bot-1",
  status: "SUCCEEDED",
  date_from: "2026-01-01T00:00:00Z",
  date_to: "2026-01-02T00:00:00Z",
  n_trials: 12,
  progress: { completed_trials: 12, total_trials: 12 },
  best_candidate: { sampled_parameters: {}, metrics: {} },
  summary: {
    completed_trials: 11,
    failed_trials: 1,
    timings: {
      candle_load_seconds: 0.123456,
      optuna_sampling_seconds: 0.234567,
      backtest_seconds: 1.345678,
      database_commit_seconds: 0.045678,
      total_seconds: 1.789012,
    },
  },
  config_snapshot: {},
  fill_mode: "simulated",
} as unknown as OptimizationRun;

describe("OptimizationDetailPage", () => {
  beforeEach(() => {
    useQuery.mockImplementation(({ queryKey }: { queryKey: string[] }) => (
      queryKey[0] === "optimization"
        ? { data: optimization, isLoading: false, error: null }
        : { data: { items: [], total: 0 }, isLoading: false, error: null }
    ));
  });

  it("renders persisted performance timings", () => {
    render(<OptimizationDetailPage />);

    expect(screen.getByRole("heading", { name: "Performance timings" })).toBeInTheDocument();
    expect(screen.getByText("0.123456 s")).toBeInTheDocument();
    expect(screen.getByText("1.345678 s")).toBeInTheDocument();
    expect(screen.getByText("0.045678 s")).toBeInTheDocument();
    expect(screen.getByText("1.789012 s")).toBeInTheDocument();
  });
});
