import { useCallback, useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Activity, ArrowUpDown, BarChart3, BookOpen, CandlestickChart, Compass, Crosshair, FishingHook, Flame, Gauge, Globe2, Grid3x3, Landmark, LineChart, Link2, Newspaper, Package, PieChart, Radar, RefreshCw, Repeat, Rocket, Scale, Search, Shuffle, Sparkles, Sun, Target, TrendingDown, TrendingUp, Waves, Zap } from 'lucide-react'
import {
  apiErrorMessage,
  fetchCoinDcx24hVolatility,
  fetchCommandCenterSections,
  fetchFuturesIndices,
  fetchGiftNifty,
  fetchGlobalIndices,
  fetchGlobalMarketMood,
  fetchIndiaMarketHeatmapIndices,
  fetchInvestigationStrategyCatalog,
  fetchNseIndices,
  fetchOptionShortLongExpiries,
  fetchTickerSuggestions,
  fetchTomorrowOutlook,
  runBuySellAdvisor,
  runEmaPositionScan,
  runFundamentalAnalysis,
  runIndiaMarketHeatmap,
  runInvestigationWithStrategies,
  runDivergences,
  runMarketMovers,
  fetchMarketMoversOptions,
  runMegaAnalyser,
  runMegaSetupAdvisor,
  runMomentumScan,
  runMtfTrendStrength,
  runOneClick,
  runOptionChain,
  runOptionShortLong,
  runPatterns,
  runQuickAnalyzer,
  runRealBottom,
  runSma20200,
  runWeakStrong,
  runCopyTrade,
  runStopHunt,
  runTakeProfit,
  runTakeTrade,
  runTickerInvestigation,
  runTradeSetup,
  runUpgradeDowngradeScan,
} from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import {
  AssetClassTickerPicker,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { CommandCenterResults } from '../components/command-center/CommandCenterPanels'
import { WatchlistMarketProvider, type WatchlistMarket } from '../components/watchlist/WatchlistMarketContext'
import { MutualFundHoldingsPanel } from '../components/command-center/MutualFundHoldingsPanel'
import { EtfHoldingsPanel } from '../components/command-center/EtfHoldingsPanel'
import { IndiaFiiDiiHoldingsPanel } from '../components/command-center/IndiaFiiDiiHoldingsPanel'
import { AdvanceDeclineGraphPanel } from '../components/command-center/AdvanceDeclineGraphPanel'
import { ComparativeStrengthPanel } from '../components/command-center/ComparativeStrengthPanel'
import { SmartMoneyActivityPanel } from '../components/command-center/SmartMoneyActivityPanel'
import { DetectSectorRotationPanel } from '../components/command-center/DetectSectorRotationPanel'
import { PlaybookPanel } from '../components/command-center/PlaybookPanel'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../components/analysis/AnalysisBackground'
import { ChartsToggle } from '../components/pro-trade/ChartsToggle'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const TABS = [
  { id: 'playbook', label: 'Trading Playbook', icon: BookOpen },
  { id: 'tomorrow_outlook', label: 'Tomorrow Outlook', icon: Sun },
  { id: 'mega_analyser', label: 'Mega Analyser', icon: Radar },
  { id: 'buy_sell', label: 'Buy or Sell', icon: Compass },
  { id: 'investigation', label: 'Ticker Investigation', icon: Search },
  { id: 'global_market_mood', label: 'Global Market Mood', icon: Globe2 },
  { id: 'momentum', label: 'Momentum Scanner', icon: TrendingUp },
  { id: 'ema_position', label: 'EMA Position', icon: LineChart },
  { id: 'mtf_trend_strength', label: 'MTF Trend and Strength', icon: Gauge },
  { id: 'market_movers', label: 'Market Movers', icon: ArrowUpDown },
  { id: 'divergences', label: 'Divergences', icon: Shuffle },
  { id: 'candlestick_chart_patterns', label: 'Candlestick & Chart Patterns', icon: CandlestickChart },
  { id: 'stop_hunt', label: 'Stoploss Hunting', icon: FishingHook },
  { id: 'take_profit', label: 'Take Profit Targets', icon: Crosshair },
  { id: 'real_bottom', label: 'Real Bottom', icon: TrendingDown },
  { id: 'weak_strong', label: 'Weak / Strong', icon: Scale },
  { id: 'sma_20_200', label: '200SMA-20SMA — Bounce & Rejection', icon: Waves },
  { id: 'copy_trade', label: 'Copy Trade', icon: Repeat },
  { id: 'take_trade', label: 'Take Trade', icon: Rocket },
  { id: 'trade_setup', label: 'Trade Setup — Oversold/Overbought', icon: Target },
  { id: 'one_click_intraday', label: 'One-Click Intraday', icon: Zap },
  { id: 'one_click_scalping', label: 'One-Click Scalping', icon: Zap },
  { id: 'one_click_swing', label: 'One-Click Swing', icon: Zap },
  { id: 'fundamental_analysis', label: 'Fundamental Analysis', icon: BarChart3 },
  { id: 'india_fii_dii_holdings', label: 'India FII-DII Holding', icon: PieChart },
  { id: 'mutual_fund_holdings', label: 'Mutual Fund Holdings', icon: Landmark },
  { id: 'etf_holdings', label: 'ETF Holdings', icon: Package },
  { id: 'smart_money_activity', label: 'Check Smart Money Activity', icon: Activity },
  { id: 'detect_sector_rotation', label: 'Detect Sector Rotation', icon: RefreshCw },
  { id: 'stock_upgrade_downgrade', label: 'Upgrade/Downgrade', icon: Newspaper },
  { id: 'investigation_strategies', label: 'Investigate + Strategy', icon: Search },
  { id: 'mega_setup_advisor', label: 'Mega Setup Advisor', icon: Sparkles },
  { id: 'option_chain', label: 'Option Chain', icon: Link2 },
  { id: 'option_short_long', label: 'Option-Short-Long — OI Buildup · Premium/Discount · Buy/Sell Call/Put (NSE)', icon: Target },
  { id: 'india_market_heatmap', label: 'IN-US-Crypto Market Heatmap', icon: Grid3x3 },
  { id: 'advance_decline_graph', label: 'Advance Decline Graph', icon: Activity },
  { id: 'comparative_strength', label: 'Comparative Strength', icon: Scale },
  { id: 'nse_world_indices', label: 'NSE and World Indices', icon: Globe2 },
  { id: 'coindcx_24h_volatility', label: '24Hrs Volatile Crypto', icon: Flame },
  { id: 'quick_analyzer', label: 'Quick Analyzer', icon: Zap },
] as const

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

const ONE_CLICK_STYLE: Record<string, 'intraday' | 'scalping' | 'swing'> = {
  one_click_intraday: 'intraday',
  one_click_scalping: 'scalping',
  one_click_swing: 'swing',
}

const CC_BG_SKIP = new Set<TabId>([
  'playbook',
  'tomorrow_outlook',
  'global_market_mood',
  'coindcx_24h_volatility',
  'nse_world_indices',
  'india_fii_dii_holdings',
  'mutual_fund_holdings',
  'etf_holdings',
  'smart_money_activity',
  'detect_sector_rotation',
  'advance_decline_graph',
  'comparative_strength',
])

type TabId = (typeof TABS)[number]['id']
type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: ['1d'] }

