import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
          message: "Input candles contain unexpected M1 gaps or incomplete records.",
          evidence: { detected_m1_gap_count: 1, detected_m1_missing_minutes: 2 },
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

  it("groups JSON export and clipboard actions under the download menu", () => {
    render(<OptimizationDetailPage />);

    fireEvent.click(screen.getByLabelText("Download optimization data"));

    expect(
      screen.getAllByRole("button", { name: "Results JSON" }).at(0),
    ).toBeEnabled();
    expect(
      screen.getAllByRole("button", { name: "LLM context JSON" }).at(0),
    ).toBeEnabled();
    expect(
      screen.getAllByRole("button", { name: "Results JSON" }).at(1),
    ).toBeEnabled();
    expect(
      screen.getAllByRole("button", { name: "LLM context JSON" }).at(1),
    ).toBeEnabled();
  });

  it("copies results with the fallback clipboard path when Clipboard API is unavailable", async () => {
    const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    const execCommandDescriptor = Object.getOwnPropertyDescriptor(document, "execCommand");
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    Object.defineProperty(document, "execCommand", { configurable: true, value: vi.fn(() => true) });
    const execCommand = vi.spyOn(document, "execCommand").mockReturnValue(true);
    api.mockResolvedValueOnce({ trials: [{ id: "trial-1" }] });
    render(<OptimizationDetailPage />);

    fireEvent.click(screen.getByLabelText("Download optimization data"));
    fireEvent.click(screen.getAllByRole("button", { name: "Results JSON" }).at(1)!);

    await waitFor(() => {
      expect(screen.getByText("Copied 1 trials to clipboard.")).toBeInTheDocument();
    });
    expect(execCommand).toHaveBeenCalledWith("copy");

    if (clipboardDescriptor) {
      Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
    }
    if (execCommandDescriptor) {
      Object.defineProperty(document, "execCommand", execCommandDescriptor);
    } else {
      Reflect.deleteProperty(document, "execCommand");
    }
  });

  it("reports copied LLM context using the full v2 trial count", async () => {
    const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    api.mockResolvedValueOnce({
      schema_version: "goldie.optimization-llm-context.v2",
      top_trials: [{ id: "trial-1" }],
      trials: [{ id: "trial-1" }, { id: "trial-2" }],
    });
    render(<OptimizationDetailPage />);

    fireEvent.click(screen.getByLabelText("Download optimization data"));
    fireEvent.click(screen.getAllByRole("button", { name: "LLM context JSON" }).at(1)!);

    await waitFor(() => {
      expect(screen.getByText("Copied LLM context with 2 trials.")).toBeInTheDocument();
    });
    if (clipboardDescriptor) {
      Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
    } else {
      Reflect.deleteProperty(navigator, "clipboard");
    }
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
