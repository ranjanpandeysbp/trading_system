import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { Play } from 'lucide-react'
import { apiErrorMessage, fetchStrategyCategories, runBacktest } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { StatCard } from '../components/ui/StatCard'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert } from '../components/ui/Feedback'
import { DataTable, Th, Td } from '../components/ui/Table'
import { StrategySelect } from '../components/strategies/StrategySelect'

const PERIODS_BY_TIMEFRAME: Record<string, { value: string; label: string }[]> = {
  '1m': [
    { value: '7d', label: '7 days' },
    { value: '30d', label: '30 days' },
  ],
  '3m': [
    { value: '30d', label: '30 days' },
    { value: '60d', label: '60 days' },
  ],
  '5m': [
    { value: '30d', label: '30 days' },
    { value: '60d', label: '60 days' },
    { value: '90d', label: '90 days' },
  ],
  '15m': [
    { value: '30d', label: '30 days' },
    { value: '60d', label: '60 days' },
    { value: '90d', label: '90 days' },
  ],
  '30m': [
    { value: '30d', label: '30 days' },
    { value: '60d', label: '60 days' },
    { value: '90d', label: '90 days' },
  ],
  '1h': [
    { value: '60d', label: '60 days' },
    { value: '90d', label: '90 days' },
    { value: '180d', label: '180 days' },
  ],
  '4h': [
    { value: '90d', label: '90 days' },
    { value: '180d', label: '180 days' },
    { value: '1y', label: '1 year' },
  ],
  '1d': [
    { value: '1y', label: '1 year' },
    { value: '2y', label: '2 years' },
    { value: '5y', label: '5 years' },
  ],
  '1wk': [
    { value: '2y', label: '2 years' },
    { value: '5y', label: '5 years' },
    { value: '10y', label: '10 years' },
  ],
}

const DEFAULT_PERIOD: Record<string, string> = {
  '1m': '7d',
  '3m': '30d',
  '5m': '60d',
  '15m': '60d',
  '30m': '60d',
  '1h': '90d',
  '4h': '180d',
  '1d': '2y',
  '1wk': '5y',
}