export default function CommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = searchParams.get('tab')
  const initialTab: TabId =
    tabFromUrl && TABS.some((t) => t.id === tabFromUrl) ? (tabFromUrl as TabId) : 'nse_world_indices'
  const [tab, setTab] = useState<TabId>(initialTab)

  useEffect(() => {
    const next = searchParams.get('tab')
    if (next && TABS.some((t) => t.id === next) && next !== tab) {
      setTab(next as TabId)
    }
  }, [searchParams, tab])

  const selectTab = useCallback(
    (id: TabId) => {
      setTab(id)
      setSearchParams((prev) => {
        const p = new URLSearchParams(prev)
        p.set('tab', id)
        return p
      }, { replace: true })
    },
    [setSearchParams],
  )
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [result, setResult] = useState<unknown>(null)
  const [error, setError] = useState('')
  const [timeframes, setTimeframes] = useState('15m,1h,1d')
  const [useAi, setUseAi] = useState(false)
  const [showCharts, setShowCharts] = useState(false)
  const [strategyIds, setStrategyIds] = useState<string[]>([])
  const [heatmapIndex, setHeatmapIndex] = useState('Nifty 50')
  const [heatmapCustomTickers, setHeatmapCustomTickers] = useState('')
  const [moversAssetClass, setMoversAssetClass] = useState<AssetClass>('india')
  const [moversIndex, setMoversIndex] = useState('')
  const [moversTimeframe, setMoversTimeframe] = useState('1d')
  const [optionInstrumentType, setOptionInstrumentType] = useState<'Index' | 'Stock'>('Index')
  const [optionSymbol, setOptionSymbol] = useState('NIFTY')
  const [oslInstrumentType, setOslInstrumentType] = useState<'Index' | 'Stock'>('Index')
  const [oslIndices, setOslIndices] = useState<string[]>(['NIFTY'])
  const [oslStockSymbols, setOslStockSymbols] = useState<string[]>([])
  const [oslStockInput, setOslStockInput] = useState('')
  const [oslDebouncedInput, setOslDebouncedInput] = useState('')
  const [oslSuggestOpen, setOslSuggestOpen] = useState(false)
  const [oslSelectedExpiries, setOslSelectedExpiries] = useState<string[]>([])
  const [qaTimeframes, setQaTimeframes] = useState('15m,1h,4h,1d')
  const [qaFromDate, setQaFromDate] = useState(() => isoDaysAgo(90))
  const [qaToDate, setQaToDate] = useState(() => isoDaysAgo(0))
  const [qaIncludeFundamentals, setQaIncludeFundamentals] = useState(false)
  const [qaIncludeOptionChain, setQaIncludeOptionChain] = useState(false)

  useQuery({ queryKey: ['cc-sections'], queryFn: fetchCommandCenterSections })

  const tomorrowQuery = useQuery({
    queryKey: ['cc-tomorrow'],
    queryFn: fetchTomorrowOutlook,
    enabled: tab === 'tomorrow_outlook',
  })

  const moodQuery = useQuery({
    queryKey: ['cc-market-mood'],
    queryFn: fetchGlobalMarketMood,
    enabled: tab === 'global_market_mood',
  })

  const strategyCatalogQuery = useQuery({
    queryKey: ['cc-strategy-catalog'],
    queryFn: fetchInvestigationStrategyCatalog,
    enabled: tab === 'investigation_strategies',
  })

  const coinDcxQuery = useQuery({
    queryKey: ['cc-coindcx-24h'],
    queryFn: fetchCoinDcx24hVolatility,
    enabled: tab === 'coindcx_24h_volatility',
  })

  const nseIndicesQuery = useQuery({
    queryKey: ['cc-nse-indices'],
    queryFn: fetchNseIndices,
    enabled: false,
  })

  const globalIndicesQuery = useQuery({
    queryKey: ['cc-global-indices'],
    queryFn: fetchGlobalIndices,
    enabled: false,
  })

  const futuresIndicesQuery = useQuery({
    queryKey: ['cc-futures-indices'],
    queryFn: fetchFuturesIndices,
    enabled: false,
  })

  const giftNiftyQuery = useQuery({
    queryKey: ['cc-gift-nifty'],
    queryFn: fetchGiftNifty,
    enabled: false,
  })

  const heatmapAssetClass: 'india' | 'us' | 'crypto' = assetClass === 'us' || assetClass === 'crypto' ? assetClass : 'india'
  const heatmapIndicesQuery = useQuery({
    queryKey: ['cc-heatmap-indices', heatmapAssetClass],
    queryFn: () => fetchIndiaMarketHeatmapIndices(heatmapAssetClass),
    enabled: tab === 'india_market_heatmap',
  })

  useEffect(() => {
    const names = heatmapIndicesQuery.data?.index_names
    if (names?.length && !names.includes(heatmapIndex)) {
      setHeatmapIndex(names[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heatmapIndicesQuery.data])

  const moversOptionsQuery = useQuery({
    queryKey: ['cc-movers-options', moversAssetClass],
    queryFn: () => fetchMarketMoversOptions(moversAssetClass),
    enabled: tab === 'market_movers',
  })

  useEffect(() => {
    const indices = moversOptionsQuery.data?.indices
    if (indices?.length && !indices.some((i) => i.value === moversIndex)) {
      setMoversIndex(indices[0].value)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moversOptionsQuery.data])

  useEffect(() => {
    const t = setTimeout(() => setOslDebouncedInput(oslStockInput.trim()), 200)
    return () => clearTimeout(t)
  }, [oslStockInput])

  const oslSuggestQuery = useQuery({
    queryKey: ['osl-ticker-suggest', oslDebouncedInput],
    queryFn: () => fetchTickerSuggestions('india', oslDebouncedInput, 10),
    enabled: tab === 'option_short_long' && oslInstrumentType === 'Stock' && oslDebouncedInput.length >= 1,
  })
  const oslSuggestions = (oslSuggestQuery.data?.tickers ?? []).filter((s) => !oslStockSymbols.includes(s))

  const oslPrimarySymbol = oslInstrumentType === 'Index' ? oslIndices[0] : oslStockSymbols[0]
  const oslExpiriesQuery = useQuery({
    queryKey: ['osl-expiries', oslInstrumentType, oslPrimarySymbol],
    queryFn: () => fetchOptionShortLongExpiries(oslPrimarySymbol as string, oslInstrumentType === 'Index'),
    enabled: tab === 'option_short_long' && !!oslPrimarySymbol,
  })
  const oslAvailableExpiries = oslExpiriesQuery.data?.expiries ?? []

  // Clear the selection immediately on symbol/instrument change so a stale
  // expiry list from the PREVIOUS symbol (e.g. NIFTY's weekly dates) can
  // never be submitted for a DIFFERENT symbol (e.g. BANKNIFTY, monthly-only)
  // while the fresh list is still loading.
  useEffect(() => {
    setOslSelectedExpiries([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oslPrimarySymbol, oslInstrumentType])

  useEffect(() => {
    if (oslAvailableExpiries.length) setOslSelectedExpiries(oslAvailableExpiries)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oslExpiriesQuery.data])

  const handlePickerChange = useCallback((v: TickerPickerValue) => {
    setPicker(v)
  }, [])

  const toggleStrategyId = (id: string) => {
    setStrategyIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))
  }

  const bgEnabled = !CC_BG_SKIP.has(tab)
  const bg = useAnalysisBackground('command_center', tab, bgEnabled)

  const buildPayload = (): Record<string, unknown> => {
    const { tickers, durations } = picker

    if (tab === 'mega_setup_advisor') {
      const market = assetClass === 'india' ? 'Groww (India Stocks)'
        : assetClass === 'us' ? 'US Stocks (Yahoo)'
        : assetClass === 'crypto' ? 'CoinDCX Futures' : 'Commodity Futures'
      return {
        market,
        timeframes: timeframes.split(',').map((t) => t.trim()).filter(Boolean),
        ticker_count: tickers.length,
        use_ai: useAi,
      }
    }

    if (tab === 'india_market_heatmap') {
      if (heatmapIndex === 'Custom') {
        const customTickers = heatmapCustomTickers.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean)
        return { index_name: heatmapIndex, asset_class: heatmapAssetClass, tickers: customTickers }
      }
      return { index_name: heatmapIndex, asset_class: heatmapAssetClass }
    }

    if (tab === 'market_movers') {
      return { asset_class: moversAssetClass, index: moversIndex, timeframe: moversTimeframe }
    }

    if (tab === 'option_chain') {
      return { symbol: optionSymbol.trim().toUpperCase(), is_index: optionInstrumentType === 'Index' }
    }

    if (tab === 'option_short_long') {
      const symbols = oslInstrumentType === 'Index' ? oslIndices : oslStockSymbols
      return { symbols, is_index: oslInstrumentType === 'Index', expiries: oslSelectedExpiries }
    }

    if (tab === 'quick_analyzer') {
      const qaTfs = qaTimeframes.split(',').map((t) => t.trim()).filter(Boolean)
      return {
        tickers,
        timeframes: qaTfs,
        asset_class: assetClass,
        from_date: qaFromDate,
        to_date: qaToDate,
        include_fundamentals: assetClass === 'india' && qaIncludeFundamentals,
        include_option_chain: assetClass === 'india' && qaIncludeOptionChain,
      }
    }

    const base = { tickers, asset_class: assetClass, timeframes: durations, durations }
    switch (tab) {
      case 'mega_analyser':
        return base
      case 'buy_sell':
        return base
      case 'investigation':
        return { tickers, asset_class: assetClass }
      case 'momentum':
      case 'divergences':
      case 'candlestick_chart_patterns':
      case 'stop_hunt':
      case 'take_profit':
      case 'real_bottom':
      case 'weak_strong':
      case 'sma_20_200':
      case 'take_trade':
      case 'ema_position':
      case 'mtf_trend_strength':
      case 'trade_setup':
        return base
      case 'copy_trade':
        return { tickers, asset_class: assetClass }
      case 'fundamental_analysis':
        return { tickers, asset_class: assetClass }
      case 'stock_upgrade_downgrade':
        return { tickers, asset_class: assetClass }
      case 'one_click_intraday':
      case 'one_click_scalping':
      case 'one_click_swing':
        return { style: ONE_CLICK_STYLE[tab], tickers, asset_class: assetClass }
      case 'investigation_strategies':
        return { tickers, asset_class: assetClass, strategy_ids: strategyIds }
      default:
        return base
    }
  }

  const validatePayload = (): string | null => {
    const { tickers } = picker
    if (tab === 'india_market_heatmap') {
      if (!heatmapIndex) return 'Choose an index/sector'
      if (heatmapIndex === 'Custom') {
        const customTickers = heatmapCustomTickers.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean)
        if (!customTickers.length) return 'Enter at least one custom ticker'
      }
      return null
    }
    if (tab === 'market_movers') {
      if (!moversIndex) return 'Choose an index/group'
      return null
    }
    if (tab === 'option_chain') {
      if (!optionSymbol.trim()) return 'Enter or select a symbol'
      return null
    }
    if (tab === 'option_short_long') {
      const symbols = oslInstrumentType === 'Index' ? oslIndices : oslStockSymbols
      if (!symbols.length) return 'Pick at least one index, or add a stock symbol'
      if (oslExpiriesQuery.isFetching) return 'Still loading expiries for this symbol — try again in a moment.'
      if (!oslSelectedExpiries.length) return 'Select at least one expiry'
      return null
    }
    if (tab === 'quick_analyzer') {
      if (!tickers.length) return 'Select at least one ticker'
      if (assetClass === 'commodity') return 'Quick Analyzer supports India, US, and Crypto only'
      const qaTfs = qaTimeframes.split(',').map((t) => t.trim()).filter(Boolean)
      if (!qaTfs.length) return 'Select at least one timeframe'
      if (qaFromDate > qaToDate) return 'From date must be on or before To date'
      return null
    }
    if (!['mega_setup_advisor', 'market_movers', 'option_chain', 'option_short_long', 'india_market_heatmap', 'quick_analyzer'].includes(tab) && !tickers.length) {
      return 'Select at least one ticker'
    }
    return null
  }

  const runMutation = useMutation({
    mutationFn: async () => {
      const { tickers, durations } = picker

      if (tab === 'mega_setup_advisor') {
        const market = assetClass === 'india' ? 'Groww (India Stocks)'
          : assetClass === 'us' ? 'US Stocks (Yahoo)'
          : assetClass === 'crypto' ? 'CoinDCX Futures' : 'Commodity Futures'
        return runMegaSetupAdvisor({
          market,
          timeframes: timeframes.split(',').map((t) => t.trim()).filter(Boolean),
          ticker_count: tickers.length,
          use_ai: useAi,
        })
      }

      if (tab === 'india_market_heatmap') {
        if (!heatmapIndex) throw new Error('Choose an index/sector')
        if (heatmapIndex === 'Custom') {
          const customTickers = heatmapCustomTickers.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean)
          if (!customTickers.length) throw new Error('Enter at least one custom ticker')
          return runIndiaMarketHeatmap({ index_name: heatmapIndex, asset_class: heatmapAssetClass, tickers: customTickers })
        }
        return runIndiaMarketHeatmap({ index_name: heatmapIndex, asset_class: heatmapAssetClass })
      }

      if (tab === 'market_movers') {
        if (!moversIndex) throw new Error('Choose an index/group')
        return runMarketMovers({ asset_class: moversAssetClass, index: moversIndex, timeframe: moversTimeframe })
      }

      if (tab === 'option_chain') {
        if (!optionSymbol.trim()) throw new Error('Enter or select a symbol')
        return runOptionChain({ symbol: optionSymbol.trim().toUpperCase(), is_index: optionInstrumentType === 'Index' })
      }

      if (tab === 'option_short_long') {
        const symbols = oslInstrumentType === 'Index' ? oslIndices : oslStockSymbols
        if (!symbols.length) throw new Error('Pick at least one index, or add a stock symbol')
        if (oslExpiriesQuery.isFetching) throw new Error('Still loading expiries for this symbol — try again in a moment.')
        if (!oslSelectedExpiries.length) throw new Error('Select at least one expiry')
        return runOptionShortLong({ symbols, is_index: oslInstrumentType === 'Index', expiries: oslSelectedExpiries })
      }

      if (tab === 'quick_analyzer') {
        if (!tickers.length) throw new Error('Select at least one ticker')
        if (assetClass === 'commodity') throw new Error('Quick Analyzer supports India, US, and Crypto only')
        const qaTfs = qaTimeframes.split(',').map((t) => t.trim()).filter(Boolean)
        if (!qaTfs.length) throw new Error('Select at least one timeframe')
        if (qaFromDate > qaToDate) throw new Error('From date must be on or before To date')
        return runQuickAnalyzer({
          tickers, timeframes: qaTfs, asset_class: assetClass,
          from_date: qaFromDate, to_date: qaToDate,
          include_fundamentals: assetClass === 'india' && qaIncludeFundamentals,
          include_option_chain: assetClass === 'india' && qaIncludeOptionChain,
        })
      }

      if (!tickers.length) throw new Error('Select at least one ticker')

      switch (tab) {
        case 'tomorrow_outlook':
          return fetchTomorrowOutlook()
        case 'mega_analyser':
          return runMegaAnalyser({ tickers, asset_class: assetClass, durations })
        case 'buy_sell':
          return runBuySellAdvisor({ tickers, asset_class: assetClass, durations })
        case 'investigation':
          return runTickerInvestigation({ tickers, asset_class: assetClass })
        case 'momentum':
          return runMomentumScan({ tickers, asset_class: assetClass, timeframes: durations })
        case 'divergences':
          return runDivergences({ tickers, asset_class: assetClass, timeframes: durations })
        case 'candlestick_chart_patterns':
          return runPatterns({ tickers, asset_class: assetClass, timeframes: durations })
        case 'stop_hunt':
          return runStopHunt({ tickers, asset_class: assetClass, timeframes: durations })
        case 'take_profit':
          return runTakeProfit({ tickers, asset_class: assetClass, timeframes: durations })
        case 'real_bottom':
          return runRealBottom({ tickers, asset_class: assetClass, timeframes: durations })
        case 'weak_strong':
          return runWeakStrong({ tickers, asset_class: assetClass, timeframes: durations })
        case 'sma_20_200':
          return runSma20200({ tickers, asset_class: assetClass, timeframes: durations })
        case 'copy_trade':
          return runCopyTrade({ tickers, asset_class: assetClass })
        case 'take_trade':
          return runTakeTrade({ tickers, asset_class: assetClass, timeframes: durations })
        case 'ema_position':
          return runEmaPositionScan({ tickers, asset_class: assetClass, timeframes: durations })
        case 'mtf_trend_strength':
          return runMtfTrendStrength({ tickers, asset_class: assetClass, timeframes: durations })
        case 'trade_setup':
          return runTradeSetup({ tickers, asset_class: assetClass, timeframes: durations })
        case 'fundamental_analysis':
          return runFundamentalAnalysis({ tickers, asset_class: assetClass })
        case 'stock_upgrade_downgrade':
          return runUpgradeDowngradeScan({ tickers, asset_class: assetClass })
        case 'one_click_intraday':
        case 'one_click_scalping':
        case 'one_click_swing':
          return runOneClick({ style: ONE_CLICK_STYLE[tab], tickers, asset_class: assetClass })
        case 'investigation_strategies':
          return runInvestigationWithStrategies({ tickers, asset_class: assetClass, strategy_ids: strategyIds })
      }
    },
    onSuccess: (data) => { setResult(data); setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const nseWorldIndicesData = (nseIndicesQuery.data || globalIndicesQuery.data || futuresIndicesQuery.data || giftNiftyQuery.data)
    ? {
        nse_rows: nseIndicesQuery.data?.rows, global_rows: globalIndicesQuery.data?.rows,
        futures_rows: futuresIndicesQuery.data?.rows, gift_nifty: giftNiftyQuery.data?.data,
      }
    : null

  const mutationResult = bg.viewedPayload ?? result
  const displayData = tab === 'tomorrow_outlook' ? tomorrowQuery.data
    : tab === 'global_market_mood' ? moodQuery.data
    : tab === 'coindcx_24h_volatility' ? coinDcxQuery.data
    : tab === 'nse_world_indices' ? nseWorldIndicesData
    : mutationResult
  const loading = tab === 'tomorrow_outlook' ? tomorrowQuery.isLoading
    : tab === 'global_market_mood' ? moodQuery.isLoading
    : tab === 'coindcx_24h_volatility' ? coinDcxQuery.isLoading
    : tab === 'nse_world_indices' ? (nseIndicesQuery.isFetching || globalIndicesQuery.isFetching || futuresIndicesQuery.isFetching || giftNiftyQuery.isFetching)
    : runMutation.isPending
  const queryError = tab === 'tomorrow_outlook' ? (tomorrowQuery.isError ? apiErrorMessage(tomorrowQuery.error) : '')
    : tab === 'global_market_mood' ? (moodQuery.isError ? apiErrorMessage(moodQuery.error) : '')
    : tab === 'coindcx_24h_volatility' ? (coinDcxQuery.isError ? apiErrorMessage(coinDcxQuery.error) : '')
    : tab === 'nse_world_indices' ? (nseIndicesQuery.isError ? apiErrorMessage(nseIndicesQuery.error) : globalIndicesQuery.isError ? apiErrorMessage(globalIndicesQuery.error) : futuresIndicesQuery.isError ? apiErrorMessage(futuresIndicesQuery.error) : giftNiftyQuery.isError ? apiErrorMessage(giftNiftyQuery.error) : '')
    : ''
  const askContext = displayData ? buildAskContext(TABS.find((t) => t.id === tab)?.label ?? tab, displayData) : ''

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
    setPicker(DEFAULT_PICKER)
    setResult(null)
    setError('')
  }

  const watchlistMarket: WatchlistMarket =
    assetClass === 'us' || assetClass === 'commodity' ? 'us' : assetClass === 'crypto' ? 'crypto' : 'india'

  return (
    <WatchlistMarketProvider market={watchlistMarket}>
    <div>
      <PageHeader
        title="Command Center"
        description="Tomorrow's outlook · Mega Analyser · Buy/Sell advisor · Ticker Investigation (India · US · Crypto)"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <Chip key={id} selected={tab === id} onClick={() => { selectTab(id); setError(''); setResult(null) }}>
            <span className="inline-flex items-center gap-1.5">
              <Icon size={14} />
              {label}
            </span>
          </Chip>
        ))}
      </div>

      {tab === 'playbook' ? (
        <PlaybookPanel />
      ) : tab === 'india_fii_dii_holdings' ? (
        <IndiaFiiDiiHoldingsPanel />
      ) : tab === 'advance_decline_graph' ? (
        <AdvanceDeclineGraphPanel />
      ) : tab === 'comparative_strength' ? (
        <ComparativeStrengthPanel />
      ) : tab === 'mutual_fund_holdings' ? (
        <MutualFundHoldingsPanel />
      ) : tab === 'etf_holdings' ? (
        <EtfHoldingsPanel />
      ) : tab === 'smart_money_activity' ? (
        <SmartMoneyActivityPanel />
      ) : tab === 'detect_sector_rotation' ? (
        <DetectSectorRotationPanel />
      ) : tab === 'tomorrow_outlook' ? (
        <Card className="mb-6">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => tomorrowQuery.refetch()}
            disabled={tomorrowQuery.isFetching}
          >
            <RefreshCw size={14} />
            {tomorrowQuery.isFetching ? 'Refreshing…' : 'Refresh outlook'}
          </Button>
          {(queryError || error) && (
            <div className="mt-3"><Alert type="error">{queryError || error}</Alert></div>
          )}
        </Card>
      ) : tab === 'global_market_mood' ? (
        <Card className="mb-6">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => moodQuery.refetch()}
            disabled={moodQuery.isFetching}
          >
            <RefreshCw size={14} />
            {moodQuery.isFetching ? 'Refreshing…' : 'Refresh mood'}
          </Button>
          {(queryError || error) && (
            <div className="mt-3"><Alert type="error">{queryError || error}</Alert></div>
          )}
        </Card>
      ) : tab === 'coindcx_24h_volatility' ? (
        <Card className="mb-6">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => coinDcxQuery.refetch()}
            disabled={coinDcxQuery.isFetching}
          >
            <RefreshCw size={14} />
            {coinDcxQuery.isFetching ? 'Refreshing…' : 'Refresh'}
          </Button>
          {(queryError || error) && (
            <div className="mt-3"><Alert type="error">{queryError || error}</Alert></div>
          )}
        </Card>
      ) : tab === 'nse_world_indices' ? (
        <Card className="mb-6">
          <div className="flex flex-wrap gap-3">
            <Button
              variant="secondary"
              onClick={() => nseIndicesQuery.refetch()}
              disabled={nseIndicesQuery.isFetching}
            >
              {nseIndicesQuery.isFetching ? 'Loading…' : '📥 Load NSE Indices'}
            </Button>
            <Button
              variant="secondary"
              onClick={() => globalIndicesQuery.refetch()}
              disabled={globalIndicesQuery.isFetching}
            >
              {globalIndicesQuery.isFetching ? 'Loading…' : '🌍 Load Global Indices'}
            </Button>
            <Button
              variant="secondary"
              onClick={() => { futuresIndicesQuery.refetch(); giftNiftyQuery.refetch() }}
              disabled={futuresIndicesQuery.isFetching || giftNiftyQuery.isFetching}
            >
              {(futuresIndicesQuery.isFetching || giftNiftyQuery.isFetching) ? 'Loading…' : '🚀 Load Futures'}
            </Button>
          </div>
          {(queryError || error) && (
            <div className="mt-3"><Alert type="error">{queryError || error}</Alert></div>
          )}
        </Card>
      ) : tab === 'india_market_heatmap' ? (
        <Card className="mb-6">
          <div className="grid gap-4 sm:grid-cols-[1fr_2fr_1fr]">
            <FormField label="Asset class">
              <Select value={heatmapAssetClass} onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}>
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
              </Select>
            </FormField>
            <FormField label={heatmapAssetClass === 'india' ? 'Index / Sector' : 'Index / Group'}>
              <Select value={heatmapIndex} onChange={(e) => setHeatmapIndex(e.target.value)}>
                {(heatmapIndicesQuery.data?.index_names ?? [heatmapIndex]).map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </Select>
            </FormField>
            <div className="flex items-end">
              <Button className="w-full" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || bg.runInBackground}>
                {runMutation.isPending ? 'Loading…' : 'Submit'}
              </Button>
            </div>
          </div>
          {heatmapIndex === 'Custom' && (
            <div className="mt-3">
              <FormField label={`Custom ${heatmapAssetClass === 'crypto' ? 'crypto pairs' : 'tickers'} (comma-separated)`}>
                <textarea
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  rows={2}
                  placeholder={heatmapAssetClass === 'crypto' ? 'BTC-USDT, ETH-USDT' : heatmapAssetClass === 'us' ? 'AAPL, MSFT, NVDA' : 'RELIANCE, TCS, INFY'}
                  value={heatmapCustomTickers}
                  onChange={(e) => setHeatmapCustomTickers(e.target.value)}
                />
              </FormField>
            </div>
          )}
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          {bgEnabled && (
            <AnalysisBackgroundControls
              bg={bg}
              placeholder={`${TABS.find((t) => t.id === tab)?.label ?? tab} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(buildPayload(), validatePayload)}
            />
          )}
        </Card>
      ) : tab === 'market_movers' ? (
        <Card className="mb-6">
          <div className="grid gap-4 sm:grid-cols-[1fr_2fr_1fr_1fr]">
            <FormField label="Asset class">
              <Select
                value={moversAssetClass}
                onChange={(e) => { setMoversAssetClass(e.target.value as AssetClass); setMoversIndex('') }}
              >
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
                <option value="commodity">🛢️ Commodity futures</option>
              </Select>
            </FormField>
            <FormField label="Index / Group">
              <Select value={moversIndex} onChange={(e) => setMoversIndex(e.target.value)}>
                {(moversOptionsQuery.data?.indices ?? []).map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </Select>
            </FormField>
            <FormField label="Timeframe">
              <Select value={moversTimeframe} onChange={(e) => setMoversTimeframe(e.target.value)}>
                {(moversOptionsQuery.data?.timeframes ?? []).map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </Select>
            </FormField>
            <div className="flex items-end">
              <Button className="w-full" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || moversOptionsQuery.isLoading || bg.runInBackground}>
                {runMutation.isPending ? 'Scanning…' : 'Find movers'}
              </Button>
            </div>
          </div>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          {bgEnabled && (
            <AnalysisBackgroundControls
              bg={bg}
              placeholder={`${TABS.find((t) => t.id === tab)?.label ?? tab} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(buildPayload(), validatePayload)}
            />
          )}
        </Card>
      ) : tab === 'option_chain' ? (
        <Card className="mb-6">
          <div className="grid gap-4 sm:grid-cols-[1fr_2fr_1.3fr]">
            <FormField label="Instrument type">
              <Select
                value={optionInstrumentType}
                onChange={(e) => {
                  const next = e.target.value as 'Index' | 'Stock'
                  setOptionInstrumentType(next)
                  setOptionSymbol(next === 'Index' ? 'NIFTY' : 'RELIANCE')
                }}
              >
                <option value="Index">Index</option>
                <option value="Stock">Stock</option>
              </Select>
            </FormField>
            {optionInstrumentType === 'Index' ? (
              <FormField label="Index">
                <Select value={optionSymbol} onChange={(e) => setOptionSymbol(e.target.value)}>
                  <option value="NIFTY">NIFTY</option>
                  <option value="BANKNIFTY">BANKNIFTY</option>
                  <option value="FINNIFTY">FINNIFTY</option>
                  <option value="MIDCPNIFTY">MIDCPNIFTY</option>
                </Select>
              </FormField>
            ) : (
              <FormField label="Stock symbol (NSE)">
                <input
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={optionSymbol}
                  onChange={(e) => setOptionSymbol(e.target.value.toUpperCase())}
                  placeholder="RELIANCE"
                />
              </FormField>
            )}
            <div className="flex items-end">
              <Button className="w-full" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || bg.runInBackground}>
                {runMutation.isPending ? 'Fetching…' : '🔍 Analyze Option Chain'}
              </Button>
            </div>
          </div>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          {bgEnabled && (
            <AnalysisBackgroundControls
              bg={bg}
              placeholder={`${TABS.find((t) => t.id === tab)?.label ?? tab} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(buildPayload(), validatePayload)}
            />
          )}
        </Card>
      ) : tab === 'option_short_long' ? (
        <Card className="mb-6">
          <div className="grid gap-4 sm:grid-cols-[1fr_2fr_1fr]">
            <FormField label="Instrument type">
              <Select
                value={oslInstrumentType}
                onChange={(e) => setOslInstrumentType(e.target.value as 'Index' | 'Stock')}
              >
                <option value="Index">Index</option>
                <option value="Stock">Stock</option>
              </Select>
            </FormField>
            {oslInstrumentType === 'Index' ? (
              <FormField label="Index(es) — NSE F&O only (BSE Sensex/Bankex options aren't wired into this app)">
                <div className="flex flex-wrap gap-1.5">
                  {['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'].map((idx) => (
                    <Chip
                      key={idx}
                      selected={oslIndices.includes(idx)}
                      onClick={() => setOslIndices((prev) => (prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx]))}
                    >
                      {idx}
                    </Chip>
                  ))}
                </div>
              </FormField>
            ) : (
              <FormField label="Stock symbol(s)">
                <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5">
                  {oslStockSymbols.map((s) => (
                    <span key={s} className="flex items-center gap-1 rounded-md bg-slate-700/60 px-2 py-0.5 text-xs text-slate-100">
                      {s}
                      <button
                        type="button"
                        className="text-slate-400 hover:text-rose-400"
                        onClick={() => setOslStockSymbols((prev) => prev.filter((t) => t !== s))}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  <div className="relative flex-1 min-w-[120px]">
                    <input
                      className="w-full bg-transparent px-1 py-0.5 text-sm text-slate-100 outline-none"
                      value={oslStockInput}
                      onChange={(e) => { setOslStockInput(e.target.value.toUpperCase()); setOslSuggestOpen(true) }}
                      onFocus={() => setOslSuggestOpen(true)}
                      onBlur={() => setTimeout(() => setOslSuggestOpen(false), 120)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && oslStockInput.trim()) {
                          e.preventDefault()
                          const sym = oslStockInput.trim().toUpperCase()
                          setOslStockSymbols((prev) => (prev.includes(sym) ? prev : [...prev, sym]))
                          setOslStockInput('')
                          setOslSuggestOpen(false)
                        }
                      }}
                      placeholder={oslStockSymbols.length ? 'Add another…' : 'e.g. RELIANCE'}
                      autoComplete="off"
                    />
                    {oslSuggestOpen && oslDebouncedInput.length >= 1 && (oslSuggestions.length > 0 || oslSuggestQuery.isFetching) && (
                      <ul className="absolute z-10 mt-1 max-h-56 w-48 overflow-y-auto rounded-lg border border-slate-700/80 bg-slate-900 shadow-lg">
                        {oslSuggestQuery.isFetching && oslSuggestions.length === 0 && (
                          <li className="px-3 py-2 text-xs text-slate-500">Searching…</li>
                        )}
                        {oslSuggestions.map((s) => (
                          <li key={s}>
                            <button
                              type="button"
                              onMouseDown={(e) => {
                                e.preventDefault()
                                setOslStockSymbols((prev) => (prev.includes(s) ? prev : [...prev, s]))
                                setOslStockInput('')
                                setOslSuggestOpen(false)
                              }}
                              className="block w-full px-3 py-1.5 text-left text-sm text-slate-200 hover:bg-slate-800"
                            >
                              {s}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </FormField>
            )}
            <div className="flex items-end">
              <Button className="w-full" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || bg.runInBackground}>
                {runMutation.isPending ? 'Analyzing…' : '🎯 Analyze'}
              </Button>
            </div>
          </div>
          {oslPrimarySymbol && (
            <div className="mt-4">
              <FormField label={`Expiries to analyze${oslExpiriesQuery.isFetching ? ' (loading…)' : ''}`}>
                {oslAvailableExpiries.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {oslAvailableExpiries.map((exp) => (
                      <Chip
                        key={exp}
                        selected={oslSelectedExpiries.includes(exp)}
                        onClick={() => setOslSelectedExpiries((prev) => (prev.includes(exp) ? prev.filter((e) => e !== exp) : [...prev, exp]))}
                      >
                        {exp}
                      </Chip>
                    ))}
                  </div>
                ) : !oslExpiriesQuery.isFetching ? (
                  <p className="text-xs text-slate-500">No listed expiries found for {oslPrimarySymbol}.</p>
                ) : null}
              </FormField>
            </div>
          )}
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          {bgEnabled && (
            <AnalysisBackgroundControls
              bg={bg}
              placeholder={`${TABS.find((t) => t.id === tab)?.label ?? tab} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(buildPayload(), validatePayload)}
            />
          )}
        </Card>
      ) : tab === 'mega_setup_advisor' ? (
        <Card className="mb-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Asset class">
              <Select value={assetClass} onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}>
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
                <option value="commodity">🛢️ Commodity futures</option>
              </Select>
            </FormField>
            <FormField label="Timeframes (comma-separated)">
              <input
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={timeframes}
                onChange={(e) => setTimeframes(e.target.value)}
              />
            </FormField>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
            Use AI to personalize (falls back to rule-based if no API key configured)
          </label>
          <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || bg.runInBackground}>
            {runMutation.isPending ? 'Thinking…' : 'Get recommendation'}
          </Button>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          {bgEnabled && (
            <AnalysisBackgroundControls
              bg={bg}
              placeholder={`${TABS.find((t) => t.id === tab)?.label ?? tab} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(buildPayload(), validatePayload)}
            />
          )}
        </Card>
      ) : (
        <Card className="mb-6">
          <FormField label="Asset class">
            <Select
              value={assetClass}
              onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}
            >
              <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
              <option value="us">🇺🇸 US stocks (Yahoo)</option>
              <option value="crypto">₿ Crypto (CoinDCX)</option>
              <option value="commodity">🛢️ Commodity futures</option>
            </Select>
          </FormField>

          <AssetClassTickerPicker
            key={assetClass}
            assetClass={assetClass}
            single={tab === 'mega_analyser'}
            showDurations={tab === 'buy_sell' || tab === 'mega_analyser' || tab === 'momentum' || tab === 'ema_position' || tab === 'mtf_trend_strength' || tab === 'trade_setup' || tab === 'divergences' || tab === 'candlestick_chart_patterns' || tab === 'stop_hunt' || tab === 'take_profit' || tab === 'real_bottom' || tab === 'weak_strong' || tab === 'take_trade' || tab === 'sma_20_200'}
            onChange={handlePickerChange}
          />

          {tab === 'quick_analyzer' && (
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <FormField label="Timeframes (comma-separated)">
                <input
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={qaTimeframes}
                  onChange={(e) => setQaTimeframes(e.target.value)}
                />
              </FormField>
              <FormField label="From date">
                <input
                  type="date"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={qaFromDate}
                  onChange={(e) => setQaFromDate(e.target.value)}
                />
              </FormField>
              <FormField label="To date">
                <input
                  type="date"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={qaToDate}
                  onChange={(e) => setQaToDate(e.target.value)}
                />
              </FormField>
            </div>
          )}

          {tab === 'quick_analyzer' && assetClass === 'india' && (
            <div className="mt-4 flex flex-wrap gap-4">
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={qaIncludeFundamentals}
                  onChange={(e) => setQaIncludeFundamentals(e.target.checked)}
                />
                📚 Include Fundamental Analysis in trade setup &amp; confidence
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={qaIncludeOptionChain}
                  onChange={(e) => setQaIncludeOptionChain(e.target.checked)}
                />
                ⛓️ Include Option Chain Analysis in trade setup &amp; confidence
              </label>
            </div>
          )}

          {tab === 'investigation_strategies' && (
            <div className="mt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
                Strategies to run against this ticker
              </p>
              <div className="max-h-48 space-y-3 overflow-y-auto rounded-lg border border-slate-800 p-3">
                {Object.entries(strategyCatalogQuery.data?.groups ?? {}).map(([group, opts]) => (
                  <div key={group}>
                    <p className="mb-1 text-xs font-semibold text-slate-400">{group}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {opts.map((o) => (
                        <Chip key={o.id} selected={strategyIds.includes(o.id)} onClick={() => toggleStrategyId(o.id)}>
                          {o.label}
                        </Chip>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === 'ema_position' && (
            <div className="mt-4">
              <ChartsToggle checked={showCharts} onChange={setShowCharts} />
            </div>
          )}

          <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || bg.runInBackground}>
            {runMutation.isPending ? 'Running…' : 'Run analysis'}
          </Button>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          {bgEnabled && (
            <AnalysisBackgroundControls
              bg={bg}
              placeholder={`${TABS.find((t) => t.id === tab)?.label ?? tab} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(buildPayload(), validatePayload)}
            />
          )}
        </Card>
      )}

      {bgEnabled && <AnalysisBackgroundJobsAndReports bg={bg} />}

      {loading && !bg.viewedPayload && <Loading message="Running analysis…" />}

      {displayData && (!loading || bg.viewedPayload) && !queryError && (
        <Card>
          {bg.viewedReportMeta?.name && (
            <p className="mb-3 text-sm text-slate-400">
              Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
            </p>
          )}
          <CommandCenterResults tab={tab} data={displayData as Record<string, unknown>} assetClass={assetClass} showCharts={showCharts} />
        </Card>
      )}

      {askContext && !loading && tab !== 'trade_setup' && tab !== 'take_trade' && tab !== 'india_fii_dii_holdings' && tab !== 'mutual_fund_holdings' && tab !== 'etf_holdings' && tab !== 'smart_money_activity' && tab !== 'detect_sector_rotation' && tab !== 'advance_decline_graph' && tab !== 'comparative_strength' && (
        <AskAIPanel context={askContext} section={`command-center/${tab}`} />
      )}
    </div>
    </WatchlistMarketProvider>
  )
}
