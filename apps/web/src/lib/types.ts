export type Bot = {
  id: string;
  name: string;
  description: string;
  mode: "SHADOW" | "PAPER";
  state: string;
  active_config_version_id: string | null;
  created_at: string;
  updated_at: string;
};

export type BotConfig = {
  market: { symbol: string; timeframe: "M1" };
  strategy: {
    name: "basic_momentum";
    lookback_candles: number;
    min_momentum_points: number;
  };
  filters: { max_spread_points: number; stale_after_seconds: number };
  session: { timezone: string; start_time: string; end_time: string };
  theoretical_trade: {
    stop_loss_points: number;
    take_profit_points: number;
    risk_per_trade_pct: number;
    max_trade_duration_minutes: number;
    max_open_shadow_positions: number;
  };
};

export type ConfigVersion = {
  id: string;
  bot_id: string;
  version: number;
  status: "DRAFT" | "VALIDATED" | "ACTIVE" | "SUPERSEDED";
  config: BotConfig;
  validation_errors: unknown[] | null;
  created_at: string;
  activated_at: string | null;
};

export type Signal = {
  id: string;
  observed_at: string;
  signal: "BUY" | "SELL" | "NO_TRADE";
  reason_code: string;
  entry_price: string | null;
  stop_loss: string | null;
  take_profit: string | null;
  momentum_points: string | null;
  spread_points: string | null;
  outcome: ShadowTrade | null;
};

export type ShadowTrade = {
  id: string;
  signal_id: string;
  bot_id: string;
  run_id: string;
  config_version_id: string;
  direction: "BUY" | "SELL";
  status: "OPEN" | "CLOSED" | "SKIPPED";
  result: "WIN" | "LOSS" | "BREAKEVEN" | null;
  close_reason: "TAKE_PROFIT" | "STOP_LOSS" | "TIMEOUT" | "DATA_GAP" | null;
  skip_reason: string | null;
  opened_at: string | null;
  closed_at: string | null;
  entry_price: string | null;
  exit_price: string | null;
  stop_loss: string | null;
  take_profit: string | null;
  volume: string | null;
  risk_amount: string | null;
  gross_pnl: string | null;
  net_pnl: string | null;
  pnl_points: string | null;
  r_multiple: string | null;
  mfe_points: string;
  mae_points: string;
  duration_seconds: number | null;
};

export type PerformanceBreakdown = {
  key: string;
  trades: number;
  net_pnl: string | number;
};

export type Performance = {
  total_signals: number;
  closed_trades: number;
  open_trades: number;
  skipped_trades: number;
  win_rate: string | number | null;
  average_win: string | number | null;
  average_loss: string | number | null;
  net_pnl: string | number;
  total_points: string | number;
  total_r: string | number;
  profit_factor: string | number | null;
  expectancy: string | number | null;
  expectancy_r: string | number | null;
  max_drawdown: string | number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  average_duration_seconds: number | null;
  skipped_by_reason: Record<string, number>;
  equity_curve: Array<{ time: string; value: string | number }>;
  breakdown: {
    direction: PerformanceBreakdown[];
    hour_utc: PerformanceBreakdown[];
    run: PerformanceBreakdown[];
    config_version: PerformanceBreakdown[];
  };
};

export type BotStatus = {
  bot: Bot;
  agent: {
    id: string;
    name: string;
    adapter: string;
    status: string;
    last_heartbeat_at: string | null;
  } | null;
  agent_effective_status: string;
  latest_account: Record<string, string | number | boolean> | null;
  symbol_specification: Record<string, string | number> | null;
  latest_tick: {
    symbol: string;
    observed_at: string;
    bid: string;
    ask: string;
  } | null;
  recent_candles: Array<{
    opened_at: string;
    open: string;
    high: string;
    low: string;
    close: string;
    is_complete: boolean;
  }>;
  latest_signal: Signal | null;
  active_shadow_trade: ShadowTrade | null;
  active_run_id: string | null;
  data_state: "FRESH" | "STALE" | "MISSING";
};

export type Run = {
  id: string;
  config_version_id: string;
  mode: string;
  status: string;
  created_at: string;
  ended_at: string | null;
};

