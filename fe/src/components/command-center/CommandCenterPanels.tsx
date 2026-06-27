import { useState } from 'react'
import { TomorrowOutlookPanel } from '../market-pulse/MarketPulsePanels'
import { TickerInvestigationPanel } from '../technical-analysis/TechnicalAnalysisPanels'
import { Alert } from '../ui/Feedback'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { DataTable, Td, Th } from '../ui/Table'
import { StatCard } from '../ui/StatCard'

type Row = Record<string, unknown>

function verdictClass(verdict: string) {
  const v = verdict.toUpperCase()
  if (v.includes('BUY') || v.includes('BULL') || v.includes('LONG')) return 'text-emerald-400'
  if (v.includes('SELL') || v.includes('BEAR') || v.includes('SHORT') || v.includes('AVOID')) return 'text-rose-400'
  return 'text-amber-400'
}

function SummaryCard({ title, row }: { title: string; row: Row }) {
  const verdict = String(row.verdict ?? '—')
  const reasons = (row.reasons as string[]) ?? []
  const plan = row.trade_plan as Row | undefined

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{title}</p>
        <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(verdict)}`}>
          {row.ticker != null ? `${String(row.ticker)} · ` : ''}{verdict}
        </p>
        <div className="mt-3 flex flex-wrap gap-3 text-sm">
          {row.score != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Score: <strong>{Number(row.score).toFixed(1)}</strong>/10
            </span>
          )}
          {row.confidence_pct != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Confidence: <strong>{Number(row.confidence_pct).toFixed(0)}%</strong>
            </span>
          )}
          {row.direction != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Direction: <strong>{String(row.direction)}</strong>
            </span>
          )}
          {row.take_trade != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Take trade: <strong>{row.take_trade ? 'Yes' : 'No'}</strong>
            </span>
          )}
        </div>
        {row.summary != null && (
          <p className="mt-4 text-sm leading-relaxed text-slate-300">{String(row.summary)}</p>
        )}
        {row.action != null && String(row.action).trim() && (
          <p className="mt-2 text-sm text-slate-400">{String(row.action)}</p>
        )}
      </div>

      {reasons.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Engine breakdown</h4>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {reasons.map((r) => (
              <li key={r} className="flex gap-2">
                <span className="text-slate-500">•</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan && Object.keys(plan).length > 0 && (
        <Card className="!p-4">
          <h4 className="mb-3 text-sm font-semibold text-white">Trade plan</h4>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {plan.direction != null && <StatCard label="Direction" value={String(plan.direction)} />}
            {plan.stop_loss_pct != null && <StatCard label="Stop loss" value={`${plan.stop_loss_pct}%`} />}
            {plan.take_profit_pct != null && <StatCard label="Take profit" value={`${plan.take_profit_pct}%`} />}
            {plan.holding_period != null && (
              <StatCard label="Hold period" value={String(plan.holding_period)} />
            )}
          </div>
          {plan.exit_rule != null && (
            <p className="mt-3 text-sm text-slate-400">{String(plan.exit_rule)}</p>
          )}
        </Card>
      )}
    </div>
  )
}

function MegaAnalyserPanel({ data }: { data: Row }) {
  const recs = (data.recommendations as Row[]) ?? []
  const mega = (data.mega as Row | undefined) ?? recs[0]
  const summaries = (data.summaries as Row[]) ?? []
  const [filter, setFilter] = useState<'all' | 'trade' | 'error'>('all')
  const [idx, setIdx] = useState(0)

  if (recs.length > 1) {
    const rec = recs[idx] ?? recs[0]
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap gap-2">
          {recs.map((r, i) => (
            <Chip key={String(r.ticker)} selected={idx === i} onClick={() => setIdx(i)}>
              {String(r.ticker)}
            </Chip>
          ))}
        </div>
        <SummaryCard title="Mega Analyser verdict" row={rec} />
        {summaries.length > 0 && (
          <EngineSummaryTable summaries={summaries} filter={filter} setFilter={setFilter} ticker={String(rec.ticker)} />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {mega && <SummaryCard title="Mega Analyser verdict" row={mega} />}
      {summaries.length > 0 && (
        <EngineSummaryTable summaries={summaries} filter={filter} setFilter={setFilter} />
      )}
    </div>
  )
}

function EngineSummaryTable({
  summaries,
  filter,
  setFilter,
  ticker,
}: {
  summaries: Row[]
  filter: 'all' | 'trade' | 'error'
  setFilter: (f: 'all' | 'trade' | 'error') => void
  ticker?: string
}) {
  const rows = ticker
    ? summaries.filter((s) => String(s.ticker) === ticker)
    : summaries
  const filtered = rows.filter((s) => {
    if (filter === 'trade') return s.signal_type === 'trade'
    if (filter === 'error') return s.signal_type === 'error'
    return true
  })

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>All ({rows.length})</Chip>
        <Chip selected={filter === 'trade'} onClick={() => setFilter('trade')}>Actionable</Chip>
        <Chip selected={filter === 'error'} onClick={() => setFilter('error')}>Errors</Chip>
      </div>
      <DataTable>
        <thead>
          <tr>
            <Th>Ticker</Th>
            <Th>Engine</Th>
            <Th>TF</Th>
            <Th>Score</Th>
            <Th>Verdict</Th>
            <Th>Summary</Th>
          </tr>
        </thead>
        <tbody>
          {filtered.slice(0, 40).map((s, i) => (
            <tr key={`${String(s.tab)}-${String(s.timeframe)}-${i}`}>
              <Td>{String(s.ticker ?? '—')}</Td>
              <Td>{String(s.tab ?? '—')}</Td>
              <Td>{String(s.timeframe ?? '—')}</Td>
              <Td className={verdictClass(String(s.verdict ?? ''))}>
                {s.score != null ? Number(s.score).toFixed(1) : '—'}
              </Td>
              <Td>{String(s.verdict ?? '—')}</Td>
              <Td className="max-w-xs truncate text-slate-400">{String(s.summary ?? '—')}</Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  )
}

function BuySellPanel({ data }: { data: Row }) {
  const recs = (data.recommendations as Row[]) ?? []
  const [idx, setIdx] = useState(0)

  if (!recs.length) {
    return <p className="text-sm text-slate-500">No recommendations returned.</p>
  }

  const rec = recs[idx] ?? recs[0]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {recs.map((r, i) => (
          <Chip key={String(r.ticker)} selected={idx === i} onClick={() => setIdx(i)}>
            {String(r.ticker)}
          </Chip>
        ))}
      </div>
      <SummaryCard title={`Buy / Sell · ${String(data.asset_class ?? 'india')}`} row={rec} />
    </div>
  )
}

export function CommandCenterResults({ tab, data }: { tab: string; data: Row }) {
  if (data.error && tab !== 'investigation') {
    return <Alert type="error">{String(data.error)}</Alert>
  }

  switch (tab) {
    case 'tomorrow_outlook':
      return <TomorrowOutlookPanel data={data} />
    case 'mega_analyser':
      return <MegaAnalyserPanel data={data} />
    case 'buy_sell':
      return <BuySellPanel data={data} />
    case 'investigation':
      return <TickerInvestigationPanel data={data} />
    default:
      return <p className="text-sm text-slate-500">Unknown section.</p>
  }
}
