import { useCallback, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BarChart3, CandlestickChart, Compass, Crosshair, FishingHook, Flame, Globe2, Grid3x3, LineChart, Link2, Newspaper, Radar, RefreshCw, Rocket, Search, Shuffle, Sparkles, Sun, Target, TrendingUp, Zap } from 'lucide-react'
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
  fetchTomorrowOutlook,
  runBuySellAdvisor,
  runEmaPositionScan,
  runFundamentalAnalysis,
  runIndiaMarketHeatmap,
  runInvestigationWithStrategies,
  runDivergences,
  runMegaAnalyser,
  runMegaSetupAdvisor,
  runMomentumScan,
  runOneClick,
  runOptionChain,
  runPatterns,
  runQuickAnalyzer,
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
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const TABS = [
  { id: 'tomorrow_outlook', label: 'Tomorrow Outlook', icon: Sun },
  { id: 'mega_analyser', label: 'Mega Analyser', icon: Radar },
  { id: 'buy_sell', label: 'Buy or Sell', icon: Compass },
  { id: 'investigation', label: 'Ticker Investigation', icon: Search },
  { id: 'global_market_mood', label: 'Global Market Mood', icon: Globe2 },
  { id: 'momentum', label: 'Momentum Scanner', icon: TrendingUp },
  { id: 'ema_position', label: 'EMA Position', icon: LineChart },
  { id: 'divergences', label: 'Divergences', icon: Shuffle },
  { id: 'candlestick_chart_patterns', label: 'Candlestick & Chart Patterns', icon: CandlestickChart },
  { id: 'stop_hunt', label: 'Stoploss Hunting', icon: FishingHook },
  { id: 'take_profit', label: 'Take Profit Targets', icon: Crosshair },
  { id: 'take_trade', label: 'Take Trade', icon: Rocket },
  { id: 'trade_setup', label: 'Trade Setup — Oversold/Overbought', icon: Target },
  { id: 'one_click_intraday', label: 'One-Click Intraday', icon: Zap },
  { id: 'one_click_scalping', label: 'One-Click Scalping', icon: Zap },
  { id: 'one_click_swing', label: 'One-Click Swing', icon: Zap },
  { id: 'fundamental_analysis', label: 'Fundamental Analysis', icon: BarChart3 },
  { id: 'stock_upgrade_downgrade', label: 'Upgrade/Downgrade', icon: Newspaper },
  { id: 'investigation_strategies', label: 'Investigate + Strategy', icon: Search },
  { id: 'mega_setup_advisor', label: 'Mega Setup Advisor', icon: Sparkles },
  { id: 'option_chain', label: 'Option Chain', icon: Link2 },
  { id: 'india_market_heatmap', label: 'Indian Market Heatmap', icon: Grid3x3 },
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

type TabId = (typeof TABS)[number]['id']
type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: ['1d'] }

export default function CommandCenter() {
  const [tab, setTab] = useState<TabId>('nse_world_indices')
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [result, setResult] = useState<unknown>(null)
  const [error, setError] = useState('')
  const [timeframes, setTimeframes] = useState('15m,1h,1d')
  const [useAi, setUseAi] = useState(false)
  const [strategyIds, setStrategyIds] = useState<string[]>([])
  const [heatmapIndex, setHeatmapIndex] = useState('Nifty 50')
  const [optionInstrumentType, setOptionInstrumentType] = useState<'Index' | 'Stock'>('Index')
  const [optionSymbol, setOptionSymbol] = useState('NIFTY')
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

  const heatmapIndicesQuery = useQuery({
    queryKey: ['cc-heatmap-indices'],
    queryFn: fetchIndiaMarketHeatmapIndices,
    enabled: tab === 'india_market_heatmap',
  })

  const handlePickerChange = useCallback((v: TickerPickerValue) => {
    setPicker(v)
  }, [])

  const toggleStrategyId = (id: string) => {
    setStrategyIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))
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
        return runIndiaMarketHeatmap({ index_name: heatmapIndex })
      }

      if (tab === 'option_chain') {
        if (!optionSymbol.trim()) throw new Error('Enter or select a symbol')
        return runOptionChain({ symbol: optionSymbol.trim().toUpperCase(), is_index: optionInstrumentType === 'Index' })
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
        case 'take_trade':
          return runTakeTrade({ tickers, asset_class: assetClass, timeframes: durations })
        case 'ema_position':
          return runEmaPositionScan({ tickers, asset_class: assetClass, timeframes: durations })
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
    onSuccess: (data) => { setResult(data); setError('') },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const nseWorldIndicesData = (nseIndicesQuery.data || globalIndicesQuery.data || futuresIndicesQuery.data || giftNiftyQuery.data)
    ? {
        nse_rows: nseIndicesQuery.data?.rows, global_rows: globalIndicesQuery.data?.rows,
        futures_rows: futuresIndicesQuery.data?.rows, gift_nifty: giftNiftyQuery.data?.data,
      }
    : null

  const displayData = tab === 'tomorrow_outlook' ? tomorrowQuery.data
    : tab === 'global_market_mood' ? moodQuery.data
    : tab === 'coindcx_24h_volatility' ? coinDcxQuery.data
    : tab === 'nse_world_indices' ? nseWorldIndicesData
    : result
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

  return (
    <div>
      <PageHeader
        title="Command Center"
        description="Tomorrow's outlook · Mega Analyser · Buy/Sell advisor · Ticker Investigation (India · US · Crypto)"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <Chip key={id} selected={tab === id} onClick={() => { setTab(id); setError(''); setResult(null) }}>
            <span className="inline-flex items-center gap-1.5">
              <Icon size={14} />
              {label}
            </span>
          </Chip>
        ))}
      </div>

      {tab === 'tomorrow_outlook' ? (
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
          <div className="grid gap-4 sm:grid-cols-[2fr_1fr]">
            <FormField label="Index / Sector">
              <Select value={heatmapIndex} onChange={(e) => setHeatmapIndex(e.target.value)}>
                {(heatmapIndicesQuery.data?.index_names ?? [heatmapIndex]).map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </Select>
            </FormField>
            <div className="flex items-end">
              <Button className="w-full" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
                {runMutation.isPending ? 'Loading…' : 'Submit'}
              </Button>
            </div>
          </div>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
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
              <Button className="w-full" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
                {runMutation.isPending ? 'Fetching…' : '🔍 Analyze Option Chain'}
              </Button>
            </div>
          </div>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
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
          <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
            {runMutation.isPending ? 'Thinking…' : 'Get recommendation'}
          </Button>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
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
            showDurations={tab === 'buy_sell' || tab === 'mega_analyser' || tab === 'momentum' || tab === 'ema_position' || tab === 'trade_setup' || tab === 'divergences' || tab === 'candlestick_chart_patterns' || tab === 'stop_hunt' || tab === 'take_profit' || tab === 'take_trade'}
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

          <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
            {runMutation.isPending ? 'Running…' : 'Run analysis'}
          </Button>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
        </Card>
      )}

      {loading && <Loading message="Running analysis…" />}

      {displayData && !loading && !queryError && (
        <Card>
          <CommandCenterResults tab={tab} data={displayData as Record<string, unknown>} assetClass={assetClass} />
        </Card>
      )}

      {askContext && !loading && tab !== 'trade_setup' && tab !== 'take_trade' && (
        <AskAIPanel context={askContext} section={`command-center/${tab}`} />
      )}
    </div>
  )
}
