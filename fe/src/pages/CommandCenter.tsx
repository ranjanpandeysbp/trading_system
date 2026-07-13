import { useCallback, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BarChart3, Compass, Globe2, LineChart, Newspaper, Radar, RefreshCw, Search, Sparkles, Sun, TrendingUp, Zap } from 'lucide-react'
import {
  apiErrorMessage,
  fetchCommandCenterSections,
  fetchGlobalMarketMood,
  fetchInvestigationStrategyCatalog,
  fetchTomorrowOutlook,
  runBuySellAdvisor,
  runEmaPositionScan,
  runFundamentalAnalysis,
  runInvestigationWithStrategies,
  runMegaAnalyser,
  runMegaSetupAdvisor,
  runMomentumScan,
  runOneClick,
  runTickerInvestigation,
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
  { id: 'one_click_intraday', label: 'One-Click Intraday', icon: Zap },
  { id: 'one_click_scalping', label: 'One-Click Scalping', icon: Zap },
  { id: 'one_click_swing', label: 'One-Click Swing', icon: Zap },
  { id: 'fundamental_analysis', label: 'Fundamental Analysis', icon: BarChart3 },
  { id: 'stock_upgrade_downgrade', label: 'Upgrade/Downgrade', icon: Newspaper },
  { id: 'investigation_strategies', label: 'Investigate + Strategy', icon: Search },
  { id: 'mega_setup_advisor', label: 'Mega Setup Advisor', icon: Sparkles },
] as const

const ONE_CLICK_STYLE: Record<string, 'intraday' | 'scalping' | 'swing'> = {
  one_click_intraday: 'intraday',
  one_click_scalping: 'scalping',
  one_click_swing: 'swing',
}

type TabId = (typeof TABS)[number]['id']
type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: ['1d'] }

export default function CommandCenter() {
  const [tab, setTab] = useState<TabId>('tomorrow_outlook')
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [result, setResult] = useState<unknown>(null)
  const [error, setError] = useState('')
  const [timeframes, setTimeframes] = useState('15m,1h,1d')
  const [useAi, setUseAi] = useState(false)
  const [strategyIds, setStrategyIds] = useState<string[]>([])

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
          return runMomentumScan({ tickers, asset_class: assetClass })
        case 'ema_position':
          return runEmaPositionScan({ tickers, asset_class: assetClass })
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

  const displayData = tab === 'tomorrow_outlook' ? tomorrowQuery.data : tab === 'global_market_mood' ? moodQuery.data : result
  const loading = tab === 'tomorrow_outlook' ? tomorrowQuery.isLoading : tab === 'global_market_mood' ? moodQuery.isLoading : runMutation.isPending
  const queryError = tab === 'tomorrow_outlook' ? (tomorrowQuery.isError ? apiErrorMessage(tomorrowQuery.error) : '')
    : tab === 'global_market_mood' ? (moodQuery.isError ? apiErrorMessage(moodQuery.error) : '') : ''
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
            showDurations={tab === 'buy_sell' || tab === 'mega_analyser'}
            onChange={handlePickerChange}
          />

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
          <CommandCenterResults tab={tab} data={displayData as Record<string, unknown>} />
        </Card>
      )}

      {askContext && !loading && (
        <AskAIPanel context={askContext} section={`command-center/${tab}`} />
      )}
    </div>
  )
}
