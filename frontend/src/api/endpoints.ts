import { get, post, put } from "./client";
import type {
  Backtest,
  BandwidthUsage,
  BinanceAccount,
  BinanceTotalValue,
  BotEvent,
  Candle,
  DecisionLogEntry,
  Order,
  PortfolioSummary,
  Position,
  RealAccountHistoryResponse,
  RiskEvent,
  RiskState,
  Settings,
  Signal,
  Snapshot,
  Strategy,
  SymbolInfo,
  SymbolListResponse,
  SystemLog,
  TradeStats,
} from "./types";

export const auth = {
  login: (username: string, password: string) => post<{ username: string }>("/auth/login", { username, password }),
  logout: () => post("/auth/logout"),
  me: () => get<{ username: string }>("/auth/me"),
};

export const settingsApi = {
  get: () => get<Settings>("/settings"),
  updateRisk: (payload: Partial<Settings>) => put<Settings>("/settings/risk", payload),
  changeMode: (mode: string, confirmation_phrase?: string) => put<Settings>("/settings/mode", { mode, confirmation_phrase }),
  toggleBot: (enabled: boolean, reason?: string) => post<Settings>("/settings/bot/toggle", { enabled, reason }),
  updateWizard: (step?: number, completed?: boolean) => put<Settings>("/settings/wizard", { step, completed }),
  clearEmergencyStop: (note?: string) => post<Settings>("/settings/emergency-stop/clear", { note }),
  updateAutoSelect: (payload: { enabled?: boolean; max_symbols?: number; min_volume_usdt?: number }) =>
    put<Settings>("/settings/auto-select", payload),
  updateNetwork: (payload: { stream_all_timeframes?: boolean; orderbook_update_speed_ms?: number }) =>
    put<Settings>("/settings/network", payload),
};

export const binanceApi = {
  testConnectivity: () =>
    post<{ ping: boolean; server_time: number | null; account_reachable: boolean; error: string | null; environment: string; masked_api_key: string }>(
      "/binance/test-connectivity",
    ),
  account: () => get<BinanceAccount>("/binance/account"),
  totalValue: () => get<BinanceTotalValue>("/binance/account/total-value"),
  totalValueHistory: (page = 1, pageSize = 10) =>
    get<RealAccountHistoryResponse>(`/binance/account/total-value/history?page=${page}&page_size=${pageSize}`),
  tradeStats: () => get<TradeStats>("/binance/account/trade-stats"),
  exchangeInfo: (symbol?: string) => get<any>(`/binance/exchange-info${symbol ? `?symbol=${symbol}` : ""}`),
};

export const symbolsApi = {
  sync: () => post<{ created: number; updated: number }>("/symbols/sync"),
  list: (
    params: {
      selected_only?: boolean;
      favorites_only?: boolean;
      search?: string;
      page?: number;
      page_size?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.selected_only) qs.set("selected_only", "true");
    if (params.favorites_only) qs.set("favorites_only", "true");
    if (params.search) qs.set("search", params.search);
    qs.set("page", String(params.page ?? 1));
    qs.set("page_size", String(params.page_size ?? 50));
    return get<SymbolListResponse>(`/symbols?${qs.toString()}`);
  },
  select: (symbol: string, selected: boolean) => post<SymbolInfo>(`/symbols/${symbol}/select`, { selected }),
  favorite: (symbol: string, favorite: boolean) => post<SymbolInfo>(`/symbols/${symbol}/favorite`, { favorite }),
};

export const marketApi = {
  candles: (symbol: string, timeframe: string, limit = 300) => get<Candle[]>(`/market/candles?symbol=${symbol}&timeframe=${timeframe}&limit=${limit}`),
  backfill: (symbol: string, timeframe: string, start_date?: string, end_date?: string) =>
    post<{ id: string; status: string }>("/market/backfill", { symbol, timeframe, start_date, end_date }),
  backfillJobs: (symbol?: string) => get<any[]>(`/market/backfill/jobs${symbol ? `?symbol=${symbol}` : ""}`),
  backfillJob: (jobId: string) => get<any>(`/market/backfill/jobs/${jobId}`),
  backfillQueueLength: () => get<{ pending_in_queue: number }>("/market/backfill/queue-length"),
  ticker: (symbol: string) => get<any>(`/market/ticker?symbol=${symbol}`),
  bandwidth: () => get<BandwidthUsage>("/market/bandwidth"),
};

export const signalsApi = {
  list: (params: { symbol?: string; action?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.symbol) qs.set("symbol", params.symbol);
    if (params.action) qs.set("action", params.action);
    qs.set("limit", String(params.limit ?? 100));
    return get<Signal[]>(`/signals?${qs.toString()}`);
  },
};

export const ordersApi = {
  list: (params: { symbol?: string; mode?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.symbol) qs.set("symbol", params.symbol);
    if (params.mode) qs.set("mode", params.mode);
    qs.set("limit", String(params.limit ?? 100));
    return get<Order[]>(`/orders?${qs.toString()}`);
  },
};

export const positionsApi = {
  list: (params: { status_filter?: string; mode?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.status_filter) qs.set("status_filter", params.status_filter);
    if (params.mode) qs.set("mode", params.mode);
    return get<Position[]>(`/positions?${qs.toString()}`);
  },
};

export const manualTradingApi = {
  previewBuy: (payload: Record<string, unknown>) => post<any>("/manual-trading/buy/preview", payload),
  confirmBuy: (payload: Record<string, unknown>) => post<any>("/manual-trading/buy/confirm", payload),
  confirmSell: (position_id: string) => post<any>("/manual-trading/sell/confirm", { position_id }),
};

export const backtestsApi = {
  create: (payload: Record<string, unknown>) => post<Backtest>("/backtests", payload),
  list: () => get<Backtest[]>("/backtests"),
  get: (id: string) => get<Backtest>(`/backtests/${id}`),
  trades: (id: string) => get<any[]>(`/backtests/${id}/trades`),
};

export const strategiesApi = {
  list: () => get<Strategy[]>("/strategies"),
  update: (name: string, payload: Partial<Strategy>) => put<Strategy>(`/strategies/${name}`, payload),
};

export const riskApi = {
  state: () => get<RiskState>("/risk/state"),
  events: () => get<RiskEvent[]>("/risk/events"),
  triggerEmergencyStop: (reason: string) => post<{ status: string }>(`/risk/emergency-stop/trigger?reason=${encodeURIComponent(reason)}`),
};

export const logsApi = {
  decisions: (params: { symbol?: string; only_actionable?: boolean; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.symbol) qs.set("symbol", params.symbol);
    if (params.only_actionable) qs.set("only_actionable", "true");
    qs.set("limit", String(params.limit ?? 200));
    return get<DecisionLogEntry[]>(`/logs/decisions?${qs.toString()}`);
  },
  system: (params: { service?: string; level?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.service) qs.set("service", params.service);
    if (params.level) qs.set("level", params.level);
    return get<SystemLog[]>(`/logs/system?${qs.toString()}`);
  },
  botEvents: () => get<BotEvent[]>("/logs/bot-events"),
};

export const portfolioApi = {
  summary: () => get<PortfolioSummary>("/portfolio/summary"),
  snapshots: (days = 30) => get<Snapshot[]>(`/portfolio/snapshots?days=${days}`),
  breakdown: () => get<any[]>("/portfolio/breakdown"),
};

export const healthApi = {
  readiness: () => get<{ status: string; checks: Record<string, string> }>("/readiness"),
};
