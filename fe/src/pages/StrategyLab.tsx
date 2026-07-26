import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Beaker, Grid3X3, ListFilter, BookOpen } from 'lucide-react'
import {
  apiErrorMessage,
  fetchStrategyLabPresets,
  fetchStrategyLabSections,
  runStrategyLabBacktest,
  runStrategyLabMultiCombo,
  runStrategyLabScreener,
} from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import type { AssetClass } from '../components/command-center/AssetClassTickerPicker'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { StatCard } from '../components/ui/StatCard'
import { DataTable, SortableTh, Td, useSort } from '../components/ui/Table'

const TABS = [
  { id: 'builder', label: 'Builder & Tester', icon: Beaker },
  { id: 'multi_combo', label: 'Multi-Combo', icon: Grid3X3 },
  { id: 'screener', label: 'Advanced Screener', icon: ListFilter },
  { id: 'presets', label: 'Encyclopedia', icon: BookOpen },
] as const

type TabId = (typeof TABS)[number]['id']

const TFS = ['5m', '15m', '1h', '4h', '1d']

const SCREENER_PRESETS = [
  { id: 'rsi_oversold', label: 'RSI Oversold (<35)' },
  { id: 'rsi_overbought', label: 'RSI Overbought (>65)' },
  { id: 'above_ema20', label: 'Price above EMA 20' },
  { id: 'below_ema20', label: 'Price below EMA 20' },
] as const

const DEFAULT_TICKERS: Record<AssetClass, string> = {
  india: 'RELIANCE, TCS, INFY, HDFCBANK',
  us: 'AAPL, MSFT, NVDA, AMZN',
  crypto: 'BTC-USDT, ETH-USDT, SOL-USDT',
  commodity: 'CL=F, GC=F, SI=F',
}

const DEFAULT_TICKER: Record<AssetClass, string> = {
  india: 'RELIANCE',
  us: 'AAPL',
  crypto: 'BTC-USDT',
  commodity: 'CL=F',
}

