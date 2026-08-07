import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Radar, Zap } from 'lucide-react'
import {
  apiErrorMessage,
  executeSignal,
  fetchBacktesterLeaderboardCatalog,
  runScan,
  type ScanSignal,
} from '../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../components/analysis/AnalysisBackground'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, ConfidenceBar, Loading } from '../components/ui/Feedback'
import { StrategyDataSourceBar } from '../components/ui/StrategyDataSourceBar'
import { DataTable, SortableTh, Th, Td } from '../components/ui/Table'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk', '1M']

type SortKey = 'ticker' | 'strategy' | 'timeframe' | 'action' | 'price' | 'day_high' | 'day_low' | 'sl_pct' | 'tp_pct' | 'confidence_pct'

const TF_ORDER: Record<string, number> = {
  '1m': 1, '3m': 2, '5m': 3, '15m': 4, '30m': 5, '1h': 6, '4h': 7, '1d': 8, '1wk': 9, '1M': 10,
}
const ACTION_ORDER = { BUY: 0, SELL: 1, HOLD: 2 }

function formatPrice(value?: number | null, assetClass: AssetClass = 'india') {
  if (value == null || value <= 0) return '—'
  const sym = assetClass === 'us' || assetClass === 'commodity' ? '$' : assetClass === 'crypto' ? '' : '₹'
  return `${sym}${value.toFixed(2)}`
}

function signalKey(s: ScanSignal) {
  return `${s.ticker}-${s.strategy}-${s.timeframe}`
}

function compareSignals(a: ScanSignal, b: ScanSignal, key: SortKey): number {
  switch (key) {
    case 'ticker':
      return a.ticker.localeCompare(b.ticker)
    case 'strategy':
      return a.strategy_label.localeCompare(b.strategy_label)
    case 'timeframe':
      return (TF_ORDER[a.timeframe] ?? 99) - (TF_ORDER[b.timeframe] ?? 99)
    case 'action':
      return ACTION_ORDER[a.action] - ACTION_ORDER[b.action]
    case 'price':
      return a.price - b.price
    case 'day_high':
      return (a.day_high ?? 0) - (b.day_high ?? 0)
    case 'day_low':
      return (a.day_low ?? 0) - (b.day_low ?? 0)
    case 'sl_pct':
      return a.sl_pct - b.sl_pct
    case 'tp_pct':
      return a.tp_pct - b.tp_pct
    case 'confidence_pct':
      return a.confidence_pct - b.confidence_pct
  }
}

