import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CollectorFeedPage from "./page";

const useQuery = vi.fn();
let continuityError: Error | null = null;

vi.mock("next/navigation", () => ({ useParams: () => ({ feedId: "feed-1" }) }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: unknown) => useQuery(options),
  useQueryClient: () => ({
    setQueryData: vi.fn(),
    invalidateQueries: vi.fn(),
  }),
}));
vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  openCollectorStream: vi.fn(() => () => undefined),
}));
vi.mock("@/components/status-pill", () => ({
  StatusPill: ({ value }: { value: string }) => <span>{value}</span>,
}));

const detail = {
  feed: {
    id: "feed-1",
    provider: "binance_spot",
    environment: "spot",
    canonical_symbol: "BTCUSDT",
    provider_symbol: "BTCUSDT",
    status: "ONLINE",
    last_heartbeat_at: "2026-06-29T10:58:29Z",
    latest_tick: null,
    earliest_candle_at: "2025-05-01T00:00:00Z",
    latest_candle_at: "2026-06-29T10:57:00Z",
    data_lag_seconds: null,
    bot_count: 0,
  },
  agent: null,
  instrument_settings: {
    provider_symbol: "BTCUSDT",
    enabled: true,
    overrides: {},
    provider: "binance_spot",
    environment: "spot",
    market_feed_id: "feed-1",
    canonical_symbol: "BTCUSDT",
  },
  gap_count: 0,
  gaps: [],
  commands: [],
};

const continuity = {
  market_feed_id: "feed-1",
  symbol: "BTCUSDT",
  timeframe: "M1",
  computed_at: "2026-06-29T11:00:00Z",
  full_history: {
    status: "BLOCK",
    date_from: "2025-05-01T00:00:00Z",
    date_to: "2026-06-29T10:57:00Z",
    observed_candles: 452927,
    expected_candles: 611218,
    coverage_pct: 74.105637,
    gap_segment_count: 101,
    missing_minutes: 158291,
    market_closed_gap_count: 0,
    market_closed_missing_minutes: 0,
    gaps: [{
      from: "2026-02-06T11:20:00Z",
      to: "2026-05-27T09:30:00Z",
      missing_minutes: 158291,
    }],
    gaps_truncated: true,
  },
  recent_24h: {
    status: "PASS",
    date_from: "2026-06-28T10:57:00Z",
    date_to: "2026-06-29T10:57:00Z",
    observed_candles: 1441,
    expected_candles: 1441,
    coverage_pct: 100,
    gap_segment_count: 0,
    missing_minutes: 0,
    market_closed_gap_count: 0,
    market_closed_missing_minutes: 0,
    gaps: [],
    gaps_truncated: false,
  },
};

describe("Collector feed Data tab", () => {
  beforeEach(() => {
    continuityError = null;
    useQuery.mockImplementation(({ queryKey }: { queryKey: string[] }) => {
      if (queryKey[0] === "collector-feed") {
        return { data: detail, isLoading: false, error: null };
      }
      if (queryKey[0] === "collector-continuity") {
        return {
          data: continuityError ? undefined : continuity,
          isLoading: false,
          error: continuityError,
        };
      }
      return { data: { configuration: {}, instruments: [] }, isLoading: false, error: null };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads continuity only when Data is selected and separates full from recent health", () => {
    render(<CollectorFeedPage />);
    const initialContinuityQuery = useQuery.mock.calls.find(
      ([options]) => options.queryKey[0] === "collector-continuity",
    )?.[0];
    expect(initialContinuityQuery.enabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Data" }));

    expect(screen.getByRole("heading", { name: "Full history continuity" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Latest 24 hours" })).toBeInTheDocument();
    expect(screen.getByText("158,291m")).toBeInTheDocument();
    expect(screen.getByText("Showing largest 100 of 101 gaps.")).toBeInTheDocument();
    expect(screen.getAllByText("BLOCK").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PASS").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/UTC/).length).toBeGreaterThan(0);

    const activeContinuityQuery = useQuery.mock.calls
      .map(([options]) => options)
      .filter((options) => options.queryKey[0] === "collector-continuity")
      .at(-1);
    expect(activeContinuityQuery.enabled).toBe(true);
  });

  it("shows a Data-only continuity error without replacing the feed page", () => {
    continuityError = new Error("Continuity query failed");
    render(<CollectorFeedPage />);
    fireEvent.click(screen.getByRole("button", { name: "Data" }));

    expect(screen.getByText("Continuity query failed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "BTCUSDT" })).toBeInTheDocument();
  });

  it("opens Commands and pre-fills the historical backfill from a selected gap", () => {
    render(<CollectorFeedPage />);
    fireEvent.click(screen.getByRole("button", { name: "Data" }));

    fireEvent.click(screen.getAllByRole("button", { name: /Backfill gap/ })[0]);

    expect(screen.getByRole("heading", { name: "Historical backfill" })).toBeInTheDocument();
    const start = screen.getByLabelText("Start") as HTMLInputElement;
    const end = screen.getByLabelText("End") as HTMLInputElement;
    expect(new Date(start.value).toISOString()).toBe("2026-02-06T11:20:00.000Z");
    expect(new Date(end.value).toISOString()).toBe("2026-05-27T09:31:00.000Z");
  });
});
