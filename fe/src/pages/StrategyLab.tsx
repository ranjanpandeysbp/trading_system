import { useState } from 'react'
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
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { StatCard } from '../components/ui/StatCard'
import { DataTable, Td, Th } from '../components/ui/Table'

const TABS = [
  { id: 'builder', label: 'Builder & Tester', icon: Beaker },
  { id: 'multi_combo', label: 'Multi-Combo', icon: Grid3X3 },
  { id: 'screener', label: 'Advanced Screener', icon: ListFilter },
  { id: 'presets', label: 'Presets', icon: BookOpen },
] as const

type TabId = (typeof TABS)[number]['id']

const TFS = ['5m', '15m', '1h', '4h', '1d']

function parseTickers(raw: string) {
  return raw.split(/[,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean)
}

export default function StrategyLab() {
  const [tab, setTab] = useState<TabId>('builder')
  const [ticker, setTicker] = useState('RELIANCE')
  const [tickers, setTickers] = useState('RELIANCE, TCS, INFY')
  const [timeframe, setTimeframe] = useState('1d')
  const [selectedTfs, setSelectedTfs] = useState<string[]>(['1d'])
  const [preset, setPreset] = useState('')
  const [strategies, setStrategies] = useState('')
  const [error, setError] = useState('')

  useQuery({ queryKey: ['sl-sections'], queryFn: fetchStrategyLabSections })
  const presetsQuery = useQuery({ queryKey: ['sl-presets'], queryFn: () => fetchStrategyLabPresets() })

  const presetNames = Object.keys((presetsQuery.data as { presets?: Record<string, unknown> })?.presets ?? {})

  const mutation = useMutation({
    mutationFn: async () => {
      switch (tab) {
        case 'builder':
          return runStrategyLabBacktest({
            ticker,
            timeframe,
            preset_name: preset || undefined,
            capital: 100_000,
          })
        case 'multi_combo': {
          const list = parseTickers(tickers)
          if (!list.length) throw new Error('Enter at least one ticker')
          return runStrategyLabMultiCombo({
            tickers: list,
            timeframes: selectedTfs,
            strategies: strategies
              ? strategies.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean)
              : undefined,
          })
        }
        case 'screener': {
          const list = parseTickers(tickers)
          if (!list.length) throw new Error('Enter at least one ticker')
          return runStrategyLabScreener({ tickers: list, timeframes: selectedTfs })
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

  const result = tab === 'presets' ? presetsQuery.data : mutation.data
  const loading = tab === 'presets' ? presetsQuery.isLoading : mutation.isPending

  return (
    <div>
      <PageHeader
        title="Strategy Lab"
        description="Build & backtest custom rules · Multi-combo scanner · Advanced screener · Preset encyclopedia"
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

      {tab !== 'presets' && (
        <Card className="mb-4">
          {tab === 'builder' && (
            <div className="grid gap-4 sm:grid-cols-3">
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
              <FormField label="Preset (optional)">
                <Select value={preset} onChange={(e) => setPreset(e.target.value)}>
                  <option value="">Custom / default RSI</option>
                  {presetNames.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </Select>
              </FormField>
            </div>
          )}

          {(tab === 'multi_combo' || tab === 'screener') && (
            <>
              <FormField label="Tickers (comma-separated)">
                <Textarea rows={2} value={tickers} onChange={(e) => setTickers(e.target.value)} />
              </FormField>
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
              {tab === 'multi_combo' && (
                <div className="mt-4">
                  <FormField label="Strategies (optional, comma-separated preset names)">
                    <Input
                      placeholder="Leave empty for top 5 presets"
                      value={strategies}
                      onChange={(e) => setStrategies(e.target.value)}
                    />
                  </FormField>
                </div>
              )}
            </>
          )}

          <Button className="mt-4" onClick={() => mutation.mutate()} disabled={loading}>
            {tab === 'builder' ? 'Run backtest' : tab === 'multi_combo' ? 'Run multi-combo' : 'Run screener'}
          </Button>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
        </Card>
      )}

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

function BuilderResults({ data }: { data: Record<string, unknown> }) {
  const metrics = (data.metrics as Record<string, number>) ?? {}
  return (
    <div className="space-y-4">
      <h3 className="font-semibold text-white">
        {String(data.ticker)} · {String(data.timeframe)} · {String(data.market)}
      </h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total return" value={`${metrics.total_return_pct?.toFixed(2) ?? '—'}%`} />
        <StatCard label="Sharpe" value={metrics.sharpe_ratio?.toFixed(2) ?? '—'} />
        <StatCard label="Max DD" value={`${metrics.max_drawdown_pct?.toFixed(2) ?? '—'}%`} />
        <StatCard label="Trades" value={String(data.trade_count ?? metrics.n_trades ?? '—')} />
      </div>
    </div>
  )
}

function ComboResults({ data }: { data: Record<string, unknown> }) {
  const rows = (data.rows as Record<string, unknown>[]) ?? []
  return (
    <DataTable>
      <thead>
        <tr>
          <Th>Ticker</Th>
          <Th>TF</Th>
          <Th>Strategy</Th>
          <Th>Return %</Th>
          <Th>Sharpe</Th>
          <Th>Status</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
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
  )
}

function ScreenerResults({ data }: { data: Record<string, unknown> }) {
  const signals = (data.signals as Record<string, unknown>[]) ?? []
  if (!signals.length) return <p className="text-slate-500">No signals matched entry rules.</p>
  return (
    <DataTable>
      <thead>
        <tr>
          <Th>Ticker</Th>
          <Th>TF</Th>
          <Th>Close</Th>
          <Th>Signal</Th>
        </tr>
      </thead>
      <tbody>
        {signals.map((s, i) => (
          <tr key={i}>
            <Td>{String(s.Ticker)}</Td>
            <Td>{String(s.Timeframe)}</Td>
            <Td>{String(s.Close)}</Td>
            <Td>{String(s.Signal)}</Td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  )
}

function PresetsPanel({ data }: { data: Record<string, unknown> }) {
  const presets = (data.presets as Record<string, { description?: string; recommended_timeframe?: string }>) ?? {}
  const categories = (data.categories as Record<string, string[]>) ?? {}
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">
        {Object.keys(presets).length} presets for {String(data.market)}
      </p>
      {Object.entries(categories).map(([cat, names]) => (
        <div key={cat}>
          <h4 className="mb-2 font-medium capitalize text-white">{cat.replace(/_/g, ' ')}</h4>
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
