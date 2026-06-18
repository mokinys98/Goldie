export type Bot = {
  id: string;
  name: string;
  description: string;
  mode: "SHADOW" | "PAPER";
  state: string;
  active_config_version_id: string | null;
  market_feed_id: string | null;
  strategy_profile_id?: string | null;
  config_overrides?: Record<string, unknown>;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type BotConfig = {
  market: { symbol: string; timeframe: "M1" };
  strategy: {
    name: string;
    parameters: Record<string, string | number | boolean>;
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
  strategy_profile_id?: string | null;
  config_overrides?: Record<string, unknown>;
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
  inputs: Record<string, string | number | boolean | null>;
  outcome: ShadowTrade | null;
};

export type StrategyParameterMetadata = {
  title?: string;
  description?: string;
  type?: "integer" | "number" | "boolean" | "string";
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  default?: string | number | boolean;
  unit?: string;
  impact?: string;
};

export type StrategyMetadata = {
  name: string;
  description: string;
  required_candles: number;
  parameters: Record<string, StrategyParameterMetadata>;
  defaults: Record<string, string | number | boolean>;
};

export type StrategyProfile = {
  id: string;
  name: string;
  description: string;
  status: "DRAFT" | "ACTIVE" | "ARCHIVED";
  config: BotConfig;
  bot_count: number;
  created_at: string;
  updated_at: string;
};

export type ConfigurationSchema = Record<
  string,
  Record<string, StrategyParameterMetadata>
>;

export type BulkBotResult = {
  market_feed_id: string;
  name: string;
  status: "CREATED" | "EXISTS" | "FAILED";
  bot: Bot | null;
  error: string | null;
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
  paper_account: Record<string, string | number | boolean> | null;
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
  data_state: "FRESH" | "STALE" | "MISSING" | "MARKET_CLOSED";
};

export type MarketFeed = {
  id: string;
  provider: string;
  environment: string;
  canonical_symbol: string;
  provider_symbol: string;
  status: string;
  last_heartbeat_at: string | null;
};

export type Run = {
  id: string;
  config_version_id: string;
  mode: string;
  status: string;
  created_at: string;
  ended_at: string | null;
};

export type CollectorConfiguration = {
  id: string;
  version: number;
  quote_interval_seconds: string | number;
  candle_poll_seconds: string | number;
  heartbeat_seconds: string | number;
  backfill_days: number;
  backfill_batch_size: number;
  configuration_retry_seconds: string | number;
  updated_at: string;
};

export type CollectorInstrumentSettings = {
  id?: string;
  provider_symbol: string;
  canonical_symbol: string;
  enabled: boolean;
  overrides: Record<string, string | number>;
  market_feed_id: string | null;
};

export type CollectorCommand = {
  id: string;
  collector_instance_id: string | null;
  market_feed_id: string | null;
  command: "PAUSE" | "RESUME" | "RECONNECT" | "BACKFILL";
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  payload: Record<string, unknown>;
  progress: Record<string, string | number>;
  result: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type CollectorFeedSummary = {
  id: string;
  provider: string;
  environment: string;
  canonical_symbol: string;
  provider_symbol: string;
  status: string;
  last_heartbeat_at: string | null;
  latest_tick: {
    observed_at: string;
    bid: string | number;
    ask: string | number;
    spread: string | number;
  } | null;
  latest_candle_at: string | null;
  data_lag_seconds: number | null;
  bot_count: number;
};

export type CollectorOverview = {
  instance: {
    id: string;
    name: string;
    status: string;
    reported_status: string;
    last_heartbeat_at: string | null;
    applied_config_version: number | null;
    details: Record<string, unknown>;
  } | null;
  counts: {
    online: number;
    paused: number;
    error: number;
    market_closed: number;
    ticks_24h: number;
    candles_24h: number;
  };
  feeds: CollectorFeedSummary[];
  recent_commands: CollectorCommand[];
};

export type CollectorSettingsResponse = {
  configuration: CollectorConfiguration;
  instruments: CollectorInstrumentSettings[];
};

export type CollectorFeedDetail = {
  feed: CollectorFeedSummary;
  agent: Record<string, unknown> | null;
  instrument_settings: CollectorInstrumentSettings;
  gap_count: number;
  commands: CollectorCommand[];
};

export type PageResult<T> = {
  items: T[];
  next_cursor: string | null;
};

export type CollectorCandle = {
  opened_at: string;
  open: string | number;
  high: string | number;
  low: string | number;
  close: string | number;
  volume: number;
  complete: boolean;
};

export type CollectorTick = {
  observed_at: string;
  received_at: string;
  bid: string | number;
  ask: string | number;
  spread: string | number;
};

export type BacktestExperiment = {
  id: string;
  bot_id: string;
  config_version_id: string;
  market_feed_id: string;
  run_id: string;
  status: "PENDING" | "RUNNING" | "CANCEL_REQUESTED" | "CANCELLED" | "SUCCEEDED" | "FAILED";
  date_from: string;
  date_to: string;
  initial_capital: string | number;
  fill_mode: "perfect" | "simulated";
  fee_maker: string | number;
  fee_taker: string | number;
  taker_slippage: string | number;
  slippage_small: string | number;
  slippage_medium: string | number;
  medium_impact: string | number;
  impact_model: "sqrt";
  model_sqrt_limit: string | number;
  limit_fill_timeout_s: number;
  min_qty_threshold: string | number;
  min_qty_check: boolean;
  config_snapshot: BotConfig;
  progress: { processed?: number; total?: number };
  summary: {
    total_trades?: number;
    wins?: number;
    losses?: number;
    win_rate?: string | number | null;
    average_win?: string | number | null;
    average_loss?: string | number | null;
    profit_factor?: string | number | null;
    gross_pnl?: string | number;
    commission?: string | number;
    net_pnl?: string | number;
    final_equity?: string | number;
    max_drawdown?: string | number;
    max_consecutive_losses?: number;
    equity_curve?: Array<{ time: string; value: string | number }>;
  };
  reason_counts: Record<string, number>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type BacktestTrade = {
  id: string;
  experiment_id: string;
  direction: "BUY" | "SELL";
  signal_at: string;
  opened_at: string;
  closed_at: string;
  entry_price: string | number;
  exit_price: string | number;
  stop_loss: string | number;
  take_profit: string | number;
  volume: string | number;
  risk_amount: string | number;
  close_reason: string;
  gross_pnl: string | number;
  commission: string | number;
  net_pnl: string | number;
  pnl_points: string | number;
  r_multiple: string | number;
  mfe_points: string | number;
  mae_points: string | number;
  duration_seconds: number;
};

export type BacktestTradePage = {
  items: BacktestTrade[];
  total: number;
};

export type BotsPerformance = {
  date_from: string;
  date_to: string;
  total: Performance;
  items: Array<{
    bot: Pick<Bot, "id" | "name" | "mode" | "state">;
    performance: Performance;
  }>;
};

export type BatchBacktestResult = {
  bot_id: string;
  status: "CREATED" | "FAILED";
  experiment: BacktestExperiment | null;
  error: string | null;
};

export type OptimizationRun = {
  id: string;
  bot_id: string;
  config_version_id: string;
  market_feed_id: string;
  run_id: string;
  status: "PENDING" | "RUNNING" | "CANCEL_REQUESTED" | "CANCELLED" | "SUCCEEDED" | "FAILED";
  date_from: string;
  date_to: string;
  n_trials: number;
  objective: "BALANCED";
  initial_capital: string | number;
  fill_mode: "perfect" | "simulated";
  fee_maker: string | number;
  fee_taker: string | number;
  taker_slippage: string | number;
  slippage_small: string | number;
  slippage_medium: string | number;
  medium_impact: string | number;
  impact_model: "sqrt";
  model_sqrt_limit: string | number;
  limit_fill_timeout_s: number;
  min_qty_threshold: string | number;
  min_qty_check: boolean;
  config_snapshot: BotConfig;
  progress: {
    completed_trials?: number;
    successful_trials?: number;
    failed_trials?: number;
    total_trials?: number;
  };
  best_candidate: {
    trial_number?: number;
    sampled_parameters?: Record<string, string | number | boolean>;
    score?: string | number;
    metrics?: Record<string, string | number>;
    summary?: Record<string, unknown>;
  };
  summary: {
    completed_trials?: number;
    failed_trials?: number;
    duration_seconds?: number;
    search_space?: Array<{
      name: string;
      type?: string;
      minimum?: number;
      maximum?: number;
      choices?: Array<string | number | boolean>;
    }>;
    execution_model?: Record<string, string | number | boolean>;
    top_candidates?: Array<{
      trial_number: number;
      sampled_parameters: Record<string, string | number | boolean>;
      score: string | number;
      metrics: Record<string, string | number>;
      summary: Record<string, unknown>;
    }>;
  };
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type OptimizationTrial = {
  id: string;
  optimization_run_id: string;
  trial_number: number;
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  sampled_parameters: Record<string, string | number | boolean>;
  score: string | number | null;
  metrics: Record<string, string | number>;
  summary: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type OptimizationTrialPage = {
  items: OptimizationTrial[];
  total: number;
};