function parseTickers(raw: string) {
  return raw.split(/[,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean)
}

export default function StrategyLab() {
  const [tab, setTab] = useState<TabId>('builder')
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [ticker, setTicker] = useState(DEFAULT_TICKER.india)
  const [tickers, setTickers] = useState(DEFAULT_TICKERS.india)
  const [timeframe, setTimeframe] = useState('1d')
  const [selectedTfs, setSelectedTfs] = useState<string[]>(['1d'])
  const [preset, setPreset] = useState('')
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([])
  const [strategiesInit, setStrategiesInit] = useState(false)
  const [screenerPreset, setScreenerPreset] = useState<string>('rsi_oversold')
  const [error, setError] = useState('')
  const [directionMode, setDirectionMode] = useState<'long_only' | 'short_only' | 'long_short'>('long_only')
  const [positionSizing, setPositionSizing] = useState<'pct_of_capital' | 'risk_pct'>('pct_of_capital')
  const [riskPct, setRiskPct] = useState(1.0)

  useQuery({ queryKey: ['sl-sections'], queryFn: fetchStrategyLabSections })
  const presetsQuery = useQuery({
    queryKey: ['sl-presets', assetClass],
    queryFn: () => fetchStrategyLabPresets(undefined, assetClass),
  })

  const presetNames = useMemo(
    () => Object.keys((presetsQuery.data as { presets?: Record<string, unknown> })?.presets ?? {}),
    [presetsQuery.data],
  )

  useEffect(() => {
    if (!presetNames.length) return
    if (!strategiesInit) {
      setSelectedStrategies(presetNames.slice(0, 5))
      setStrategiesInit(true)
      return
    }
    // Asset-class change left stale strategy names — re-seed.
    if (selectedStrategies.length > 0 && selectedStrategies.every((s) => !presetNames.includes(s))) {
      setSelectedStrategies(presetNames.slice(0, 5))
    }
  }, [presetNames, strategiesInit, selectedStrategies])

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
    setTicker(DEFAULT_TICKER[next])
    setTickers(DEFAULT_TICKERS[next])
    setPreset('')
    setSelectedStrategies([])
    setStrategiesInit(false)
    setError('')
  }

  const tickerList = parseTickers(tickers)

  const mutation = useMutation({
    mutationFn: async () => {
      switch (tab) {
        case 'builder':
          return runStrategyLabBacktest({
            ticker,
            timeframe,
            asset_class: assetClass,
            preset_name: preset || undefined,
            capital: 100_000,
            direction_mode: directionMode,
            position_sizing: positionSizing,
            risk_pct: riskPct,
          })
        case 'multi_combo': {
          if (!tickerList.length) throw new Error('Enter at least one ticker')
          if (!selectedStrategies.length) throw new Error('Select at least one strategy preset')
          return runStrategyLabMultiCombo({
            tickers: tickerList,
            timeframes: selectedTfs,
            strategies: selectedStrategies,
            asset_class: assetClass,
          })
        }
        case 'screener': {
          if (!tickerList.length) throw new Error('Enter at least one ticker')
          return runStrategyLabScreener({
            tickers: tickerList,
            timeframes: selectedTfs,
            asset_class: assetClass,
            screener_preset: screenerPreset,
          })
        }
        default:
          return presetsQuery.refetch()
      }
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => setError(''),
  })

  const toggleTf = (tf: string) => {
    setSelectedTfs((prev) => (prev.includes(tf) ? prev.filter((t) => t !== tf) : [...prev, tf]))
  }

  const toggleStrategy = (name: string) => {
    setSelectedStrategies((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name],
    )
  }

  const result = tab === 'presets' ? presetsQuery.data : mutation.data
  const loading = tab === 'presets' ? presetsQuery.isLoading : mutation.isPending

  return (
    <div>
      <PageHeader
        title="Strategy Lab"
        description="Backtest presets · Multi-combo scanner · Rule screener · Full hub encyclopedia — Command Center · Market Pulse · TA · Trading Hubs · Options"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <Chip key={id} selected={tab === id} onClick={() => { setTab(id); setError('') }}>
            <span className="inline-flex items-center gap-1.5">
              <Icon size={14} />
              {label}
            </span>
          </Chip>
        ))}
      </div>

      <Card className="mb-4">
        <FormField label="Asset class">
          <Select value={assetClass} onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}>
            <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
            <option value="us">🇺🇸 US stocks (Yahoo)</option>
            <option value="crypto">₿ Crypto (CoinDCX)</option>
            <option value="commodity">🛢️ Commodity futures</option>
          </Select>
        </FormField>

        {tab !== 'presets' && (
          <>
            {tab === 'builder' && (
              <div className="mt-4 grid gap-4 sm:grid-cols-3">
                <FormField label="Ticker">
                  <Input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} />
                </FormField>
                <FormField label="Timeframe">
                  <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                    {TFS.map((tf) => (
                      <option key={tf} value={tf}>{tf}</option>
                    ))}
                  </Select>
                </FormField>
                <FormField label="Preset">
                  <Select value={preset} onChange={(e) => setPreset(e.target.value)}>
                    <option value="">RSI mean-reversion (default)</option>
                    {presetNames.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </Select>
                </FormField>
              </div>
            )}

            {tab === 'builder' && (
              <div className="mt-4 grid gap-4 sm:grid-cols-3">
                <FormField label="Trade direction">
                  <Select value={directionMode} onChange={(e) => setDirectionMode(e.target.value as typeof directionMode)}>
                    <option value="long_only">Long Only</option>
                    <option value="short_only">Short Only</option>
                    <option value="long_short">Long &amp; Short</option>
                  </Select>
                </FormField>
                <FormField label="Position sizing">
                  <Select value={positionSizing} onChange={(e) => setPositionSizing(e.target.value as typeof positionSizing)}>
                    <option value="pct_of_capital">% of Capital (simple)</option>
                    <option value="risk_pct">Risk % per Trade (professional)</option>
                  </Select>
                </FormField>
                {positionSizing === 'risk_pct' && (
                  <FormField label="Risk % per trade">
                    <Input
                      type="number" step={0.25} min={0.25} max={10}
                      value={riskPct} onChange={(e) => setRiskPct(Number(e.target.value))}
                    />
                  </FormField>
                )}
              </div>
            )}

            {(tab === 'multi_combo' || tab === 'screener') && (
              <>
                <div className="mt-4">
                  <FormField label="Tickers (comma-separated)">
                    <Textarea rows={2} value={tickers} onChange={(e) => setTickers(e.target.value)} />
                  </FormField>
                </div>
                <div className="mt-4">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Timeframes</p>
                  <div className="flex flex-wrap gap-2">
                    {TFS.map((tf) => (
                      <Chip key={tf} selected={selectedTfs.includes(tf)} onClick={() => toggleTf(tf)}>
                        {tf}
                      </Chip>
                    ))}
                  </div>
                </div>
              </>
            )}

            {tab === 'multi_combo' && (
              <div className="mt-4">
                <FormField label={`Strategies (${selectedStrategies.length} selected)`}>
                  <div className="max-h-40 space-y-2 overflow-y-auto rounded-xl border border-slate-800/60 bg-slate-800/20 p-3">
                    <div className="flex flex-wrap gap-2">
                      {presetNames.map((name) => (
                        <Chip key={name} selected={selectedStrategies.includes(name)} onClick={() => toggleStrategy(name)}>
                          {name}
                        </Chip>
                      ))}
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={() => setSelectedStrategies(presetNames.slice(0, 5))}>
                      First 5
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => setSelectedStrategies(presetNames)}>
                      Select all
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setSelectedStrategies([])}>
                      Clear
                    </Button>
                  </div>
                </FormField>
              </div>
            )}

            {tab === 'screener' && (
              <div className="mt-4">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Rule preset</p>
                <div className="flex flex-wrap gap-2">
                  {SCREENER_PRESETS.map((p) => (
                    <Chip key={p.id} selected={screenerPreset === p.id} onClick={() => setScreenerPreset(p.id)}>
                      {p.label}
                    </Chip>
                  ))}
                </div>
              </div>
            )}

            <Button className="mt-4" onClick={() => mutation.mutate()} disabled={loading}>
              {loading
                ? 'Running…'
                : tab === 'builder'
                  ? 'Run backtest'
                  : tab === 'multi_combo'
                    ? `Run multi-combo (${tickerList.length} × ${selectedTfs.length} × ${selectedStrategies.length})`
                    : `Run screener (${tickerList.length})`}
            </Button>
            {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          </>
        )}
      </Card>

      {loading && <Loading message="Fetching data and running analysis…" />}

      {!loading && result && tab === 'builder' && (
        <Card className="mb-4">
          <BuilderResults data={result as Record<string, unknown>} />
        </Card>
      )}

      {!loading && result && tab === 'multi_combo' && (
        <Card className="mb-4">
          <ComboResults data={result as Record<string, unknown>} />
        </Card>
      )}

      {!loading && result && tab === 'screener' && (
        <Card className="mb-4">
          <ScreenerResults data={result as Record<string, unknown>} />
        </Card>
      )}

      {!loading && result && tab === 'presets' && (
        <Card className="mb-4">
          <PresetsPanel data={result as Record<string, unknown>} />
        </Card>
      )}

      {result && tab !== 'presets' && (
        <AskAIPanel
          context={buildAskContext(TABS.find((t) => t.id === tab)?.label ?? tab, result)}
          section={`strategy-lab/${tab}`}
        />
      )}
    </div>
  )
}

