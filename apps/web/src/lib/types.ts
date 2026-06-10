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

