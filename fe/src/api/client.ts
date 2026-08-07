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
    notes?: string | null
    opened_at?: string | null
    asset_class?: string
  }>
  recent_orders: Array<PaperOrderRow>
  pending_orders: Array<PaperOrderRow>
  closed_trades: number
  wins: number
  losses: number
  breakeven: number
  win_rate_pct: number | null
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
  realized_pnl?: number | null
  strategy?: string
  notes?: string | null
  created_at: string
  filled_at?: string | null
  cancelled_at?: string | null
  asset_class?: string
}

export interface PlaceOrderPayload {
  ticker: string
  side: 'buy' | 'sell'
  quantity: number
  price?: number
  strategy?: string
  notes?: string
  sl_pct?: number
  tp_pct?: number
  order_type?: 'market' | 'limit' | 'stop' | 'stop_limit'
  limit_price?: number
  trigger_price?: number
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
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
export const runScan = (payload: {
  tickers: string[]
  strategies: string[]
  timeframes: string[]
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
  bars?: number
}) =>
  api.post<{ signals: ScanSignal[]; scanned_at: string }>('/scanner/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)
export const runBacktest = (payload: {
  ticker: string
  strategy: string
  timeframe: string
  period?: string
  costs_pct?: number
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
}) => api.post('/backtest/run', payload).then((r) => r.data)

export const fetchBacktesterLeaderboardCatalog = () =>
  api.get<{ categories: StrategyCategoryInfo[] }>('/backtester/leaderboard/catalog').then((r) => r.data)

export const startBacktesterLeaderboardJob = (payload: {
  tickers: string[]
  strategy_ids: string[]
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
  timeframe?: string
  period?: string
  costs_pct?: number
  bars?: number
  forward_bars?: number
  direction?: 'both' | 'long_only' | 'short_only'
  report_name?: string
  run_in_background?: boolean
}) => api.post('/backtester/leaderboard/start', payload).then((r) => r.data)

export const fetchBacktesterLeaderboardJobs = (status?: string) =>
  api.get('/backtester/leaderboard/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchBacktesterLeaderboardJob = (jobId: string) =>
  api.get(`/backtester/leaderboard/jobs/${jobId}`).then((r) => r.data)

export const saveBacktesterReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/backtester/leaderboard/reports', payload).then((r) => r.data)

export const fetchBacktesterReports = () =>
  api.get('/backtester/leaderboard/reports').then((r) => r.data)

export const fetchBacktesterReport = (reportId: number) =>
  api.get(`/backtester/leaderboard/reports/${reportId}`).then((r) => r.data)

export const deleteBacktesterReport = (reportId: number) =>
  api.delete(`/backtester/leaderboard/reports/${reportId}`).then((r) => r.data)
export const getSettings = () => api.get<{
  data_provider: string
  groww_token_set: boolean
  groww_exchange: string
  initial_capital: number
  costs_pct: number
  benchmark_ticker: string
  gemini_token_set: boolean
  groq_token_set: boolean
  claude_token_set: boolean
  openai_token_set: boolean
  ai_provider: string
  groq_model: string
  gemini_model: string
  claude_model: string
  claude_endpoint: string
  openai_model: string
  openai_endpoint: string
  default_market: string
  youtube_api_key_set: boolean
  youtube_channel_ids: string
  superinvesting_token_set: boolean
}>('/settings').then((r) => r.data)
export const updateSettings = (payload: Record<string, unknown>) => api.put('/settings', payload).then((r) => r.data)
export const testProvider = () => api.post('/settings/test-provider').then((r) => r.data)

export const fetchMarkets = () => api.get<{ markets: string[] }>('/markets').then((r) => r.data)

export const fetchAIConfig = () => api.get('/ai/config').then((r) => r.data)

export const askAI = (payload: {
  context: string
  question?: string
  section?: string
  system_prompt?: string
  max_tokens?: number
}) => api.post<{
  report: string
  verdict: string | null
  provider: string
  model: string
  error: boolean
}>('/ai/ask', payload, { timeout: 180_000 }).then((r) => r.data)

export const fetchYoutubeAnalysisPrefs = () =>
  api
    .get<{
      youtube_api_key_set: boolean
      youtube_channel_ids: string
      gemini_token_set: boolean
      gemini_model: string
    }>('/youtube-analysis/prefs')
    .then((r) => r.data)

export const saveYoutubeAnalysisPrefs = (payload: {
  youtube_api_key?: string
  youtube_channel_ids?: string
}) =>
  api
    .put<{
      youtube_api_key_set: boolean
      youtube_channel_ids: string
      gemini_token_set: boolean
      gemini_model: string
    }>('/youtube-analysis/prefs', payload)
    .then((r) => r.data)

export const runYoutubeAnalysisScan = (payload: {
  youtube_api_key?: string
  video_urls?: string[]
  channel_ids?: string[]
  from_date?: string
  to_date?: string
  max_per_channel?: number
  fetch_transcripts?: boolean
  save_api_key?: boolean
}) =>
  api
    .post<Record<string, unknown>>('/youtube-analysis/scan', payload, { timeout: 600_000 })
    .then((r) => r.data)

export const runYoutubeAnalysisAiView = (payload: {
  ai_context?: string
  scan?: Record<string, unknown>
  question?: string
  max_tokens?: number
}) =>
  api
    .post<{
      report: string
      verdict: string | null
      provider: string
      model: string
      error: boolean
    }>('/youtube-analysis/ai-view', payload, { timeout: 180_000 })
    .then((r) => r.data)

export type SavedYoutubeAiViewSummary = {
  id: number
  name: string
  created_at: string
  updated_at: string | null
  summary?: {
    verdict?: string | null
    provider?: string | null
    model?: string | null
    video_count?: number
    snapshot_note?: string | null
    report_preview?: string
  }
}

export type SavedYoutubeAiViewPayload = {
  report: string
  verdict?: string | null
  provider?: string | null
  model?: string | null
  ai_context?: string
  video_urls?: string[]
  from_date?: string | null
  to_date?: string | null
  snapshot_note?: string | null
  edited?: boolean
}

export const saveYoutubeAiView = (payload: { name: string } & SavedYoutubeAiViewPayload) =>
  api.post<{ id: number; name: string; created_at: string }>('/youtube-analysis/ai-views', payload).then((r) => r.data)

export const fetchYoutubeAiViews = () =>
  api.get<{ ai_views: SavedYoutubeAiViewSummary[] }>('/youtube-analysis/ai-views').then((r) => r.data)

export const fetchYoutubeAiView = (viewId: number) =>
  api
    .get<{ id: number; name: string; created_at: string; updated_at: string | null; payload: SavedYoutubeAiViewPayload }>(
      `/youtube-analysis/ai-views/${viewId}`,
    )
    .then((r) => r.data)

export const updateYoutubeAiView = (viewId: number, payload: { name?: string; report?: string }) =>
  api.put(`/youtube-analysis/ai-views/${viewId}`, payload).then((r) => r.data)

export const deleteYoutubeAiView = (viewId: number) =>
  api.delete(`/youtube-analysis/ai-views/${viewId}`).then((r) => r.data)

export const getAccount = () => api.get<AccountSummary>('/paper/account').then((r) => r.data)
export const fetchPaperPrice = (ticker: string, assetClass: string = 'india') =>
  api.get<{ ticker: string; price: number }>('/paper/price', { params: { ticker, asset_class: assetClass } }).then((r) => r.data)
export const placeOrder = (payload: PlaceOrderPayload) => api.post('/paper/orders', payload).then((r) => r.data)
export const cancelOrder = (orderId: number) => api.post(`/paper/orders/${orderId}/cancel`).then((r) => r.data)
export const modifyOrder = (orderId: number, payload: ModifyOrderPayload) =>
  api.post(`/paper/orders/${orderId}/modify`, payload).then((r) => r.data)
export const executeSignal = (signal: ScanSignal & { asset_class?: string }) =>
  api.post('/paper/execute-signal', signal).then((r) => r.data)
export const resetAccount = () => api.post('/paper/reset').then((r) => r.data)
export const deletePaperOrders = (ids: number[]) =>
  api.post('/paper/orders/delete-bulk', { ids }).then((r) => r.data)
export const closePaperPositions = (ids: number[]) =>
  api.post('/paper/positions/close-bulk', { ids }).then((r) => r.data)

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

export const runMtfBias = (tickers: string[], is_crypto = false) =>
  api.post('/market-pulse/mtf-bias', { tickers, is_crypto }, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runAccurateStrategy = (payload: {
  tickers: string[]
  timeframe?: string
  min_confluence?: number
  rr_target?: number
  market?: string
}) => api.post('/market-pulse/accurate-strategy', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runPumpDumpBreakout = (payload: {
  tickers: string[]
  timeframe?: string
  market?: string
  initial_balance?: number
}) => api.post('/market-pulse/pump-dump-breakout', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchBigWhalePumpDump = () =>
  api.get('/market-pulse/big-whale-pump-dump', { timeout: MP_TIMEOUT }).then((r) => r.data)

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
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
}) => api.post('/technical-analysis/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchStrategyLabSections = () =>
  api.get('/strategy-lab/sections').then((r) => r.data)

export const fetchStrategyLabPresets = (market?: string, assetClass?: string) =>
  api.get('/strategy-lab/presets', {
    params: {
      ...(market ? { market } : {}),
      ...(assetClass ? { asset_class: assetClass } : {}),
    },
  }).then((r) => r.data)

export const runStrategyLabBacktest = (payload: Record<string, unknown>) =>
  api.post('/strategy-lab/backtest', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runStrategyLabMultiCombo = (payload: Record<string, unknown>) =>
  api.post('/strategy-lab/multi-combo', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runStrategyLabScreener = (payload: Record<string, unknown>) =>
  api.post('/strategy-lab/screener', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export interface CustomStrategy {
  id: number
  name: string
  market: string
  asset_class: string
  description: string | null
  timeframe: string
  indicators: Array<Record<string, unknown>>
  entry_rules: Array<Record<string, unknown>>
  exit_rules: Array<Record<string, unknown>>
  entry_mode: 'AND' | 'OR'
  exit_mode: 'AND' | 'OR'
  direction_mode: 'long_only' | 'short_only' | 'long_short'
  position_sizing: 'pct_of_capital' | 'risk_pct'
  capital_allocation_pct: number
  risk_pct: number
  sl_pct: number
  tp_pct: number
  source: 'manual' | 'ai'
  created_at: string | null
  updated_at: string | null
}

export const fetchCustomStrategies = (market?: string) =>
  api.get<{ strategies: CustomStrategy[] }>('/strategy-lab/custom-strategies', { params: market ? { market } : undefined }).then((r) => r.data)

export const createCustomStrategy = (payload: Record<string, unknown>) =>
  api.post<CustomStrategy>('/strategy-lab/custom-strategies', payload).then((r) => r.data)

export const updateCustomStrategy = (id: number, payload: Record<string, unknown>) =>
  api.patch<CustomStrategy>(`/strategy-lab/custom-strategies/${id}`, payload).then((r) => r.data)

export const deleteCustomStrategy = (id: number) =>
  api.delete(`/strategy-lab/custom-strategies/${id}`).then((r) => r.data)

export interface AIGeneratedStrategy {
  name: string
  description: string
  recommended_timeframe: string
  recommended_sl: number | null
  recommended_tp: number | null
  direction_mode: 'long_only' | 'short_only' | 'long_short'
  indicators: Array<Record<string, unknown>>
  entry_rules: Array<Record<string, unknown>>
  exit_rules: Array<Record<string, unknown>>
  entry_mode: 'AND' | 'OR'
  exit_mode: 'AND' | 'OR'
  provider: string
  model: string
}

export const aiGenerateStrategy = (payload: { text: string; market: string; asset_class: string; strategy_name?: string }) =>
  api.post<AIGeneratedStrategy>('/strategy-lab/ai-generate', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchLeaderboardCatalog = () =>
  api.get('/strategy-lab/leaderboard/catalog').then((r) => r.data)

export const startLeaderboardJob = (payload: {
  tickers: string[]
  timeframes?: string[]
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
  strategy_ids?: string[] | null
  bars?: number
  forward_bars?: number
}) => api.post('/strategy-lab/leaderboard/start', payload).then((r) => r.data)

export const fetchLeaderboardJob = (jobId: string) =>
  api.get(`/strategy-lab/leaderboard/jobs/${jobId}`).then((r) => r.data)

export const saveLeaderboardReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/strategy-lab/leaderboard/reports', payload).then((r) => r.data)

export const fetchLeaderboardReports = () =>
  api.get('/strategy-lab/leaderboard/reports').then((r) => r.data)

export const fetchLeaderboardReport = (reportId: number) =>
  api.get(`/strategy-lab/leaderboard/reports/${reportId}`).then((r) => r.data)

export const deleteLeaderboardReport = (reportId: number) =>
  api.delete(`/strategy-lab/leaderboard/reports/${reportId}`).then((r) => r.data)

export const runSeasonalityAnalyze = (payload: {
  tickers: string[]
  years?: number
  asset_class?: 'india' | 'us' | 'crypto' | 'commodity'
}) => api.post('/seasonality/analyze', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

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

export const fetchMarketMarquee = () =>
  api.get<{ quotes: Array<{
    id: string
    label: string
    symbol: string
    market: string
    price: number | null
    change_pct: number | null
    is_live: boolean
  }>; refresh_seconds: number }>('/market/marquee', { timeout: 25_000 }).then((r) => r.data)

export const fetchAlertNotifyConfig = () =>
  api.get('/alerts/notify-config').then((r) => r.data)

export const saveAlertNotifyConfig = (payload: Record<string, unknown>) =>
  api.put('/alerts/notify-config', payload).then((r) => r.data)

export const fetchAlertSchedules = () =>
  api.get('/alerts/schedules').then((r) => r.data)

export const fetchAlertScheduleCatalog = () =>
  api.get('/alerts/schedule-catalog').then((r) => r.data as AlertScheduleCatalog)

export type AlertScheduleCatalogItem = {
  id: string
  raw_id: string
  label: string
  runnable: boolean
  prefix: string
}

export type AlertScheduleCatalogGroup = {
  id: string
  label: string
  items?: AlertScheduleCatalogItem[]
  subgroups?: Array<{ id: string; label: string; items: AlertScheduleCatalogItem[] }>
}

export type AlertScheduleCatalog = {
  groups: AlertScheduleCatalogGroup[]
  count: number
  runnable_count: number
  runnable_prefixes: string[]
}

export const createAlertSchedule = (payload: Record<string, unknown>) =>
  api.post('/alerts/schedules', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const updateAlertSchedule = (id: number, payload: Record<string, unknown>) =>
  api.patch(`/alerts/schedules/${id}`, payload).then((r) => r.data)

export const deleteAlertSchedule = (id: number) =>
  api.delete(`/alerts/schedules/${id}`).then((r) => r.data)

export const enableAlertSchedule = (id: number, enabled: boolean) =>
  api.post(`/alerts/schedules/${id}/enable`, null, { params: { enabled } }).then((r) => r.data)

export const runAlertSchedule = (id: number, force = true) =>
  api.post(`/alerts/schedules/${id}/run`, null, { params: { force }, timeout: MP_TIMEOUT }).then((r) => r.data)

export const runDueAlertSchedules = () =>
  api.post('/alerts/schedules/run-due', null, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchAlertScheduleHits = (params?: { schedule_id?: number; limit?: number }) =>
  api.get('/alerts/schedule-hits', { params }).then((r) => r.data)

export const deleteAlertScheduleHit = (id: number) =>
  api.delete(`/alerts/schedule-hits/${id}`).then((r) => r.data)

export const deleteAlertScheduleHits = (payload: { ids?: number[]; delete_all?: boolean; schedule_id?: number }) =>
  api.post('/alerts/schedule-hits/delete', payload).then((r) => r.data)

export interface TradeCandidate {
  id: number
  name: string
  asset_class: 'india' | 'us' | 'crypto' | 'commodity'
  ticker: string
  timeframe: string
  strategies: string[]
  enabled: boolean
  last_checked_at: string | null
  created_at: string | null
}

export interface TradeCandidateCheckResult {
  candidate_id: number
  name: string
  ticker: string
  timeframe: string
  asset_class: string
  results: Array<{
    strategy_id: string
    strategy_label: string
    action: 'BUY' | 'SELL' | 'HOLD'
    confidence_pct: number
    sl_pct: number
    tp_pct: number
    price: number
    rationale: string
    timestamp: string
  }>
  hits_created: number
  checked_at: string
}

export interface TradeCandidateHit {
  id: number
  candidate_id: number
  candidate_name: string
  ticker: string
  timeframe: string
  asset_class: string
  strategy_id: string
  strategy_label: string
  verdict: 'BUY' | 'SELL'
  confidence_pct: number
  price: number | null
  rationale: string
  bar_asof: string
  created_at: string | null
}

export const fetchTradeCandidates = () =>
  api.get<{ candidates: TradeCandidate[] }>('/trade-candidates').then((r) => r.data)

export const createTradeCandidate = (payload: {
  name?: string
  asset_class: string
  ticker: string
  timeframe: string
  strategies: string[]
  enabled?: boolean
}) => api.post<TradeCandidate>('/trade-candidates', payload).then((r) => r.data)

export const updateTradeCandidate = (id: number, payload: Record<string, unknown>) =>
  api.patch<TradeCandidate>(`/trade-candidates/${id}`, payload).then((r) => r.data)

export const deleteTradeCandidate = (id: number) =>
  api.delete(`/trade-candidates/${id}`).then((r) => r.data)

export const checkTradeCandidate = (id: number) =>
  api.post<TradeCandidateCheckResult>(`/trade-candidates/${id}/check`, null, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchTradeCandidateHits = (params?: { candidate_id?: number; limit?: number }) =>
  api.get<{ hits: TradeCandidateHit[] }>('/trade-candidates/hits', { params }).then((r) => r.data)

export const deleteTradeCandidateHit = (id: number) =>
  api.delete(`/trade-candidates/hits/${id}`).then((r) => r.data)

export const deleteTradeCandidateHits = (payload: { ids?: number[]; delete_all?: boolean; candidate_id?: number }) =>
  api.post('/trade-candidates/hits/delete', payload).then((r) => r.data)

export interface TradingHubSection {
  id: string
  label: string
  description: string
  /** Optional extended documentation (markdown-ish text) shown in a collapsible panel. */
  guide?: string | null
  config_options: Record<string, {
    type: string
    label: string
    choices?: Array<{ value: string; label: string }>
    default?: string | number
    min?: number
    max?: number
    step?: number
  }>
  /** When set, scan ignores the ticker picker and always uses this India-index list. */
  fixed_universe?: string[] | null
  fixed_universe_label?: string | null
  /** When set, this is a multi-strategy/multi-timeframe section (e.g. Swing 5
   * Strategies) rendered by its own dedicated panel instead of the generic one. */
  multi_strategy?: boolean
  strategy_keys?: string[]
  strategy_labels?: Record<string, string>
  timeframe_options?: string[]
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

export const startIntraHedgingJob = (payload: {
  tickers: string[]
  asset_class?: string
  config?: Record<string, unknown>
  run_in_background?: boolean
  report_name?: string
}) => api.post('/trading-hubs/intra-hedging/start', payload).then((r) => r.data)

export const fetchIntraHedgingJobs = (status?: string) =>
  api.get('/trading-hubs/intra-hedging/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchIntraHedgingJob = (jobId: string) =>
  api.get(`/trading-hubs/intra-hedging/jobs/${jobId}`).then((r) => r.data)

export const saveIntraHedgingReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/trading-hubs/intra-hedging/reports', payload).then((r) => r.data)

export const fetchIntraHedgingReports = () =>
  api.get('/trading-hubs/intra-hedging/reports').then((r) => r.data)

export const fetchIntraHedgingReport = (reportId: number) =>
  api.get(`/trading-hubs/intra-hedging/reports/${reportId}`).then((r) => r.data)

export const deleteIntraHedgingReport = (reportId: number) =>
  api.delete(`/trading-hubs/intra-hedging/reports/${reportId}`).then((r) => r.data)

export interface SRTradeSetup {
  verdict: string | null
  direction: string | null
  take_trade: boolean
  confidence_pct: number | null
  sl_pct: number | null
  tp_pct: number | null
  hold_duration: string | null
  htf: string
  ltf: string
  confluence_notes: string[]
}

export interface SRBreakoutEstimate {
  level: number
  probability_pct: number
  distance_pct: number
  touches_recent: number
  projected_move_pct: number | null
}

export interface SRCandlestickPattern {
  name: string
  direction: 'bullish' | 'bearish' | 'neutral'
  bars_ago: number
  note: string
}

export interface SRChartPattern {
  name: string
  direction: 'bullish' | 'bearish'
  level: number
  note: string
}

export interface SRDivergence {
  name: string
  direction: 'bullish' | 'bearish'
  note: string
}

export interface SRBollingerCheck {
  signal: 'bullish' | 'bearish' | 'none'
  price: number
  mean: number
  upper: number
  lower: number
  percent_b: number
  note: string
}

export interface SRFibonacciLevel {
  ratio: number
  price: number
}

export interface SRFibonacci {
  trend: 'uptrend' | 'downtrend'
  swing_low: number
  swing_high: number
  levels: SRFibonacciLevel[]
  nearest_level: SRFibonacciLevel
  at_key_level: boolean
}

export interface SRZone {
  top: number
  bottom: number
  type: 'demand' | 'supply' | 'bullish' | 'bearish'
  origin_time: string
  mitigated: boolean
}

export interface SRChartResponse {
  ticker: string
  timeframe: string
  chart_data: Array<{ time: string; open: number; high: number; low: number; close: number; volume: number | null }>
  support_zone: [number, number] | null
  resistance_zone: [number, number] | null
  trendlines: Array<{ type: 'ascending' | 'descending'; points: Array<{ time: string; price: number }> }>
  emas: Record<string, Array<{ time: string; value: number }>>
  rsi: Array<{ time: string; value: number }> | null
  trade_setup: SRTradeSetup | null
  breakout: SRBreakoutEstimate | null
  breakdown: SRBreakoutEstimate | null
  candlestick_patterns: SRCandlestickPattern[]
  chart_patterns: SRChartPattern[]
  divergences: SRDivergence[]
  bollinger: SRBollingerCheck | null
  fibonacci: SRFibonacci | null
  supply_demand_zones: SRZone[]
  order_blocks: SRZone[]
  include_volume: boolean
  summary: string[]
}

export const fetchSupportResistanceChart = (payload: {
  ticker: string
  asset_class: string
  timeframe: string
  ltf?: string | null
  start_date?: string | null
  end_date?: string | null
  include_volume?: boolean
  ema_periods?: number[]
  include_rsi?: boolean
  include_fibonacci?: boolean
  include_supply_demand?: boolean
  include_order_blocks?: boolean
}) => api.post<SRChartResponse>('/trading-hubs/support-resistance/chart', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export interface BramhastraLevel {
  price: number
  label: string
  color?: string
}

export interface BramhastraChartResponse {
  ticker: string
  session_date: string
  is_today: boolean
  timeframe: string
  chart_data: Array<{ time: string; open: number; high: number; low: number; close: number; volume: number | null }>
  support_zone: [number, number] | null
  resistance_zone: [number, number] | null
  levels: BramhastraLevel[]
  last_close: number
  phase: string
  direction: string | null
  range_pct: number | null
  observation_start: string
  observation_end: string
  session_close: string
  tz: string
}

export const fetchBramhastraChart = (payload: {
  ticker: string
  asset_class: string
  config?: Record<string, unknown>
}) => api.post<BramhastraChartResponse>('/trading-hubs/bramhastra/chart', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runSwing5Scan = (payload: {
  tickers: string[]
  timeframes: string[]
  strategies: string[]
  asset_class?: string
  config?: Record<string, unknown>
}) => api.post('/trading-hubs/swing-5/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchEtfTaUniverse = (assetClass = 'india') =>
  api.get<{ asset_class: string; currency: string; presets: Record<string, string[]>; default_symbols: string[]; shop_39: string[]; master_backup: string[] }>(
    '/etf-ta/universe',
    { params: { asset_class: assetClass }, timeout: MP_TIMEOUT },
  ).then((r) => r.data)

export const scanEtfTaStf = (payload: { symbols?: string[]; exchange?: string; asset_class?: string }) =>
  api.post('/etf-ta/stf-shop/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const recommendEtfTaStf = (payload: Record<string, unknown>) =>
  api.post('/etf-ta/stf-shop/recommend', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export interface EtfShopConfig {
  asset_class: string
  currency: string
  deposited_capital: number
  growth_amount: number
  dividend_withdrawn: number
  shop_start_date: string | null
  preset: string
  custom_symbols: string | null
  exchange: string
  sell_mode: 'combined' | 'percentage' | 'absolute'
  profit_target_pct: number
  profit_target_inr: number
  min_profit_inr: number
  slots_divisor: number
  prefer_sip: boolean
  averaging_trigger_pct: number
  sip_locked_symbols: string[]
  notify_telegram: boolean
  notify_email: boolean
}

export interface EtfShopLot {
  id: number
  slot_id: string
  asset_class: string
  symbol: string
  purchase_price: number
  purchase_date: string
  amount: number
  quantity: number
  lot_type: string
  status: 'open' | 'closed'
  closed_date: string | null
  sale_price: number | null
  sale_amount: number | null
  gross_profit: number | null
  net_profit: number | null
  // Live-enriched fields, present only on open lots (populated by GET /etf-ta/stf-shop/portfolio)
  current_price?: number | null
  profit_since_bought_pct?: number | null
  profit_since_bought_inr?: number | null
  eligible_for_profit_booking?: boolean
  profit_booking_reason?: string | null
  averaging_suggested?: boolean
  averaging_fall_from_last_buy_pct?: number | null
  averaging_amount?: number | null
  averaging_reason?: string | null
}

export const fetchEtfShopPortfolio = (assetClass = 'india') =>
  api.get<{ config: EtfShopConfig; lots: EtfShopLot[] }>('/etf-ta/stf-shop/portfolio', {
    params: { asset_class: assetClass }, timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const updateEtfShopConfig = (payload: Partial<EtfShopConfig> & { asset_class: string }) =>
  api.put<EtfShopConfig>('/etf-ta/stf-shop/config', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const addEtfShopLot = (payload: { symbol: string; price: number; amount: number; lot_type?: string; purchase_date?: string; asset_class?: string }) =>
  api.post<EtfShopLot>('/etf-ta/stf-shop/lots', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const closeEtfShopLot = (lotId: number, payload: { sale_price: number; sale_date?: string; dividend_pct?: number }) =>
  api.post(`/etf-ta/stf-shop/lots/${lotId}/close`, payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runEtfShopDaily = (assetClass = 'india') =>
  api.post('/etf-ta/stf-shop/daily', {}, { params: { asset_class: assetClass }, timeout: MP_TIMEOUT }).then((r) => r.data)

export type AutoTradeAssetClass = 'india' | 'us' | 'crypto' | 'commodity'
export type AutoTradeStyle = 'scalping' | 'intraday' | 'swing' | 'investing'
export type AutoTradeDirection = 'both' | 'long_only' | 'short_only'

export interface AutoTradeSetup {
  id: number
  name: string
  asset_class: AutoTradeAssetClass
  style: AutoTradeStyle
  direction: AutoTradeDirection
  enabled: boolean
  interval_minutes: number
  universe_cap: number
  top_n: number
  last_run_at: string | null
  next_run_at: string | null
  last_status: string | null
}

export interface AutoTradeSuggestion {
  id: number
  setup_id: number
  batch_id: string
  asset_class: AutoTradeAssetClass
  style: AutoTradeStyle
  ticker: string
  action: 'BUY' | 'SELL' | 'WAIT'
  confidence_pct: number
  grade: 'A' | 'B' | 'C'
  entry_price: number | null
  sl_pct: number | null
  tp_pct: number | null
  stop_price: number | null
  target_price: number | null
  reasons: string[]
  plain_english: string
  rank: number
  created_at: string
}

export const fetchAutoTradeSetups = () =>
  api.get<{ setups: AutoTradeSetup[] }>('/suggestions/setups', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const createAutoTradeSetup = (payload: {
  name: string
  asset_class: AutoTradeAssetClass
  style: AutoTradeStyle
  direction?: AutoTradeDirection
  interval_minutes?: number
  universe_cap?: number
  top_n?: number
}) => api.post<AutoTradeSetup>('/suggestions/setups', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const updateAutoTradeSetup = (
  setupId: number,
  payload: { name?: string; direction?: AutoTradeDirection; interval_minutes?: number; universe_cap?: number; top_n?: number },
) => api.patch<AutoTradeSetup>(`/suggestions/setups/${setupId}`, payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const deleteAutoTradeSetup = (setupId: number) =>
  api.delete(`/suggestions/setups/${setupId}`, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const startAutoTradeSetup = (setupId: number) =>
  api.post<AutoTradeSetup>(`/suggestions/setups/${setupId}/start`, {}, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const stopAutoTradeSetup = (setupId: number) =>
  api.post<AutoTradeSetup>(`/suggestions/setups/${setupId}/stop`, {}, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runAutoTradeSetupNow = (setupId: number) =>
  api.post(`/suggestions/setups/${setupId}/run-now`, {}, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchAutoTradeSuggestions = (params?: { setup_id?: number; asset_class?: string; style?: string }) =>
  api
    .get<{ suggestions: AutoTradeSuggestion[] }>('/suggestions', { params, timeout: MP_TIMEOUT })
    .then((r) => r.data)

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
  notes?: string | null
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
  payload: { ticker: string; display_name?: string; added_price?: number | null; notes?: string },
) => api.post<WatchlistItemInfo>(`/watchlists/${watchlistId}/items`, payload).then((r) => r.data)

export const updateWatchlistItem = (
  watchlistId: number,
  itemId: number,
  payload: { display_name?: string; notes?: string },
) => api.patch<WatchlistItemInfo>(`/watchlists/${watchlistId}/items/${itemId}`, payload).then((r) => r.data)

export const removeWatchlistItem = (watchlistId: number, itemId: number) =>
  api.delete(`/watchlists/${watchlistId}/items/${itemId}`).then((r) => r.data)

// Todos
export type TodoStatus = 'pending' | 'done'

export interface Todo {
  id: number
  title: string
  notes: string | null
  status: TodoStatus
  created_at: string
  updated_at: string
}

export const fetchTodos = (params?: { search?: string; status?: TodoStatus }) =>
  api.get<{ todos: Todo[] }>('/todos', { params }).then((r) => r.data)

export const createTodo = (payload: { title: string; notes?: string }) =>
  api.post<Todo>('/todos', payload).then((r) => r.data)

export const updateTodo = (id: number, payload: { title?: string; notes?: string; status?: TodoStatus }) =>
  api.patch<Todo>(`/todos/${id}`, payload).then((r) => r.data)

export const deleteTodo = (id: number) =>
  api.delete(`/todos/${id}`).then((r) => r.data)

// Command Center — standalone tools
export const fetchGlobalMarketMood = () =>
  api.get('/command-center/global-market-mood', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runMomentumScan = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/momentum', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runEmaPositionScan = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/ema-position', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runMtfTrendStrength = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/mtf-trend-strength', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export interface MarketMoversOption { label: string; value: string }

export const fetchMarketMoversOptions = (asset_class: string) =>
  api.get<{ indices: MarketMoversOption[]; timeframes: MarketMoversOption[] }>(
    '/command-center/market-movers/options', { params: { asset_class } },
  ).then((r) => r.data)

export const runMarketMovers = (payload: { asset_class: string; index: string; timeframe: string }) =>
  api.post('/command-center/market-movers', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetup = (payload: { tickers: string[]; asset_class: string; timeframes?: string[]; exchange?: string }) =>
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

export const runWeakStrong = (payload: { tickers: string[]; asset_class: string; timeframes?: string[]; exchange?: string }) =>
  api.post('/command-center/weak-strong', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runSma20200 = (payload: {
  tickers: string[]
  asset_class: string
  timeframes?: string[]
  exchange?: string
  fast_period?: number
  slow_period?: number
  rr_ratio?: number
  sl_buffer_pct?: number
  take_confidence_threshold?: number
}) => api.post('/command-center/sma-20-200', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupCopyTrade = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/copy-trade', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTradeSetupSma20200 = (payload: TradeSetupDrillPayload) =>
  api.post('/command-center/trade-setup/sma-20-200', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runCopyTrade = (payload: { tickers: string[]; asset_class: string }) =>
  api.post('/command-center/copy-trade', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runTakeTrade = (payload: { tickers: string[]; asset_class: string; timeframes?: string[] }) =>
  api.post('/command-center/take-trade', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOneClick = (payload: { style: 'intraday' | 'scalping' | 'swing'; tickers: string[]; asset_class: string }) =>
  api.post('/command-center/one-click', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runFundamentalAnalysis = (payload: { tickers: string[]; asset_class: string }) =>
  api.post('/command-center/fundamental-analysis', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runIndiaFiiDiiHoldings = (payload: {
  tickers: string[]
  from_date: string
  to_date: string
}) =>
  api.post('/command-center/india-fii-dii-holdings', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const startIndiaFiiDiiHoldingsJob = (payload: {
  tickers: string[]
  from_date: string
  to_date: string
  run_in_background?: boolean
  report_name?: string
}) => api.post('/command-center/india-fii-dii-holdings/start', payload).then((r) => r.data)

export const fetchIndiaFiiDiiHoldingsJobs = (status?: string) =>
  api.get('/command-center/india-fii-dii-holdings/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchIndiaFiiDiiHoldingsJob = (jobId: string) =>
  api.get(`/command-center/india-fii-dii-holdings/jobs/${jobId}`).then((r) => r.data)

export const saveIndiaFiiDiiHoldingsReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/command-center/india-fii-dii-holdings/reports', payload).then((r) => r.data)

export const fetchIndiaFiiDiiHoldingsReports = () =>
  api.get('/command-center/india-fii-dii-holdings/reports').then((r) => r.data)

export const fetchIndiaFiiDiiHoldingsReport = (reportId: number) =>
  api.get(`/command-center/india-fii-dii-holdings/reports/${reportId}`).then((r) => r.data)

export const deleteIndiaFiiDiiHoldingsReport = (reportId: number) =>
  api.delete(`/command-center/india-fii-dii-holdings/reports/${reportId}`).then((r) => r.data)

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

export const fetchIndiaMarketHeatmapIndices = (assetClass: string = 'india') =>
  api.get<{ index_names: string[] }>('/command-center/india-market-heatmap/indices', {
    params: { asset_class: assetClass }, timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const runIndiaMarketHeatmap = (payload: { index_name: string; asset_class?: string; tickers?: string[] }) =>
  api.post('/command-center/india-market-heatmap', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchAdvanceDeclineGraphIndices = (asset_class: string = 'india') =>
  api.get<{ asset_class: string; index_names: string[] }>('/command-center/advance-decline-graph/indices', {
    params: { asset_class },
    timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const runAdvanceDeclineGraph = (payload: {
  asset_class?: 'india' | 'us' | 'crypto'
  index_name: string
  from_date: string
  to_date: string
  timeframe?: string
  session_date?: string
  as_of_time?: string
  exchange?: string
}) => api.post('/command-center/advance-decline-graph', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchComparativeStrengthPresets = (asset_class: string) =>
  api.get<{ asset_class: string; presets: Array<{ label: string; symbol: string }> }>(
    '/command-center/comparative-strength/presets',
    { params: { asset_class }, timeout: MP_TIMEOUT },
  ).then((r) => r.data)

export const runComparativeStrength = (payload: {
  asset_class: 'india' | 'us' | 'crypto' | 'commodity'
  base_symbol: string
  compare_symbols: string[]
  timeframe?: string
  lookback_bars?: number
  exchange?: string
}) => api.post('/command-center/comparative-strength', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runDayBias = (payload: { ticker: string; asset_class: string; timeframe: string; exchange?: string }) =>
  api.post('/command-center/day-bias', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionChain = (payload: { symbol: string; is_index: boolean }) =>
  api.post('/command-center/option-chain', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionShortLong = (payload: { symbols: string[]; is_index: boolean; expiries?: string[] }) =>
  api.post('/command-center/option-short-long', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchOptionShortLongExpiries = (symbol: string, isIndex: boolean) =>
  api.get<{ expiries: string[] }>('/command-center/option-short-long/expiries', {
    params: { symbol, is_index: isIndex },
  }).then((r) => r.data)

export const runQuickAnalyzer = (payload: {
  tickers: string[]
  timeframes: string[]
  asset_class: 'india' | 'us' | 'crypto'
  from_date?: string
  to_date?: string
  include_fundamentals?: boolean
  include_option_chain?: boolean
}) => api.post('/command-center/quick-analyzer', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export type MutualFundAmc = {
  ID?: number
  Id?: number
  Name: string
  AUM?: number | null
  SchemeCount?: number | null
  AUMDate?: string | null
  Slug?: string | null
}

export type MutualFundScheme = {
  ID?: number
  Id?: number
  Name: string
  Description?: string | null
  NAV?: number | null
  Return?: number | null
  AUM?: number | null
}

export const fetchMutualFundAmcs = () =>
  api.get<{ amcs: MutualFundAmc[] }>('/command-center/mutual-fund/amcs', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchMutualFundSchemes = (amcId: number) =>
  api.get<{ schemes: MutualFundScheme[] }>('/command-center/mutual-fund/schemes', {
    params: { amc_id: amcId },
    timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const runMutualFundHoldingsChange = (payload: {
  scheme_ids: number[]
  scheme_names: Record<string, string>
  from_date: string
  to_date: string
}) => api.post('/command-center/mutual-fund/holdings', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const startMutualFundHoldingsJob = (payload: {
  scheme_ids: number[]
  scheme_names: Record<string, string>
  from_date: string
  to_date: string
  run_in_background?: boolean
  report_name?: string
}) => api.post('/command-center/mutual-fund/holdings/start', payload).then((r) => r.data)

export const fetchMutualFundHoldingsJobs = (status?: string) =>
  api.get('/command-center/mutual-fund/holdings/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchMutualFundHoldingsJob = (jobId: string) =>
  api.get(`/command-center/mutual-fund/holdings/jobs/${jobId}`).then((r) => r.data)

export const saveMutualFundHoldingsReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/command-center/mutual-fund/holdings/reports', payload).then((r) => r.data)

export const fetchMutualFundHoldingsReports = () =>
  api.get('/command-center/mutual-fund/holdings/reports').then((r) => r.data)

export const fetchMutualFundHoldingsReport = (reportId: number) =>
  api.get(`/command-center/mutual-fund/holdings/reports/${reportId}`).then((r) => r.data)

export const deleteMutualFundHoldingsReport = (reportId: number) =>
  api.delete(`/command-center/mutual-fund/holdings/reports/${reportId}`).then((r) => r.data)

export type BestMfOption = { value: number; label: string }

export const fetchBestMfOptions = () =>
  api.get<{
    asset_types: BestMfOption[]
    category_hints: Record<string, string[]>
    return_periods: BestMfOption[]
  }>('/best-mf/options').then((r) => r.data)

export const runBestMf = (payload: {
  amc_ids: number[]
  asset_type_id: number
  category_filter?: string
  rank_period?: number
  top_n?: number
}) => api.post('/best-mf/run', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const startBestMfJob = (payload: {
  amc_ids: number[]
  asset_type_id: number
  category_filter?: string
  rank_period?: number
  top_n?: number
  run_in_background?: boolean
  report_name?: string
}) => api.post('/best-mf/start', payload).then((r) => r.data)

export const fetchBestMfJobs = (status?: string) =>
  api.get('/best-mf/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchBestMfJob = (jobId: string) =>
  api.get(`/best-mf/jobs/${jobId}`).then((r) => r.data)

export const saveBestMfReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/best-mf/reports', payload).then((r) => r.data)

export const fetchBestMfReports = () =>
  api.get('/best-mf/reports').then((r) => r.data)

export const fetchBestMfReport = (reportId: number) =>
  api.get(`/best-mf/reports/${reportId}`).then((r) => r.data)

export const deleteBestMfReport = (reportId: number) =>
  api.delete(`/best-mf/reports/${reportId}`).then((r) => r.data)

export type EtfCatalogItem = {
  symbol: string
  name: string
  category: string
}

export type EtfIssuer = {
  ID: number
  Name: string
  SchemeCount?: number | null
  path?: string | null
}

export type EtfIssuerScheme = {
  ID: string
  Name: string
  Description?: string | null
  NAV?: number | null
  Return?: number | null
  AUM?: number | null
  symbol?: string
}

export const fetchEtfHoldingsAmcs = () =>
  api.get<{ amcs: MutualFundAmc[] }>('/command-center/etf/amcs', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchEtfHoldingsSchemes = (amcId: number) =>
  api.get<{ schemes: MutualFundScheme[] }>('/command-center/etf/schemes', {
    params: { amc_id: amcId },
    timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const fetchEtfHoldingsIssuers = (market: 'us' | 'crypto') =>
  api.get<{ market: string; issuers: EtfIssuer[] }>('/command-center/etf/catalog', {
    params: { market },
    timeout: MP_TIMEOUT,
  }).then((r) => r.data)

/** @deprecated use fetchEtfHoldingsIssuers */
export const fetchEtfHoldingsCatalog = fetchEtfHoldingsIssuers

export const fetchEtfIssuerSchemes = (market: 'us' | 'crypto', issuerName: string) =>
  api.get<{ market: string; issuer: string; schemes: EtfIssuerScheme[] }>(
    '/command-center/etf/issuer-schemes',
    { params: { market, issuer_name: issuerName }, timeout: MP_TIMEOUT },
  ).then((r) => r.data)

export const runEtfIndiaHoldingsChange = (payload: {
  scheme_ids: number[]
  scheme_names: Record<string, string>
  from_date: string
  to_date: string
}) => api.post('/command-center/etf/holdings/india', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runEtfYahooHoldingsChange = (payload: {
  market: 'us' | 'crypto'
  symbols: string[]
  symbol_names: Record<string, string>
  from_date: string
  to_date: string
}) => api.post('/command-center/etf/holdings/yahoo', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export type EtfHoldingsJobStartResponse = { job_id: string; status: string; name?: string | null; auto_save: boolean }

export const startEtfIndiaHoldingsJob = (payload: {
  scheme_ids: number[]
  scheme_names: Record<string, string>
  from_date: string
  to_date: string
  run_in_background?: boolean
  report_name?: string
}) => api.post<EtfHoldingsJobStartResponse>('/command-center/etf/holdings/india/start', payload).then((r) => r.data)

export const startEtfYahooHoldingsJob = (payload: {
  market: 'us' | 'crypto'
  symbols: string[]
  symbol_names: Record<string, string>
  from_date: string
  to_date: string
  run_in_background?: boolean
  report_name?: string
}) => api.post<EtfHoldingsJobStartResponse>('/command-center/etf/holdings/yahoo/start', payload).then((r) => r.data)

export const fetchEtfHoldingsJobs = (status?: string) =>
  api.get('/command-center/etf/holdings/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchEtfHoldingsJob = (jobId: string) =>
  api.get(`/command-center/etf/holdings/jobs/${jobId}`).then((r) => r.data)

export const saveEtfHoldingsReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/command-center/etf/holdings/reports', payload).then((r) => r.data)

export const fetchEtfHoldingsReports = () =>
  api.get('/command-center/etf/holdings/reports').then((r) => r.data)

export const fetchEtfHoldingsReport = (reportId: number) =>
  api.get(`/command-center/etf/holdings/reports/${reportId}`).then((r) => r.data)

export const deleteEtfHoldingsReport = (reportId: number) =>
  api.delete(`/command-center/etf/holdings/reports/${reportId}`).then((r) => r.data)

export type SmartMoneyTickerResult = {
  ticker: string
  found?: boolean
  signal: string
  bias: string
  summary: string
  overall_trend?: string
  avg_change_pct?: number
  schemes_increasing?: number
  schemes_decreasing?: number
  n_schemes?: number
  matched_stocks?: string[]
  sources?: string[]
  sector?: string
  stock?: string
  ai_context?: string
}

export type SmartMoneyActivityResult = {
  error?: string
  market?: string
  source?: string
  from_date?: string
  to_date?: string
  tickers?: string[]
  preferred_amcs?: Array<{ id: number; name: string }>
  notes?: string[]
  summary?: { tickers: number; found: number; bullish: number; bearish: number; wait: number }
  results?: SmartMoneyTickerResult[]
  ai_system_prompt?: string
  saved_report_id?: number
  saved_report_name?: string
}

export type SmartMoneyActivityRunPayload = {
  tickers: string[]
  asset_class: 'india' | 'us' | 'crypto'
  source: 'mutual_fund' | 'etf' | 'both'
  from_date: string
  to_date: string
  amc_ids?: number[]
  mf_scheme_ids?: number[]
  mf_scheme_names?: Record<number, string>
  etf_scheme_ids?: number[]
  etf_scheme_names?: Record<number, string>
  etf_symbols?: string[]
  etf_symbol_names?: Record<string, string>
}

export const runSmartMoneyActivity = (payload: SmartMoneyActivityRunPayload) =>
  api.post<SmartMoneyActivityResult>('/command-center/smart-money-activity', payload, {
    timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const startSmartMoneyActivityJob = (
  payload: SmartMoneyActivityRunPayload & { run_in_background?: boolean; report_name?: string },
) => api.post('/command-center/smart-money-activity/start', payload).then((r) => r.data)

export const fetchSmartMoneyActivityJobs = (status?: string) =>
  api.get('/command-center/smart-money-activity/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchSmartMoneyActivityJob = (jobId: string) =>
  api.get(`/command-center/smart-money-activity/jobs/${jobId}`).then((r) => r.data)

export const saveSmartMoneyActivityReport = (payload: {
  name: string
  tickers?: string[]
  from_date?: string
  to_date?: string
  payload: Record<string, unknown>
}) => api.post('/command-center/smart-money-activity/reports', payload).then((r) => r.data)

export const fetchSmartMoneyActivityReports = () =>
  api.get('/command-center/smart-money-activity/reports').then((r) => r.data)

export const fetchSmartMoneyActivityReport = (reportId: number) =>
  api.get(`/command-center/smart-money-activity/reports/${reportId}`).then((r) => r.data)

export const deleteSmartMoneyActivityReport = (reportId: number) =>
  api.delete(`/command-center/smart-money-activity/reports/${reportId}`).then((r) => r.data)

export const fetchDetectSectorRotationUniverse = (market: 'india' | 'us' | 'crypto' = 'india') =>
  api.get<{ market: string; sectors: string[] }>('/command-center/detect-sector-rotation/universe', {
    params: { market },
    timeout: MP_TIMEOUT,
  }).then((r) => r.data)

export const runDetectSectorRotation = (payload: {
  market: 'india' | 'us' | 'crypto'
  sectors?: string[]
  crs_sma_period?: number
  hma_length?: number
  pullback_months?: number
  pullback_mode?: 'months' | 'quarters'
}) => api.post('/command-center/detect-sector-rotation', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const fetchOptionsSections = () =>
  api.get<{ sections: Array<{ id: string; label: string }> }>('/options/sections', { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsDoubleCalendar = (payload: {
  tickers: string[]
  asset_class: 'india' | 'us' | 'crypto' | 'commodity'
  timeframes?: string[]
  exchange?: string
  short_dte?: number
  long_dte?: number
  otm_offset_pct?: number
  diagonal_widen_pct?: number
  take_profit_start?: number
  take_profit_max?: number
  stop_loss?: number
  vix_max_threshold?: number
  vol_percentile_max?: number
}) => api.post('/options/double-calendar', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsDoubleCalendarPnl = (payload: {
  net_debit: number
  current_mark: number
  stop_loss?: number
  take_profit_start?: number
  take_profit_max?: number
}) => api.post('/options/double-calendar/pnl', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsDeltaNeutral = (payload: {
  tickers: string[]
  asset_class: 'india' | 'us' | 'crypto' | 'commodity'
  timeframes?: string[]
  exchange?: string
  dte?: number
  short_delta_target?: number
  wing_width_pct?: number
  iron_fly?: boolean
  profit_target_pct?: number
  stop_loss_multiple?: number
  vix_max_threshold?: number
  vol_percentile_max?: number
  adx_trend_max?: number
}) => api.post('/options/delta-neutral', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsDeltaNeutralPnl = (payload: {
  net_credit: number
  current_cost_to_close: number
  profit_target_pct?: number
  stop_loss_multiple?: number
}) => api.post('/options/delta-neutral/pnl', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsHedging = (payload: {
  tickers: string[]
  asset_class: 'india' | 'us' | 'crypto' | 'commodity'
  exchange?: string
  dte?: number
  hedge_distance_pct?: number
  zone_timeframe?: string
  zone_fallback_timeframe?: string
  total_capital?: number
  profit_target_pct_of_capital?: number
  max_loss_pct_of_capital?: number
  max_adjustments_per_day?: number
}) => api.post('/options/hedging', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsHedgingPnl = (payload: {
  total_capital: number
  current_pnl: number
  profit_target_pct_of_capital?: number
  max_loss_pct_of_capital?: number
}) => api.post('/options/hedging/pnl', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsGokulChhabra = (payload?: {
  tickers?: string[]
  exchange?: string
  vwma_length?: number
  st_period?: number
  st_multiplier?: number
  session_start?: string
  session_end?: string
  pullback_tol_pct?: number
  min_rr?: number
  target_delta_min?: number
  target_delta_max?: number
}) => api.post('/options/gokul-chhabra', payload ?? {}, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsMarketPrediction = (payload?: {
  symbol?: string
  is_index?: boolean
  exchange?: string
  futures_price?: number
  fii_index_position_cut?: boolean
  further_analysis?: string[]
}) => api.post('/options/market-prediction', payload ?? {}, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runOptionsZeroToHero = (payload?: {
  tickers?: string[]
  exchange?: string
  execution_tf?: string
  sl_buffer_pct?: number
  max_pullback_candles?: number
  partial_book_rr?: number
  partial_book_pct?: number
  session_end?: string
}) => api.post('/options/zero-to-hero', payload ?? {}, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const startOptionsJob = (sectionId: string, payload: Record<string, unknown>) =>
  api.post(`/options/${sectionId}/start`, payload).then((r) => r.data)

export const fetchOptionsJobs = (sectionId: string, status?: string) =>
  api.get(`/options/${sectionId}/jobs`, { params: status ? { status } : {} }).then((r) => r.data)

export const fetchOptionsJob = (sectionId: string, jobId: string) =>
  api.get(`/options/${sectionId}/jobs/${jobId}`).then((r) => r.data)

export const saveOptionsReport = (sectionId: string, payload: { name: string; payload: Record<string, unknown> }) =>
  api.post(`/options/${sectionId}/reports`, payload).then((r) => r.data)

export const fetchOptionsReports = (sectionId: string) =>
  api.get(`/options/${sectionId}/reports`).then((r) => r.data)

export const fetchOptionsReport = (sectionId: string, reportId: number) =>
  api.get(`/options/${sectionId}/reports/${reportId}`).then((r) => r.data)

export const deleteOptionsReport = (sectionId: string, reportId: number) =>
  api.delete(`/options/${sectionId}/reports/${reportId}`).then((r) => r.data)

export const startAnalysisJob = (payload: Record<string, unknown> & { domain: string; section: string }) =>
  api.post('/analysis/start', payload).then((r) => r.data)

export const fetchAnalysisJobs = (domain: string, section: string, status?: string) =>
  api.get('/analysis/jobs', { params: { domain, section, ...(status ? { status } : {}) } }).then((r) => r.data)

export const fetchAnalysisJob = (jobId: string) =>
  api.get(`/analysis/jobs/${jobId}`).then((r) => r.data)

export const saveAnalysisReport = (domain: string, section: string, payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/analysis/reports', payload, { params: { domain, section } }).then((r) => r.data)

export const fetchAnalysisReports = (domain: string, section: string) =>
  api.get('/analysis/reports', { params: { domain, section } }).then((r) => r.data)

export const fetchAnalysisReport = (domain: string, section: string, reportId: number) =>
  api.get(`/analysis/reports/${reportId}`, { params: { domain, section } }).then((r) => r.data)

export const deleteAnalysisReport = (domain: string, section: string, reportId: number) =>
  api.delete(`/analysis/reports/${reportId}`, { params: { domain, section } }).then((r) => r.data)

export const runProTradeVolumeProfileCe = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  intraday_tf?: string
  daily_tf?: string
  num_bins?: number
  value_area_pct?: number
  compression_days?: number
  compression_threshold_pct?: number
  val_touch_tol_pct?: number
  lvn_threshold_pct?: number
}) => api.post('/pro-trade/volume-profile-ce', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradeVolumeProfilePoc = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  timeframe?: string
  lookback_bars?: number
  profile_bars?: number
  num_bins?: number
  cluster_vol_pct?: number
  breakout_buffer_pct?: number
}) => api.post('/pro-trade/volume-profile-poc', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradePaVolumeProfile = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  timeframe?: string
  lookback_bars?: number
  vp_lookback?: number
  num_bins?: number
  poc_tolerance_pct?: number
  breakout_buffer_pct?: number
}) => api.post('/pro-trade/pa-volume-profile', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradePaVpSmc = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  htf?: string
  ltf?: string
  lookback_bars?: number
  swing_window?: number
  vp_num_bins?: number
  vp_value_area_pct?: number
  zone_tolerance_pct?: number
  min_confluence_factors?: number
  rr_min?: number
}) => api.post('/pro-trade/pa-vp-smc', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradeVolumeSpreadNextCandle = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  timeframe?: string
  lookback_bars?: number
  vol_ma_period?: number
  ultra_vol_lookback?: number
  low_spread_factor?: number
  rr_ratio?: number
}) => api.post('/pro-trade/volume-spread-next-candle', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradeElliottWave = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  timeframe?: string
  lookback_bars?: number
  zigzag_pct?: number
  start_date?: string
  end_date?: string
}) => api.post('/pro-trade/elliott-wave', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradeFibonacciPro = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  timeframe?: string
  lookback_bars?: number
  fib_lookback?: number
  secondary_lookback?: number
  zone_tol_atr?: number
  min_rr?: number
  strategies?: string[]
  start_date?: string
  end_date?: string
}) => api.post('/pro-trade/fibonacci-pro', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradeBbMeanReversion = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  timeframes: string[]
  lookback_bars?: number
  bb_period?: number
  bb_std?: number
  er_hard_block?: number
  er_soft_ceiling?: number
  squeeze_pctile_floor?: number
  rsi_overbought?: number
  rsi_oversold?: number
  zone_tolerance_pct?: number
  min_rr?: number
  extra_checks?: string[]
}) => api.post('/pro-trade/bb-mean-reversion', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const runProTradeBtst = (payload: {
  tickers: string[]
  asset_class?: string
  exchange?: string
  lookback_bars?: number
  min_clv?: number
  min_volume_zscore?: number
  climax_volume_zscore?: number
  min_relative_strength_pct?: number
  sl_atr_mult?: number
  tp_atr_mult?: number
  min_rr?: number
  historical_lookback_days?: number
  check_oi_buildup?: boolean
  further_analysis?: string[]
}) => api.post('/pro-trade/btst', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)

export const startBtstJob = (payload: {
  tickers: string[]
  asset_class?: string
  config?: Record<string, unknown>
  run_in_background?: boolean
  report_name?: string
}) => api.post('/pro-trade/btst/start', payload).then((r) => r.data)

export const fetchBtstJobs = (status?: string) =>
  api.get('/pro-trade/btst/jobs', { params: status ? { status } : {} }).then((r) => r.data)

export const fetchBtstJob = (jobId: string) => api.get(`/pro-trade/btst/jobs/${jobId}`).then((r) => r.data)

export const saveBtstReport = (payload: { name: string; payload: Record<string, unknown> }) =>
  api.post('/pro-trade/btst/reports', payload).then((r) => r.data)

export const fetchBtstReports = () => api.get('/pro-trade/btst/reports').then((r) => r.data)

export const fetchBtstReport = (reportId: number) => api.get(`/pro-trade/btst/reports/${reportId}`).then((r) => r.data)

export const deleteBtstReport = (reportId: number) => api.delete(`/pro-trade/btst/reports/${reportId}`).then((r) => r.data)

/* ── Investing Agent (SuperInvesting) ─────────────────────────────── */

export type InvestingAgentStreamEvent =
  | { kind: 'status'; message?: string; type?: string }
  | { kind: 'conversation'; id: string; value?: string }
  | { kind: 'reasoning'; text: string }
  | { kind: 'tool'; type?: string; tool?: string; toolCallId?: string }
  | { kind: 'text'; text: string }
  | {
      kind: 'done'
      conversation_id: string
      answer: string
      reasoning?: string | null
      tools?: string[]
    }
  | { kind: 'error'; message: string; status_code?: number | null }

export const fetchInvestingAgentStatus = () =>
  api.get<{ token_set: boolean }>('/investing-agent/status').then((r) => r.data)

export const saveInvestingAgentToken = (token: string) =>
  api.put<{ token_set: boolean; message: string }>('/investing-agent/token', { token }).then((r) => r.data)

export const fetchInvestingAgentStockCard = (symbol: string) =>
  api.get(`/investing-agent/stock/card`, { params: { symbol } }).then((r) => r.data)

export const fetchInvestingAgentStockDetail = (symbol: string) =>
  api.post('/investing-agent/stock/detail', { symbol }).then((r) => r.data)

export const fetchInvestingAgentSearch = (query: string) =>
  api.get('/investing-agent/search', { params: { query, page: 1, limit: 20 } }).then((r) => r.data)

export const fetchInvestingAgentStarters = () =>
  api.get('/investing-agent/starters').then((r) => r.data)

/** Stream chat via fetch (axios does not expose SSE well). */
export async function streamInvestingAgentChat(
  message: string,
  onEvent: (event: InvestingAgentStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = authToken ?? localStorage.getItem('ist_auth_token')
  const res = await fetch('/api/v1/investing-agent/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message }),
    signal,
  })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  if (!res.body) throw new Error('No response stream')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const chunk of parts) {
      for (const line of chunk.split('\n')) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const payload = trimmed.slice(5).trim()
        if (!payload || payload === '[DONE]') continue
        try {
          onEvent(JSON.parse(payload) as InvestingAgentStreamEvent)
        } catch {
          /* skip malformed */
        }
      }
    }
  }
}