export default function Backtester() {
  const [searchParams] = useSearchParams()
  const [ticker, setTicker] = useState('RELIANCE')
  const [strategy, setStrategy] = useState(searchParams.get('strategy') ?? '')
  const [timeframe, setTimeframe] = useState('1d')
  const [period, setPeriod] = useState('2y')
  const [costsPct, setCostsPct] = useState(0.0008)
  const [result, setResult] = useState<{
    period: string
    bars_evaluated: number
    signal_count: number
    benchmark_ticker?: string | null
    summary?: string | null
    stats: {
      num_trades: number
      win_rate_pct: number | null
      total_return_pct: number
      avg_return_per_trade_pct: number | null
      max_drawdown_pct: number
      trades: Array<{ pnl_pct: number }>
    }
    recent_signals: Array<{ timestamp: string; close: number; action: string }>
  } | null>(null)
  const [error, setError] = useState('')

  const { data: categories } = useQuery({ queryKey: ['strategy-categories'], queryFn: fetchStrategyCategories })
  const strategies = categories?.flatMap((c) => c.strategies)

  const selected = strategies?.find((s) => s.id === strategy)
  const timeframes = selected?.timeframes ?? ['1d', '15m', '5m', '3m', '1m']
  const periodOptions = PERIODS_BY_TIMEFRAME[timeframe] ?? PERIODS_BY_TIMEFRAME['1d']

  useEffect(() => {
    const fromUrl = searchParams.get('strategy')
    if (fromUrl) setStrategy(fromUrl)
  }, [searchParams])

  useEffect(() => {
    if (!selected?.timeframes.length) return
    setTimeframe((current) => (selected.timeframes.includes(current) ? current : selected.timeframes[0]))
  }, [strategy, selected])

  useEffect(() => {
    const defaultPeriod = DEFAULT_PERIOD[timeframe] ?? '1y'
    setPeriod((current) => {
      const allowed = PERIODS_BY_TIMEFRAME[timeframe]?.map((p) => p.value) ?? []
      return allowed.includes(current) ? current : defaultPeriod
    })
  }, [timeframe])

  const backtestMutation = useMutation({
    mutationFn: runBacktest,
    onSuccess: (data) => { setResult(data); setError('') },
    onError: (e: unknown) => setError(apiErrorMessage(e)),
  })

  const handleRun = () => {
    if (!ticker || !strategy) { setError('Select ticker and strategy'); return }
    backtestMutation.mutate({ ticker, strategy, timeframe, period, costs_pct: costsPct })
  }

  const chartData = result?.stats.trades?.slice(-20).map((t, i) => ({ trade: i + 1, pnl: t.pnl_pct })) ?? []

  return (
    <div>
      <PageHeader
        title="Backtester"
        description="Evaluate strategy signals on historical data with configurable period and transaction costs"
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h3 className="mb-5 font-semibold text-white">Backtest Configuration</h3>

          <FormField label="Ticker">
            <Input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="RELIANCE" />
          </FormField>
          <FormField label="Strategy">
            <StrategySelect value={strategy} onChange={setStrategy} categories={categories} />
          </FormField>
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {timeframes.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
            </Select>
          </FormField>
          <FormField label="Backtest Period">
            <Select value={period} onChange={(e) => setPeriod(e.target.value)}>
              {periodOptions.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </Select>
          </FormField>
          <FormField label="Round-trip cost % (e.g. 0.0008 = 0.08%)">
            <Input type="number" step="0.0001" value={costsPct} onChange={(e) => setCostsPct(parseFloat(e.target.value))} />
          </FormField>

          <Button onClick={handleRun} disabled={backtestMutation.isPending} className="w-full sm:w-auto">
            <Play size={16} />
            {backtestMutation.isPending ? 'Running...' : 'Run Backtest'}
          </Button>
          {error && <Alert type="error">{error}</Alert>}
        </Card>

        {result && (
          <Card>
            <h3 className="mb-4 font-semibold text-white">Results</h3>
            <p className="mb-4 text-sm text-slate-500">
              {result.period} · {result.bars_evaluated} bars · {result.signal_count} signals
              {result.benchmark_ticker ? ` · benchmark ${result.benchmark_ticker}` : ''}
            </p>
            {result.summary && (
              <Alert type={result.stats.num_trades > 0 ? 'success' : 'error'}>
                {result.summary}
              </Alert>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <StatCard label="Trades" value={result.stats.num_trades} />
              <StatCard label="Win Rate" value={`${result.stats.win_rate_pct ?? '—'}%`} />
              <StatCard
                label="Total Return"
                value={`${result.stats.total_return_pct}%`}
                trend={result.stats.total_return_pct >= 0 ? 'up' : 'down'}
              />
              <StatCard label="Max Drawdown" value={`${result.stats.max_drawdown_pct}%`} trend="down" />
            </div>
          </Card>
        )}
      </div>

      {chartData.length > 0 && (
        <Card className="mt-6">
          <h3 className="mb-4 font-semibold text-white">Trade P&L (%)</h3>
          <div className="h-[240px] sm:h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="trade" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '12px',
                  fontSize: '13px',
                }}
              />
              <Bar dataKey="pnl" fill="url(#barGradient)" radius={[6, 6, 0, 0]} />
              <defs>
                <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" />
                  <stop offset="100%" stopColor="#6366f1" />
                </linearGradient>
              </defs>
            </BarChart>
          </ResponsiveContainer>
          </div>
        </Card>
      )}

      {result && result.recent_signals.length > 0 && (
        <Card className="mt-6">
          <h3 className="mb-4 font-semibold text-white">Recent Signals</h3>
          <DataTable>
            <thead>
              <tr>
                <Th>Time</Th>
                <Th>Close</Th>
                <Th>Action</Th>
              </tr>
            </thead>
            <tbody>
              {result.recent_signals.map((s, i) => (
                <tr key={i} className="hover:bg-slate-800/20">
                  <Td className="text-slate-400">{s.timestamp}</Td>
                  <Td className="tabular-nums">₹{s.close}</Td>
                  <Td><Badge action={s.action} /></Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Card>
      )}
    </div>
  )
}
