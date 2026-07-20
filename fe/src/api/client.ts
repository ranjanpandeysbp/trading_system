import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

let authToken: string | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}

api.interceptors.request.use((config) => {
  const token = authToken ?? localStorage.getItem('ist_auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      const path = window.location.pathname
      const isAuthPage = ['/login', '/register', '/forgot-password', '/reset-password'].some((p) =>
        path.startsWith(p),
      )
      if (!isAuthPage) {
        localStorage.removeItem('ist_auth_token')
        setAuthToken(null)
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return 'Cannot reach server — start the backend: cd be && python run.py'
    }
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail) return JSON.stringify(detail)
    return error.message
  }
  return error instanceof Error ? error.message : 'Request failed'
}

export interface UserInfo {
  id: number
  name: string
  mobile: string
  email: string
  created_at?: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

export const registerUser = (payload: { name: string; mobile: string; email: string; password: string }) =>
  api.post<TokenResponse>('/auth/register', payload).then((r) => r.data)

export const loginUser = (payload: { identifier: string; password: string }) =>
  api.post<TokenResponse>('/auth/login', payload).then((r) => r.data)

export const forgotPassword = (email: string) =>
  api.post<{ message: string; reset_token?: string; reset_url?: string }>('/auth/forgot-password', { email }).then((r) => r.data)

export const resetPassword = (token: string, new_password: string) =>
  api.post<TokenResponse>('/auth/reset-password', { token, new_password }).then((r) => r.data)

export const fetchMe = () => api.get<UserInfo>('/auth/me').then((r) => r.data)

export const logoutUser = () => api.post('/auth/logout').then((r) => r.data)

export interface StrategyInfo {
  id: string
  name: string
  category: string
  category_label: string
  timeframes: string[]
  summary: string
  description: string
  indicators: string[]
  entry_rules: string[]
  exit_rules: string[]
  needs_benchmark: boolean
  min_bars: number
}

export interface StrategyCategoryInfo {
  id: string
  label: string
  description: string
  timeframes: string[]
  strategy_count: number
  strategies: StrategyInfo[]
}

export interface ScanSignal {
  ticker: string
  strategy: string
  strategy_label: string
  category: string
  timeframe: string
  action: 'BUY' | 'SELL' | 'HOLD'
  signal: number
  price: number
  day_high?: number | null
  day_low?: number | null
  sl_pct: number
  tp_pct: number
  confidence_pct: number
  timestamp: string
  rationale: string
}

export interface AccountSummary {
  id: number
  name: string
  cash_balance: number
  initial_capital: number
  portfolio_value: number
  total_pnl: number
  total_pnl_pct: number
  positions: Array<{
    id: number
    ticker: string
    quantity: number
    avg_price: number
    ltp: number
    side: string
    market_value: number
    pnl: number
    pnl_pct: number
    sl_pct?: number
    tp_pct?: number
    strategy?: string
  }>
  recent_orders: Array<PaperOrderRow>
  pending_orders: Array<PaperOrderRow>
}

export interface PaperOrderRow {
  id: number
  ticker: string
  side: string
  quantity: number
  price: number
  order_type: 'market' | 'limit' | 'stop' | 'stop_limit' | string
  status: 'filled' | 'pending' | 'cancelled' | string
  limit_price?: number | null
  trigger_price?: number | null
  filled_price?: number | null
  strategy?: string
  created_at: string
  filled_at?: string | null
  cancelled_at?: string | null
}

export interface PlaceOrderPayload {
  ticker: string
  side: 'buy' | 'sell'
  quantity: number
  price?: number
  strategy?: string
  sl_pct?: number
  tp_pct?: number
  order_type?: 'market' | 'limit' | 'stop' | 'stop_limit'
  limit_price?: number
  trigger_price?: number
}

export interface ModifyOrderPayload {
  quantity?: number
  limit_price?: number
  trigger_price?: number
}

export const fetchStrategies = () => api.get<StrategyInfo[]>('/strategies').then((r) => r.data)
export const fetchStrategyCategories = () =>
  api.get<StrategyCategoryInfo[]>('/strategies/categories').then((r) => r.data)
export const fetchScannerCategories = () =>
  api.get<StrategyCategoryInfo[]>('/strategies/scanner-categories').then((r) => r.data)
export const fetchStrategy = (id: string) => api.get<StrategyInfo>(`/strategies/${id}`).then((r) => r.data)
export const runScan = (payload: { tickers: string[]; strategies: string[]; timeframes: string[] }) =>
  api.post<{ signals: ScanSignal[]; scanned_at: string }>('/scanner/scan', payload).then((r) => r.data)
export const runBacktest = (payload: {
  ticker: string
  strategy: string
  timeframe: string
  period?: string
  costs_pct?: number
}) => api.post('/backtest/run', payload).then((r) => r.data)
export const getSettings = () => api.get<{
  data_provider: string
  groww_token_set: boolean
  groww_exchange: string
  initial_capital: number
  costs_pct: number
  benchmark_ticker: string
  gemini_token_set: boolean
  groq_token_set: boolean
  ai_provider: string
  groq_model: string
  gemini_model: string
  default_market: string
}>('/settings').then((r) => r.data)
export const updateSettings = (payload: Record<string, unknown>) => api.put('/settings', payload).then((r) => r.data)
export const testProvider = () => api.post('/settings/test-provider').then((r) => r.data)

export const fetchMarkets = () => api.get<{ markets: string[] }>('/markets').then((r) => r.data)

export const fetchAIConfig = () => api.get('/ai/config').then((r) => r.data)

export const askAI = (payload: {
  context: string
  question?: string
  section?: string
  max_tokens?: number
}) => api.post<{
  report: string
  verdict: string | null
  provider: string
  model: string
  error: boolean
}>('/ai/ask', payload, { timeout: 120_000 }).then((r) => r.data)
export const getAccount = () => api.get<AccountSummary>('/paper/account').then((r) => r.data)
export const placeOrder = (payload: PlaceOrderPayload) => api.post('/paper/orders', payload).then((r) => r.data)
export const cancelOrder = (orderId: number) => api.post(`/paper/orders/${orderId}/cancel`).then((r) => r.data)
export const modifyOrder = (orderId: number, payload: ModifyOrderPayload) =>
  api.post(`/paper/orders/${orderId}/modify`, payload).then((r) => r.data)
export const executeSignal = (signal: ScanSignal) => api.post('/paper/execute-signal', signal).then((r) => r.data)
export const resetAccount = () => api.post('/paper/reset').then((r) => r.data)

// Market Pulse (India only) — scans can take 1–3 min (NSE/yfinance)
const MP_TIMEOUT = 300_000

export const fetchMarketPulseSections = () =>
  api.get<{ sections: Array<{ id: string; label: string }> }>('/market-pulse/sections').then((r) => r.data)

export const fetchMarketPulseIndices = () =>
  api.get<{ indices: Array<{ group: string; name: string }> }>('/market-pulse/indices', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchMarketPulseIntelligence = () =>
  api.get('/market-pulse/intelligence', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchNiftyBreadth = (offset = 0, limit = 10) =>
  api.get('/market-pulse/nifty-breadth', { params: { offset, limit }, timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchNiftyMonthly = (offset = 0, limit = 2) =>
  api.get('/market-pulse/nifty-monthly', { params: { offset, limit }, timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchNiftyMovers = (index_name: string) =>
  api.get('/market-pulse/nifty-movers', { params: { index_name }, timeout: MP_TIMEOUT }).then((r) => r.data)

export const runGainersLosers = (payload: { index_name: string; tf_key: string; lookback_bars: number }) =>
  api.post('/market-pulse/gainers-losers', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runStockRotation = (payload: { index_name: string; tf_key: string; lookback_bars: number }) =>
  api.post('/market-pulse/stock-rotation', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchSectorRotation = () =>
  api.get('/market-pulse/sector-rotation', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchSectorRotationIntraday = () =>
  api.get('/market-pulse/sector-rotation/intraday', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchSectorRotationMarket = (market: 'us' | 'crypto') =>
  api.get(`/market-pulse/sector-rotation/${market}`, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchSectorRotationMarketIntraday = (market: 'us' | 'crypto') =>
  api.get(`/market-pulse/sector-rotation/${market}/intraday`, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchStockRotationUniverses = (market: 'us' | 'crypto') =>
  api.get<{ universes: Array<{ id: string; label: string }> }>(
    `/market-pulse/stock-rotation/${market}/universes`,
  ).then((r) => r.data)

export const runStockRotationMarket = (
  market: 'us' | 'crypto',
  payload: { universe_id: string; tf_key: string; lookback_bars: number },
) => api.post(`/market-pulse/stock-rotation/${market}`, payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchOppositeHedge = (capital = 100000) =>
  api.get('/market-pulse/opposite-hedge', { params: { capital }, timeout: MP_TIMEOUT }).then((r) => r.data)

export const runMtfBias = (tickers: string[]) =>
  api.post('/market-pulse/mtf-bias', { tickers }, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchWeek52 = (index_name: string) =>
  api.get('/market-pulse/week52', { params: { index_name }, timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchHeatmap = (timeframe = '1d', mode = 'sectoral') =>
  api.get('/market-pulse/heatmap', { params: { timeframe, mode }, timeout: MP_TIMEOUT }).then((r) => r.data)

export const runCommodityScreener = (timeframes?: string[]) =>
  api.post('/market-pulse/commodity-screener', { timeframes }, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchTomorrowOutlook = () =>
  api.get('/market-pulse/tomorrow-outlook', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runSentimentScreener = (payload: { tickers: string[]; timeframes?: string[]; lookback_days?: number }) =>
  api.post('/market-pulse/sentiment-screener', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runMtfScanner = (payload: { tickers: string[]; timeframes?: string[] }) =>
  api.post('/market-pulse/mtf-scanner', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTickerInvestigation = (payload: {
  tickers: string[]
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
}) =>
  api.post('/market-pulse/ticker-investigation', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchCommandCenterSections = () =>
  api.get('/command-center/sections').then((r) => r.data)

export const fetchTickerUniverse = (asset_class: string) =>
  api.get('/command-center/ticker-universe', { params: { asset_class } }).then((r) => r.data)

export const fetchTickerSuggestions = (asset_class: string, q: string, limit = 20) =>
  api.get<{ tickers: string[] }>('/command-center/ticker-suggestions', { params: { asset_class, q, limit } }).then((r) => r.data)

export const runBuySellAdvisor = (payload: {
  tickers: string[]
  asset_class?: string
  scenario?: string
  durations?: string[]
}) => api.post('/command-center/buy-sell', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runMegaAnalyser = (payload: {
  tickers: string[]
  asset_class?: string
  durations?: string[]
}) => api.post('/command-center/mega-analyser', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchTaScreeners = () =>
  api.get('/technical-analysis/screeners').then((r) => r.data)

export const runTaScreener = (payload: {
  screener_id: string
  tickers: string[]
  timeframe?: string
  options?: Record<string, unknown>
}) => api.post('/technical-analysis/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchStrategyLabSections = () =>
  api.get('/strategy-lab/sections').then((r) => r.data)

export const fetchStrategyLabPresets = (market?: string) =>
  api.get('/strategy-lab/presets', { params: market ? { market } : undefined }).then((r) => r.data)

export const runStrategyLabBacktest = (payload: Record<string, unknown>) =>
  api.post('/strategy-lab/backtest', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runStrategyLabMultiCombo = (payload: Record<string, unknown>) =>
  api.post('/strategy-lab/multi-combo', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runStrategyLabScreener = (payload: Record<string, unknown>) =>
  api.post('/strategy-lab/screener', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runSeasonalityAnalyze = (payload: { tickers: string[]; years?: number }) =>
  api.post('/seasonality/analyze', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchAlertsConfig = () => api.get('/alerts/config').then((r) => r.data)

export const fetchAlertMonitors = () => api.get('/alerts/monitors').then((r) => r.data)

export const createAlertMonitor = (payload: Record<string, unknown>) =>
  api.post('/alerts/monitors', payload).then((r) => r.data)

export const deleteAlertMonitor = (id: number) =>
  api.delete(`/alerts/monitors/${id}`).then((r) => r.data)

export const toggleAlertMonitor = (id: number, enabled: boolean) =>
  api.patch(`/alerts/monitors/${id}`, null, { params: { enabled } }).then((r) => r.data)

export const pollAlerts = (force = false) =>
  api.post('/alerts/poll', null, { params: { force }, timeout: MP_TIMEOUT }).then((r) => r.data)

export interface TradingHubSection {
  id: string
  label: string
  description: string
  config_options: Record<string, {
    type: string
    label: string
    choices?: Array<{ value: string; label: string }>
    default?: string
  }>
}

export interface TradingHub {
  id: string
  label: string
  description: string
  sections: TradingHubSection[]
}

export const fetchTradingHubs = () =>
  api.get<{ hubs: TradingHub[] }>('/trading-hubs', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradingHubScan = (payload: {
  section_id: string
  tickers: string[]
  asset_class?: string
  config?: Record<string, unknown>
  run_backtest?: boolean
}) => api.post('/trading-hubs/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchEtfTaUniverse = () =>
  api.get<{ presets: Record<string, string[]>; default_symbols: string[]; shop_39: string[]; master_backup: string[] }>(
    '/etf-ta/universe',
    { timeout: MP_TIMEOUT },
  ).then((r) => r.data)

export const scanEtfTaStf = (payload: { symbols?: string[]; exchange?: string }) =>
  api.post('/etf-ta/stf-shop/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const recommendEtfTaStf = (payload: Record<string, unknown>) =>
  api.post('/etf-ta/stf-shop/recommend', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export interface WatchlistInfo {
  id: number
  market_type: 'india' | 'us' | 'crypto'
  name: string
  created_at: string
}

export interface WatchlistItemInfo {
  id: number
  watchlist_id: number
  ticker: string
  display_name: string
  added_price: number | null
  added_at: string
  ltp?: number | null
  change_pct?: number | null
  change_since_added_pct?: number | null
}

export const fetchWatchlists = () =>
  api.get<{ watchlists: WatchlistInfo[] }>('/watchlists').then((r) => r.data)

export const createWatchlist = (payload: { market_type: string; name: string }) =>
  api.post<WatchlistInfo>('/watchlists', payload).then((r) => r.data)

export const deleteWatchlist = (id: number) =>
  api.delete(`/watchlists/${id}`).then((r) => r.data)

export const fetchWatchlistItems = (id: number) =>
  api.get<WatchlistInfo & { items: WatchlistItemInfo[] }>(`/watchlists/${id}/items`, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const addWatchlistItem = (
  watchlistId: number,
  payload: { ticker: string; display_name?: string; added_price?: number | null },
) => api.post<WatchlistItemInfo>(`/watchlists/${watchlistId}/items`, payload).then((r) => r.data)

export const removeWatchlistItem = (watchlistId: number, itemId: number) =>
  api.delete(`/watchlists/${watchlistId}/items/${itemId}`).then((r) => r.data)

// Command Center — standalone tools
export const fetchGlobalMarketMood = () =>
  api.get('/command-center/global-market-mood', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runMomentumScan = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/momentum', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runEmaPositionScan = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/ema-position', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetup = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/trade-setup', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

type TradeSetupDrillPayload = { ticker: string; asset_class: string; timeframe: string }

export const runTradeSetupPatterns = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/patterns', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupSupportResistance = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/support-resistance', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupSmartMoney = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/smart-money', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupScalping = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/scalping', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupTimeSeries = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/time-series', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupDivergence = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/divergence', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runDivergences = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/divergences', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runPatterns = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/patterns', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupStopHunt = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/stop-hunt', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runStopHunt = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/stop-hunt', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupTakeProfit = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/take-profit', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTakeProfit = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/take-profit', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupRealBottom = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/real-bottom', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupIntraHwp = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/intra-hwp', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupWeakStrong = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/weak-strong', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runRealBottom = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/real-bottom', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runWeakStrong = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/weak-strong', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupCopyTrade = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/copy-trade', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runCopyTrade = (payload: { tickers: string[]; asset_class: string }) =>
  api.post('/command-center/copy-trade', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTakeTrade = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/take-trade', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOneClick = (payload: { style: 'intraday' | 'scalping' | 'swing'; tickers: string[]; asset_class: string }) =>
  api.post('/command-center/one-click', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runFundamentalAnalysis = (payload: { tickers: string[]; asset_class: string }) =>
  api.post('/command-center/fundamental-analysis', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runUpgradeDowngradeScan = (payload: { tickers: string[]; asset_class: string }) =>
  api.post('/command-center/upgrade-downgrade', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchInvestigationStrategyCatalog = () =>
  api.get<{ groups: Record<string, Array<{ id: string; label: string }>> }>(
    '/command-center/investigation-strategies/catalog',
  ).then((r) => r.data)

export const runInvestigationWithStrategies = (payload: {
  tickers: string[]
  asset_class: string
  strategy_ids: string[]
}) => api.post('/command-center/investigation-strategies/run', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runMegaSetupAdvisor = (payload: {
  market: string
  timeframes: string[]
  ticker_count?: number
  use_ai?: boolean
  user_goal?: string
}) => api.post('/command-center/mega-setup-advisor', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchCoinDcx24hVolatility = () =>
  api.get('/command-center/coindcx-24h-volatility', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchNseIndices = () =>
  api.get('/command-center/nse-indices', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchGlobalIndices = () =>
  api.get('/command-center/global-indices', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchFuturesIndices = () =>
  api.get('/command-center/futures-indices', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchGiftNifty = () =>
  api.get('/command-center/gift-nifty', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchIndiaMarketHeatmapIndices = () =>
  api.get<{ index_names: string[] }>('/command-center/india-market-heatmap/indices', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runIndiaMarketHeatmap = (payload: { index_name: string }) =>
  api.post('/command-center/india-market-heatmap', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionChain = (payload: { symbol: string; is_index: boolean }) =>
  api.post('/command-center/option-chain', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runQuickAnalyzer = (payload: {
  tickers: string[]
  timeframes: string[]
  asset_class: 'india' | 'us' | 'crypto'
  from_date?: string
  to_date?: string
  include_fundamentals?: boolean
  include_option_chain?: boolean
}) => api.post('/command-center/quick-analyzer', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchMutualFundAmcs = () =>
  api.get<{ amcs: Array<{ Id: number; Name: string }> }>('/command-center/mutual-fund/amcs', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchMutualFundSchemes = (amcId: number) =>
  api.get<{ schemes: Array<Record<string, unknown>> }>('/command-center/mutual-fund/schemes', {
    params: { amc_id: amcId },
    timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const runMutualFundHoldingsChange = (payload: {
  scheme_ids: number[]
  scheme_names: Record<number, string>
  from_date: string
  to_date: string
}) => api.post('/command-center/mutual-fund/holdings', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)