function fmtPct(v: unknown, digits = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(digits)}%` : '—'
}

function ProfessionalMetrics({ metrics }: { metrics: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  const hasDirectionSplit = metrics.long_trades != null && metrics.short_trades != null
  const buyHold = metrics.buy_hold_return_pct
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full px-3 py-2.5 text-left text-sm font-medium text-slate-200 hover:bg-slate-800/30"
      >
        Professional Metrics {open ? '▲' : '▼'}
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/60 p-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Sortino Ratio" value={typeof metrics.sortino_ratio === 'number' ? metrics.sortino_ratio.toFixed(3) : '—'} />
            <StatCard label="Annual Volatility" value={fmtPct(metrics.annual_volatility_pct)} />
            <StatCard label="Max DD Duration" value={`${metrics.max_drawdown_duration_days ?? '—'}d`} />
            <StatCard label="Market Exposure" value={fmtPct(metrics.exposure_pct)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Expectancy / Trade" value={fmtPct(metrics.expectancy_pct, 3)} />
            <StatCard label="Max Win Streak" value={String(metrics.max_consecutive_wins ?? '—')} />
            <StatCard label="Max Loss Streak" value={String(metrics.max_consecutive_losses ?? '—')} />
            <StatCard label="Alpha vs Buy&Hold" value={buyHold != null ? fmtPct(metrics.alpha_pct) : '—'} />
          </div>
          {hasDirectionSplit && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Long Trades" value={String(metrics.long_trades)} />
              <StatCard label="Long Win Rate" value={fmtPct(metrics.long_win_rate_pct)} />
              <StatCard label="Short Trades" value={String(metrics.short_trades)} />
              <StatCard label="Short Win Rate" value={fmtPct(metrics.short_win_rate_pct)} />
            </div>
          )}
          {buyHold != null && (
            <p className="text-xs text-slate-500">
              Buy &amp; Hold over the same window: <strong>{fmtPct(buyHold)}</strong> · Strategy alpha: <strong>{fmtPct(metrics.alpha_pct)}</strong>
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function BuilderResults({ data }: { data: Record<string, unknown> }) {
  const metrics = (data.metrics as Record<string, number>) ?? {}
  return (
    <div className="space-y-4">
      <h3 className="font-semibold text-white">
        {String(data.ticker)} · {String(data.timeframe)} · {String(data.market)}
        {data.preset_name ? ` · ${String(data.preset_name)}` : ''}
      </h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total return" value={`${metrics.total_return_pct?.toFixed(2) ?? '—'}%`} />
        <StatCard label="Sharpe" value={metrics.sharpe_ratio?.toFixed(2) ?? '—'} />
        <StatCard label="Max DD" value={`${metrics.max_drawdown_pct?.toFixed(2) ?? '—'}%`} />
        <StatCard label="Trades" value={String(data.trade_count ?? metrics.n_trades ?? '—')} />
      </div>
      <ProfessionalMetrics metrics={metrics} />
    </div>
  )
}

function ComboResults({ data }: { data: Record<string, unknown> }) {
  const rows = (data.rows as Record<string, unknown>[]) ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(rows, {
    ticker: (r) => (r.Ticker != null ? String(r.Ticker) : null),
    tf: (r) => (r.Timeframe != null ? String(r.Timeframe) : null),
    strategy: (r) => (r.Strategy != null ? String(r.Strategy) : null),
    return_pct: (r) => (r['Return %'] != null ? Number(r['Return %']) : null),
    sharpe: (r) => (r.Sharpe != null ? Number(r.Sharpe) : null),
    status: (r) => (r.Status != null ? String(r.Status) : null),
  })
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        {String(data.count ?? rows.length)} combos · {String(data.ticker_count ?? '—')} tickers · {String(data.strategy_count ?? '—')} strategies · {String(data.market ?? '')}
      </p>
      <DataTable>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
            <SortableTh active={sortKey === 'tf'} direction={sortDir} onSort={() => handleSort('tf')}>TF</SortableTh>
            <SortableTh active={sortKey === 'strategy'} direction={sortDir} onSort={() => handleSort('strategy')}>Strategy</SortableTh>
            <SortableTh active={sortKey === 'return_pct'} direction={sortDir} onSort={() => handleSort('return_pct')}>Return %</SortableTh>
            <SortableTh active={sortKey === 'sharpe'} direction={sortDir} onSort={() => handleSort('sharpe')}>Sharpe</SortableTh>
            <SortableTh active={sortKey === 'status'} direction={sortDir} onSort={() => handleSort('status')}>Status</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              <Td>{String(r.Ticker)}</Td>
              <Td>{String(r.Timeframe)}</Td>
              <Td className="max-w-[10rem] truncate">{String(r.Strategy)}</Td>
              <Td>{r['Return %'] != null ? Number(r['Return %']).toFixed(2) : '—'}</Td>
              <Td>{r.Sharpe != null ? Number(r.Sharpe).toFixed(2) : '—'}</Td>
              <Td>{String(r.Status)}</Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  )
}

function ScreenerResults({ data }: { data: Record<string, unknown> }) {
  const signals = (data.signals as Record<string, unknown>[]) ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(signals, {
    ticker: (s) => (s.Ticker != null ? String(s.Ticker) : null),
    tf: (s) => (s.Timeframe != null ? String(s.Timeframe) : null),
    close: (s) => (s.Close != null ? Number(s.Close) : null),
    signal: (s) => (s.Signal != null ? String(s.Signal) : null),
  })
  if (!signals.length) return <p className="text-slate-500">No signals matched entry rules.</p>
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        {String(data.count ?? signals.length)} hits · preset {String(data.screener_preset ?? '—')} · {String(data.market ?? '')}
      </p>
      <DataTable>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
            <SortableTh active={sortKey === 'tf'} direction={sortDir} onSort={() => handleSort('tf')}>TF</SortableTh>
            <SortableTh active={sortKey === 'close'} direction={sortDir} onSort={() => handleSort('close')}>Close</SortableTh>
            <SortableTh active={sortKey === 'signal'} direction={sortDir} onSort={() => handleSort('signal')}>Signal</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s, i) => (
            <tr key={i}>
              <Td>{String(s.Ticker)}</Td>
              <Td>{String(s.Timeframe)}</Td>
              <Td>{String(s.Close)}</Td>
              <Td>{String(s.Signal)}</Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  )
}

function PresetsPanel({ data }: { data: Record<string, unknown> }) {
  const presets = (data.presets as Record<string, { description?: string; recommended_timeframe?: string }>) ?? {}
  const categories = (data.categories as Record<string, string[]>) ?? {}
  const encyclopedia = data.encyclopedia as
    | {
        hubs?: Array<{
          hub: string
          count: number
          sections: Array<{ id: string; title: string; guide?: string | null; extra?: string | null }>
        }>
        section_count?: number
        hub_count?: number
        overview?: string
        workflows?: string
        when_to_use?: string
        strategy_lab_detail?: string
      }
    | undefined

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">
        {encyclopedia?.section_count ?? 0} hub sections across {encyclopedia?.hub_count ?? 0} hubs
        {' · '}
        {Object.keys(presets).length} builder presets for {String(data.market)} ({String(data.asset_class ?? '')})
      </p>

      {encyclopedia?.hubs?.length ? (
        <div className="space-y-4">
          <h4 className="font-medium text-white">All hubs & strategies</h4>
          {encyclopedia.overview && (
            <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium text-slate-200">App overview</summary>
              <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{encyclopedia.overview}</pre>
            </details>
          )}
          {encyclopedia.workflows && (
            <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium text-slate-200">Workflows</summary>
              <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{encyclopedia.workflows}</pre>
            </details>
          )}
          {encyclopedia.when_to_use && (
            <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium text-slate-200">When to use what</summary>
              <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{encyclopedia.when_to_use}</pre>
            </details>
          )}
          {encyclopedia.hubs.map((hub) => (
            <div key={hub.hub}>
              <h5 className="mb-2 text-sm font-semibold text-slate-100">
                {hub.hub}{' '}
                <span className="font-normal text-slate-500">({hub.count})</span>
              </h5>
              <div className="space-y-2">
                {hub.sections.map((section) => (
                  <details
                    key={section.id}
                    className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2"
                  >
                    <summary className="cursor-pointer text-sm font-medium text-slate-200">
                      {section.title}
                    </summary>
                    <p className="mt-1 text-[11px] text-slate-600">{section.id}</p>
                    {section.guide ? (
                      <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
                        {section.guide}
                      </pre>
                    ) : (
                      <p className="mt-2 text-xs text-slate-500">No guide available yet.</p>
                    )}
                    {section.extra && (
                      <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
                        {section.extra}
                      </pre>
                    )}
                  </details>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {encyclopedia?.strategy_lab_detail && (
        <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-slate-200">Strategy Lab & tools detail</summary>
          <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
            {encyclopedia.strategy_lab_detail}
          </pre>
        </details>
      )}

      {Object.entries(categories).map(([cat, names]) => (
        <div key={cat}>
          <h4 className="mb-2 font-medium capitalize text-white">
            Builder presets — {cat.replace(/_/g, ' ')}
          </h4>
          <ul className="space-y-2">
            {names.map((name) => (
              <li key={name} className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2 text-sm">
                <span className="font-medium text-slate-200">{name}</span>
                {presets[name]?.description && (
                  <p className="mt-1 text-slate-500">{presets[name].description}</p>
                )}
                {presets[name]?.recommended_timeframe && (
                  <p className="text-xs text-slate-600">TF: {presets[name].recommended_timeframe}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
