import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OptimizationRun } from "@/lib/types";
import OptimizationDetailPage from "./page";

const useQuery = vi.fn();
const api = vi.fn();

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "optimization-1" }) }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: unknown) => useQuery(options),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({ api: (...args: unknown[]) => api(...args) }));
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
  progress: {
    completed_trials: 57,
    total_trials: 57,
    strategy_trials_completed: 12,
    strategy_trials_total: 12,
    validation_trials_completed: 45,
    validation_trials_total: 45,
  },
  best_candidate: {
    sampled_parameters: { fast_ema_period: 8 },
    metrics: {},
    fixed_config_overrides: {
      theoretical_trade: { stop_loss_points: 15, take_profit_points: 37.5 },
    },
  },
  summary: {
    completed_trials: 11,
    failed_trials: 1,
    search_period: {
      date_from: "2026-01-01T00:00:00Z",
      date_to: "2026-01-01T19:12:00Z",
    },
    validation_period: {
      date_from: "2026-01-01T19:12:00Z",
      date_to: "2026-01-02T00:00:00Z",
    },
    timings: {
      candle_load_seconds: 0.123456,
      optuna_sampling_seconds: 0.234567,
      backtest_seconds: 1.345678,
      database_commit_seconds: 0.045678,
      total_seconds: 1.789012,
    },
    research_quality_gates: {
      overall_status: "BLOCK",
      recommendation: "Research gates block promotion.",
      gates: [
        {
          id: "validation_trade_sample",
          status: "BLOCK",
          severity: "HIGH",
          message: "Validation sample is too small for a V1 promotion decision.",
          evidence: { validation_trades: 2, minimum_required: 10 },
        },
        {
          id: "data_quality",
          status: "WARN",
          severity: "MEDIUM",
          message: "Input candles contain gaps or incomplete records.",
          evidence: { detected_m1_gap_count: 1 },
        },
      ],
    },
  },
  config_snapshot: {},
  fill_mode: "simulated",
} as unknown as OptimizationRun;

describe("OptimizationDetailPage", () => {
  beforeEach(() => {
    cleanup();
    api.mockReset();
    useQuery.mockImplementation(({ queryKey }: { queryKey: string[] }) => (
      queryKey[0] === "optimization"
        ? { data: optimization, isLoading: false, error: null }
        : { data: { items: [], total: 0 }, isLoading: false, error: null }
    ));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders persisted performance timings", () => {
    render(<OptimizationDetailPage />);

    expect(screen.getByRole("heading", { name: "Performance timings" })).toBeInTheDocument();
    expect(screen.getByText("0.123456 s")).toBeInTheDocument();
    expect(screen.getByText("1.345678 s")).toBeInTheDocument();
    expect(screen.getByText("0.045678 s")).toBeInTheDocument();
    expect(screen.getByText("1.789012 s")).toBeInTheDocument();
  });

  it("renders phase progress and the winning fixed config", () => {
    render(<OptimizationDetailPage />);

    expect(screen.getAllByText("12 / 12 trials").length).toBeGreaterThan(0);
    expect(screen.getAllByText("45 / 45 trials").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("heading", { name: "Best fixed config" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("37.5").length).toBeGreaterThan(0);
  });

  it("offers JSON export and clipboard actions", () => {
    render(<OptimizationDetailPage />);

    expect(
      screen.getAllByRole("button", { name: "Export Results to JSON" }).at(-1),
    ).toBeEnabled();
    expect(
      screen.getAllByRole("button", { name: "Copy results in clipboard" }).at(-1),
    ).toBeEnabled();
  });

  it("renders research readiness gates", () => {
    render(<OptimizationDetailPage />);

    expect(
      screen.getAllByRole("heading", { name: "Research readiness" }).at(-1),
    ).toBeInTheDocument();
    expect(screen.getByText("Research gates block promotion.")).toBeInTheDocument();
    expect(screen.getAllByText("BLOCK").length).toBeGreaterThan(0);
    expect(screen.getByText("validation trade sample")).toBeInTheDocument();
    expect(screen.getByText("Validation sample is too small for a V1 promotion decision.")).toBeInTheDocument();
  });

  it("requires an override confirmation before applying a blocked candidate", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<OptimizationDetailPage />);

    fireEvent.click(
      screen.getAllByRole("button", { name: "Apply best as new config" }).at(-1)!,
    );

    expect(confirm).toHaveBeenCalledWith(
      "Research gates block this candidate. Apply it anyway as a new active config?",
    );
    expect(api).not.toHaveBeenCalled();
  });
});
