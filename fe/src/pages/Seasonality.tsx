import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CalendarRange } from 'lucide-react'
import { apiErrorMessage, runSeasonalityAnalyze } from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { StatCard } from '../components/ui/StatCard'
import { DataTable, SortableTh, Td, useSort } from '../components/ui/Table'

function parseTickers(raw: string) {
  return raw.split(/[,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean)
}

export default function Seasonality() {
  const [tickers, setTickers] = useState('RELIANCE, TCS, INFY, HDFCBANK')
  const [years, setYears] = useState(10)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () => {
      const list = parseTickers(tickers)
      if (!list.length) throw new Error('Enter at least one ticker')
      return runSeasonalityAnalyze({ tickers: list, years })
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => setError(''),
  })

  const data = mutation.data as Record<string, unknown> | undefined
  const results = (data?.results as Record<string, unknown>[]) ?? []

  return (
    <div>
      <PageHeader
        title="Seasonality"
        description="Monthly return patterns · seasonal signals · historical backtest (up to 8 tickers)"
      />

      <Card className="mb-4">
        <FormField label="Tickers (comma-separated, max 8)">
          <Textarea rows={2} value={tickers} onChange={(e) => setTickers(e.target.value)} />
        </FormField>
        <div className="mt-4 max-w-xs">
          <FormField label="Lookback years">
            <Input
              type="number"
              min={3}
              max={20}
              value={years}
              onChange={(e) => setYears(Number(e.target.value))}
            />
          </FormField>
        </div>
        <Button className="mt-4" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          <span className="inline-flex items-center gap-2">
            <CalendarRange size={16} />
            Analyze seasonality
          </span>
        </Button>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      {mutation.isPending && <Loading message="Downloading history and computing monthly stats…" />}

      {!mutation.isPending && results.map((item) => (
        <Card key={String(item.symbol)} className="mb-4">
          <SymbolSeasonality item={item} />
        </Card>
      ))}

      {data && (
        <AskAIPanel
          context={buildAskContext('Seasonality', data)}
          section="seasonality/analyze"
        />
      )}
    </div>
  )
}

function SymbolSeasonality({ item }: { item: Record<string, unknown> }) {
  const symbol = String(item.symbol)
  if (item.error) {
    return <p className="text-rose-400">{symbol}: {String(item.error)}</p>
  }

  const stats = (item.stats as Record<string, unknown>[]) ?? []
  const bt = (item.backtest as Record<string, number>) ?? {}
  const signals = (item.signals as Record<string, unknown>[]) ?? []
  const bullish = signals.filter((s) => String(s.Signal ?? s.signal).toUpperCase().includes('BUY'))

  const { sorted: sortedStats, sortKey: statsSortKey, sortDir: statsSortDir, handleSort: handleStatsSort } = useSort(
    stats,
    {
      month: (r) => String(r.MonthName ?? r.Month ?? ''),
      avg_return: (r) => (r.AvgReturn != null ? Number(r.AvgReturn) : null),
      win_rate: (r) => (r.WinRate != null ? Number(r.WinRate) : null),
      signal: (r) => {
        const sig = signals.find((s) => s.Month === r.Month)
        return sig ? String(sig.Signal ?? sig.signal ?? '') : ''
      },
    },
  )

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">{symbol}</h3>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Seasonal BT return" value={`${bt.total_return_pct?.toFixed(2) ?? '—'}%`} />
        <StatCard label="Win months" value={String(bullish.length)} />
        <StatCard label="Months analyzed" value={String(stats.length)} />
      </div>

      {stats.length > 0 && (
        <DataTable>
          <thead>
            <tr>
              <SortableTh active={statsSortKey === 'month'} direction={statsSortDir} onSort={() => handleStatsSort('month')}>Month</SortableTh>
              <SortableTh active={statsSortKey === 'avg_return'} direction={statsSortDir} onSort={() => handleStatsSort('avg_return')}>Avg return %</SortableTh>
              <SortableTh active={statsSortKey === 'win_rate'} direction={statsSortDir} onSort={() => handleStatsSort('win_rate')}>Win rate %</SortableTh>
              <SortableTh active={statsSortKey === 'signal'} direction={statsSortDir} onSort={() => handleStatsSort('signal')}>Signal</SortableTh>
            </tr>
          </thead>
          <tbody>
            {sortedStats.map((row, i) => {
              const month = String(row.MonthName ?? row.Month ?? i + 1)
              const sig = signals.find((s) => s.Month === row.Month)
              return (
                <tr key={month}>
                  <Td>{month}</Td>
                  <Td>{row.AvgReturn != null ? Number(row.AvgReturn).toFixed(2) : '—'}</Td>
                  <Td>{row.WinRate != null ? Number(row.WinRate).toFixed(1) : '—'}</Td>
                  <Td>{sig ? String(sig.Signal ?? sig.signal ?? '—') : '—'}</Td>
                </tr>
              )
            })}
          </tbody>
        </DataTable>
      )}
    </div>
  )
}