export default function Scanner() {
  const qc = useQueryClient()
  const [searchParams] = useSearchParams()
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(() => {
    const fromUrl = searchParams.get('strategy')
    return fromUrl ? [fromUrl] : []
  })
  const [selectedTimeframes, setSelectedTimeframes] = useState<string[]>(['15m', '1d'])
  const [bars, setBars] = useState(350)
  const [signals, setSignals] = useState<ScanSignal[]>([])
  const [scanMeta, setScanMeta] = useState<Record<string, unknown> | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('confidence_pct')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [error, setError] = useState('')
  const bg = useAnalysisBackground('scanner', 'scan')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'confidence_pct' || key === 'price' || key === 'day_high' || key === 'day_low' || key === 'sl_pct' || key === 'tp_pct' ? 'desc' : 'asc')
    }
  }

  const scanMutation = useMutation({
    mutationFn: runScan,
    onSuccess: (data) => {
      setSignals(data.signals)
      setScanMeta(data as unknown as Record<string, unknown>)
      setError('')
      bg.setViewedReportId(null)
    },
    onError: (e: unknown) => setError(apiErrorMessage(e)),
  })

  const reportSignals = (bg.viewedPayload as { signals?: ScanSignal[] } | undefined)?.signals
  const displaySignals = reportSignals ?? signals

  const sortedSignals = useMemo(() => {
    return [...displaySignals].sort((a, b) => {
      const cmp = compareSignals(a, b, sortKey)
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [displaySignals, sortKey, sortDir])

  const {
    data: catalog,
    isLoading: categoriesLoading,
    isError: categoriesError,
    error: categoriesFetchError,
  } = useQuery({ queryKey: ['bt-catalog'], queryFn: fetchBacktesterLeaderboardCatalog })

  const categories = catalog?.categories ?? []
  const strategies = categories.flatMap((c) => c.strategies)
  const totalStrategyCount = categories.reduce((n, c) => n + c.strategy_count, 0)

  useEffect(() => {
    const fromUrl = searchParams.get('strategy')
    if (fromUrl) setSelectedStrategies([fromUrl])
  }, [searchParams])

  const handlePickerChange = useCallback((v: TickerPickerValue) => {
    setPicker(v)
  }, [])

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
    setPicker({ tickers: [], durations: [] })
    setSignals([])
    setError('')
  }

  const tradeMutation = useMutation({
    mutationFn: executeSignal,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['account'] })
      alert('Paper trade executed')
    },
    onError: (e: unknown) => alert(apiErrorMessage(e)),
  })

  const toggle = (list: string[], item: string, setter: (v: string[]) => void) => {
    setter(list.includes(item) ? list.filter((x) => x !== item) : [...list, item])
  }

  const handleScan = () => {
    const tickerList = picker.tickers
    if (!tickerList.length || !selectedStrategies.length || !selectedTimeframes.length) {
      setError('Select at least one ticker, strategy, and timeframe')
      return
    }
    scanMutation.mutate({
      tickers: tickerList,
      strategies: selectedStrategies,
      timeframes: selectedTimeframes,
      asset_class: assetClass,
      bars,
    })
  }

  const buildScanPayload = () => ({
    tickers: picker.tickers,
    strategies: selectedStrategies,
    timeframes: selectedTimeframes,
    asset_class: assetClass,
    bars,
  })

  const validateScan = () => {
    if (!picker.tickers.length || !selectedStrategies.length || !selectedTimeframes.length) {
      return 'Select at least one ticker, strategy, and timeframe'
    }
    return null
  }

  const activeSignals = displaySignals.filter((s) => s.action !== 'HOLD')

  return (
    <div>
      <PageHeader
        title="Strategy Scanner"
        description="Search tickers across strategies and timeframes — BUY/SELL with SL%, TP%, and confidence · India · US · Crypto · Commodities"
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-5 flex items-center gap-2">
            <Radar className="text-blue-400" size={20} />
            <h3 className="font-semibold text-white">Scan Configuration</h3>
          </div>

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
            defaultSelectCount="All"
            defaultCryptoTopN={200}
            onChange={handlePickerChange}
          />

          <FormField label="Timeframes">
            <div className="flex flex-wrap gap-2">
              {TIMEFRAMES.map((tf) => (
                <Chip
                  key={tf}
                  selected={selectedTimeframes.includes(tf)}
                  onClick={() => toggle(selectedTimeframes, tf, setSelectedTimeframes)}
                >
                  {tf}
                </Chip>
              ))}
            </div>
          </FormField>

          <FormField label="History bars">
            <Input type="number" min={150} max={2000} step={50} value={bars} onChange={(e) => setBars(Number(e.target.value))} />
          </FormField>

          <FormField label={`Strategies (${selectedStrategies.length} of ${totalStrategyCount} selected)`}>
            {categoriesLoading && <Loading message="Loading strategies…" />}
            {categoriesError && (
              <Alert type="error">{apiErrorMessage(categoriesFetchError)}</Alert>
            )}
            {!categoriesLoading && !categoriesError && (
              <>
                <div className="max-h-56 space-y-3 overflow-y-auto rounded-xl border border-slate-800/60 bg-slate-800/20 p-3">
                  {categories.map((cat) => (
                    <div key={cat.id}>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                        {cat.label} · {cat.timeframes.join(', ')}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {cat.strategies.map((s) => (
                          <Chip
                            key={s.id}
                            selected={selectedStrategies.includes(s.id)}
                            onClick={() => toggle(selectedStrategies, s.id, setSelectedStrategies)}
                            title={s.summary}
                          >
                            {s.name}
                          </Chip>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button variant="secondary" size="sm" className="flex-1 sm:flex-none" onClick={() => setSelectedStrategies(strategies.map((s) => s.id))}>
                    Select All
                  </Button>
                  <Button variant="ghost" size="sm" className="flex-1 sm:flex-none" onClick={() => setSelectedStrategies([])}>
                    Clear
                  </Button>
                </div>
              </>
            )}
          </FormField>

          <Button onClick={handleScan} disabled={scanMutation.isPending || bg.runInBackground} className="w-full sm:w-auto">
            <Zap size={16} />
            {scanMutation.isPending
              ? `Scanning ${picker.tickers.length} ticker${picker.tickers.length === 1 ? '' : 's'}…`
              : `Run Scan${picker.tickers.length ? ` (${picker.tickers.length})` : ''}`}
          </Button>
          <AnalysisBackgroundControls
            bg={bg}
            placeholder={`Scanner · ${new Date().toLocaleDateString()}`}
            onStart={() => bg.startBackground(buildScanPayload(), validateScan)}
          />
          {error && <Alert type="error">{error}</Alert>}
        </Card>

        <AnalysisBackgroundJobsAndReports bg={bg} />

        <Card>
          <h3 className="mb-1 font-semibold text-white">Scan Summary</h3>
          {bg.viewedReportMeta?.name && (
            <p className="mb-2 text-sm text-slate-400">
              Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
            </p>
          )}
          <p className="mb-4 text-sm text-slate-500">
            {displaySignals.length
              ? `${activeSignals.length} active signals of ${displaySignals.length} combinations`
              : 'Run a scan to see results'}
          </p>

          {scanMutation.isPending && <Loading message="Analyzing markets..." />}

          <div className="space-y-3">
            {activeSignals.slice(0, 5).map((s, i) => (
              <div
                key={i}
                className="rounded-xl border border-slate-800/60 bg-slate-800/30 p-4 transition-colors hover:border-slate-700"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-white">{s.ticker}</span>
                  <Badge action={s.action} />
                </div>
                <p className="mt-1.5 text-xs text-slate-500">
                  {s.strategy_label} · {s.timeframe}
                </p>
                <div className="mt-2 flex items-center justify-between text-xs">
                  <span className="text-slate-400">Confidence</span>
                  <span className="font-medium text-blue-400">{s.confidence_pct}%</span>
                </div>
                <ConfidenceBar value={s.confidence_pct} />
              </div>
            ))}
          </div>
        </Card>
      </div>

      {signals.length > 0 && (
        <Card className="mt-6">
          <StrategyDataSourceBar
            data={(bg.viewedPayload as Record<string, unknown> | undefined) ?? scanMeta}
            assetClass={assetClass}
          />
          <h3 className="mb-4 text-base font-semibold text-white sm:text-lg">Results</h3>

          <div className="space-y-3 md:hidden">
            {sortedSignals.map((s) => (
              <div
                key={signalKey(s)}
                className="rounded-xl border border-slate-800/60 bg-slate-800/20 p-4"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold text-white">{s.ticker}</p>
                    <p className="mt-0.5 truncate text-xs text-slate-500">{s.strategy_label}</p>
                  </div>
                  <Badge action={s.action} />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-slate-500">Price</span>
                    <p className="font-medium tabular-nums text-slate-200">{formatPrice(s.price, assetClass)}</p>
                  </div>
                  <div>
                    <span className="text-slate-500">Day High / Low</span>
                    <p className="font-medium tabular-nums text-slate-200">
                      {formatPrice(s.day_high, assetClass)} / {formatPrice(s.day_low, assetClass)}
                    </p>
                  </div>
                  <div>
                    <span className="text-slate-500">TF</span>
                    <p className="font-medium text-slate-200">{s.timeframe}</p>
                  </div>
                  <div>
                    <span className="text-slate-500">SL / TP</span>
                    <p className="font-medium text-slate-200">
                      {s.sl_pct ? `${s.sl_pct}%` : '—'} / {s.tp_pct ? `${s.tp_pct}%` : '—'}
                    </p>
                  </div>
                  <div>
                    <span className="text-slate-500">Confidence</span>
                    <p className="font-medium text-blue-400">{s.confidence_pct}%</p>
                  </div>
                </div>
                <ConfidenceBar value={s.confidence_pct} />
                {s.action !== 'HOLD' && (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-3 w-full"
                    onClick={() => tradeMutation.mutate({ ...s, asset_class: assetClass })}
                    disabled={tradeMutation.isPending}
                  >
                    Paper {s.action === 'BUY' ? 'Buy' : 'Sell'}
                  </Button>
                )}
              </div>
            ))}
          </div>

          <div className="hidden md:block">
          <DataTable minWidth={1050}>
            <thead>
              <tr>
                <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
                <SortableTh active={sortKey === 'strategy'} direction={sortDir} onSort={() => handleSort('strategy')}>Strategy</SortableTh>
                <SortableTh active={sortKey === 'timeframe'} direction={sortDir} onSort={() => handleSort('timeframe')}>TF</SortableTh>
                <SortableTh active={sortKey === 'action'} direction={sortDir} onSort={() => handleSort('action')}>Action</SortableTh>
                <SortableTh active={sortKey === 'price'} direction={sortDir} onSort={() => handleSort('price')}>Price</SortableTh>
                <SortableTh active={sortKey === 'day_high'} direction={sortDir} onSort={() => handleSort('day_high')}>Day High</SortableTh>
                <SortableTh active={sortKey === 'day_low'} direction={sortDir} onSort={() => handleSort('day_low')}>Day Low</SortableTh>
                <SortableTh active={sortKey === 'sl_pct'} direction={sortDir} onSort={() => handleSort('sl_pct')}>SL%</SortableTh>
                <SortableTh active={sortKey === 'tp_pct'} direction={sortDir} onSort={() => handleSort('tp_pct')}>TP%</SortableTh>
                <SortableTh active={sortKey === 'confidence_pct'} direction={sortDir} onSort={() => handleSort('confidence_pct')}>Confidence</SortableTh>
                <Th></Th>
              </tr>
            </thead>
            <tbody>
              {sortedSignals.map((s) => (
                <tr key={signalKey(s)} className="hover:bg-slate-800/20">
                  <Td className="font-medium text-white">{s.ticker}</Td>
                  <Td>{s.strategy_label}</Td>
                  <Td>
                    <span className="rounded-md bg-slate-800 px-2 py-0.5 text-xs">{s.timeframe}</span>
                  </Td>
                  <Td><Badge action={s.action} /></Td>
                  <Td className="tabular-nums">{formatPrice(s.price, assetClass)}</Td>
                  <Td className="tabular-nums text-emerald-400/90">{formatPrice(s.day_high, assetClass)}</Td>
                  <Td className="tabular-nums text-rose-400/90">{formatPrice(s.day_low, assetClass)}</Td>
                  <Td>{s.sl_pct ? `${s.sl_pct}%` : '—'}</Td>
                  <Td>{s.tp_pct ? `${s.tp_pct}%` : '—'}</Td>
                  <Td className="min-w-[120px]">
                    <span className="font-medium text-blue-400">{s.confidence_pct}%</span>
                    <ConfidenceBar value={s.confidence_pct} />
                  </Td>
                  <Td>
                    {s.action !== 'HOLD' && (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => tradeMutation.mutate({ ...s, asset_class: assetClass })}
                        disabled={tradeMutation.isPending}
                      >
                        Paper {s.action === 'BUY' ? 'Buy' : 'Sell'}
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          </div>
        </Card>
      )}
    </div>
  )
}
