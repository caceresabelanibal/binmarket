export type TradingMode = "PAPER" | "TESTNET" | "LIVE";
export type SignalAction = "BUY" | "SELL" | "HOLD" | "NO_TRADE";
export type OrderStatus = "NEW" | "PARTIALLY_FILLED" | "FILLED" | "CANCELED" | "REJECTED" | "EXPIRED";
export type PositionStatus = "OPEN" | "CLOSED";

export interface Settings {
  mode: TradingMode;
  bot_enabled: boolean;
  bot_enabled_at: string | null;
  bot_disabled_at: string | null;
  bot_changed_by: string | null;
  bot_change_reason: string | null;
  max_risk_per_trade_pct: number;
  max_total_exposure_pct: number;
  max_position_size_pct: number;
  max_daily_loss_pct: number;
  max_weekly_loss_pct: number;
  max_open_positions: number;
  max_consecutive_losses: number;
  min_expected_net_profit_pct: number;
  taker_fee_pct: number;
  maker_fee_pct: number;
  default_slippage_pct: number;
  paper_starting_balance_usdt: number;
  emergency_stop_active: boolean;
  emergency_stop_reason: string | null;
  wizard_completed: boolean;
  wizard_step: number;
  auto_select_symbols_enabled: boolean;
  auto_select_max_symbols: number;
  auto_select_min_volume_usdt: number;
  stream_all_timeframes: boolean;
  orderbook_update_speed_ms: number;
}

export interface BandwidthCategoryUsage {
  bytes_per_min: number;
  kb_per_sec: number;
}

export interface BandwidthUsage {
  measured_minute: string;
  categories: Record<"ticker" | "orderbook" | "klines", BandwidthCategoryUsage>;
  total_bytes_per_min: number;
  total_kb_per_sec: number;
  estimated_mb_per_hour: number;
  selected_symbols_count: number;
  streams_per_symbol: number;
  total_streams: number;
  stream_all_timeframes: boolean;
  orderbook_update_speed_ms: number;
}

export interface SymbolInfo {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  status: string;
  is_selected: boolean;
  is_favorite: boolean;
  is_auto_selected: boolean;
  price_tick_size: number;
  lot_step_size: number;
  min_notional: number;
  last_price: number | null;
  price_change_pct_24h: number | null;
  volume_24h: number | null;
  high_24h: number | null;
  low_24h: number | null;
}

export interface SymbolListResponse {
  items: SymbolInfo[];
  total: number;
  page: number;
  page_size: number;
}

export interface SyncJob {
  id: string;
  symbol: string;
  timeframe: string;
  status: "PENDING" | "RUNNING" | "DONE" | "FAILED";
  candles_synced: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Candle {
  open_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Signal {
  id: string;
  symbol: string;
  timeframe: string;
  strategy_name: string;
  regime: string;
  action: SignalAction;
  opportunity_score: number;
  trend_score: number;
  momentum_score: number;
  volume_score: number;
  volatility_score: number;
  risk_score: number;
  reasons: string[];
  expected_net_profit_pct: number | null;
  risk_reward_ratio: number | null;
  suggested_entry_price: number | null;
  suggested_quantity: number | null;
  suggested_stop_loss: number | null;
  suggested_take_profit: number | null;
  acted_upon: boolean;
  order_id: string | null;
  created_at: string;
}

export interface Order {
  id: string;
  client_order_id: string;
  exchange_order_id: string | null;
  symbol: string;
  side: "BUY" | "SELL";
  type: string;
  status: OrderStatus;
  quantity: number;
  filled_quantity: number;
  avg_fill_price: number | null;
  commission_total: number;
  mode: TradingMode;
  strategy_name: string | null;
  reason: string;
  is_manual: boolean;
  created_at: string;
  position_id: string | null;
  position_status: PositionStatus | null;
  position_realized_pnl: number | null;
}

export interface Position {
  id: string;
  symbol: string;
  status: PositionStatus;
  entry_price: number;
  quantity: number;
  stop_loss: number | null;
  take_profit: number | null;
  realized_pnl: number;
  unrealized_pnl_pct: number | null;
  exit_price: number | null;
  close_reason: string | null;
  mode: TradingMode;
  strategy_name: string | null;
  opened_at: string;
  closed_at: string | null;
}

export interface PortfolioSummary {
  mode: string;
  total_equity: number;
  cash_balance: number;
  invested_value: number;
  pnl_today: number;
  pnl_week: number;
  pnl_month: number;
  pnl_total: number;
  roi_pct: number;
  win_rate_pct: number;
  drawdown_pct: number;
  open_positions_count: number;
}

export interface Snapshot {
  taken_at: string;
  total_equity: number;
  pnl_total: number;
  roi_pct: number;
  drawdown_pct: number;
}

export interface RiskState {
  mode: string;
  available_capital: number;
  open_positions_count: number;
  total_exposure_value: number;
  total_exposure_pct: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  weekly_pnl: number;
  weekly_pnl_pct: number;
  consecutive_losing_trades: number;
  emergency_stop_active: boolean;
  emergency_stop_reason: string | null;
  limits: Record<string, number>;
}

export interface RiskEvent {
  id: number;
  event_type: string;
  symbol: string | null;
  severity: "INFO" | "WARNING" | "CRITICAL";
  details: Record<string, unknown>;
  occurred_at: string;
}

export interface Strategy {
  id: number;
  name: string;
  version: string;
  description: string;
  parameters: Record<string, number | string | boolean>;
  is_enabled: boolean;
}

export interface Backtest {
  id: string;
  name: string;
  symbol: string;
  timeframe: string;
  strategy_name: string;
  parameters: Record<string, unknown>;
  start_date: string;
  end_date: string;
  initial_capital: number;
  fee_pct: number;
  slippage_pct: number;
  is_walk_forward: boolean;
  status: "PENDING" | "RUNNING" | "DONE" | "FAILED";
  error_message: string | null;
  results: Record<string, any>;
  equity_curve: { t: string; equity: number }[];
  created_at: string;
  finished_at: string | null;
}

export interface BinanceAssetValue {
  asset: string;
  amount: number;
  price_usdt: number;
  value_usdt: number;
}

export interface BinanceTotalValue {
  total_usdt?: number;
  total_ars?: number;
  usdt_ars_rate?: number;
  breakdown?: BinanceAssetValue[];
  unvalued_assets?: { asset: string; amount: number }[];
  error?: string;
}

export interface RealAccountHistoryEntry {
  id: number;
  taken_at: string;
  total_usdt: number;
  total_ars: number | null;
  usdt_ars_rate: number | null;
}

export interface RealAccountHistoryResponse {
  items: RealAccountHistoryEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface BinanceAccount {
  account_type?: string;
  can_trade?: boolean;
  can_withdraw?: boolean;
  balances?: { asset: string; free: string; locked: string }[];
  warnings?: string[];
  error?: string;
}

export interface DecisionLogEntry {
  id: string;
  symbol: string;
  strategy_name: string;
  action: SignalAction;
  opportunity_score: number;
  reasons: string[];
  suggested_quantity: number | null;
  risk_reward_ratio: number | null;
  created_at: string;
}

export interface SystemLog {
  id: number;
  level: string;
  service: string;
  message: string;
  context: Record<string, unknown>;
  occurred_at: string;
}

export interface BotEvent {
  id: number;
  action: string;
  performed_by: string;
  reason: string | null;
  context: Record<string, unknown>;
  occurred_at: string;
}
