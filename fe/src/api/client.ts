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
  recent_orders: Array<{
    id: number
    ticker: string
    side: string
    quantity: number
    price: number
    status: string
    strategy?: string
    created_at: string
  }>
}

export const fetchStrategies = () => api.get<StrategyInfo[]>('/strategies').then((r) => r.data)
export const fetchStrategyCategories = () =>
  api.get<StrategyCategoryInfo[]>('/strategies/categories').then((r) => r.data)
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
export const getSettings = () => api.get('/settings').then((r) => r.data)
export const updateSettings = (payload: Record<string, unknown>) => api.put('/settings', payload).then((r) => r.data)
export const testProvider = () => api.post('/settings/test-provider').then((r) => r.data)
export const getAccount = () => api.get<AccountSummary>('/paper/account').then((r) => r.data)
export const placeOrder = (payload: Record<string, unknown>) => api.post('/paper/orders', payload).then((r) => r.data)
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

export const runTickerInvestigation = (tickers: string[]) =>
  api.post('/market-pulse/ticker-investigation', { tickers }, { timeout: MP_TIMEOUT }).then((r) => r.data)

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
  config?: Record<string, unknown>
  run_backtest?: boolean
}) => api.post('/trading-hubs/scan', payload, { timeout: MP_TIMEOUT }).then((r) => r.data)
