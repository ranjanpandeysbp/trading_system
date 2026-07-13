import { Fragment, useState } from 'react'
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

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

const SR_EVENT_LABEL: Record<string, string> = {
  RESISTANCE_BREAK: '🚀 Breaking resistance',
  SUPPORT_BREAK: '🔻 Breaking support',
  RANGE: '↔️ In range',
  NONE: '—',
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
        {row.meaning != null && String(row.meaning).trim() && (
          <p className="mt-2 text-sm text-slate-400">{String(row.meaning)}</p>
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
            {plan.expected_profit_pct != null && (
              <StatCard label="Expected profit" value={`${plan.expected_profit_pct}%`} />
            )}
            {plan.confidence_pct != null && (
              <StatCard label="Plan confidence" value={`${plan.confidence_pct}%`} />
            )}
            {plan.holding_period != null && (
              <StatCard label="Hold period" value={String(plan.holding_period)} />
            )}
          </div>
          {plan.exit_rule != null && (
            <p className="mt-3 text-sm text-slate-400">{String(plan.exit_rule)}</p>
          )}
          {plan.max_hold_exit != null && String(plan.max_hold_exit).trim() && (
            <p className="mt-1 text-xs text-slate-500">Time stop: {String(plan.max_hold_exit)}</p>
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
  const [filter, setFilter] = useState<'all' | 'trade' | 'watch' | 'error'>('all')
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
  filter: 'all' | 'trade' | 'watch' | 'error'
  setFilter: (f: 'all' | 'trade' | 'watch' | 'error') => void
  ticker?: string
}) {
  const [expanded, setExpanded] = useState<number | null>(null)
  const rows = ticker
    ? summaries.filter((s) => String(s.ticker) === ticker)
    : summaries
  const filtered = rows.filter((s) => {
    if (filter === 'trade') return s.signal_type === 'trade'
    if (filter === 'watch') return s.signal_type === 'no_trade' || s.signal_type === 'watch'
    if (filter === 'error') return s.signal_type === 'error'
    return true
  })

  const actionable = rows.filter((s) => s.signal_type === 'trade')
  const best = (actionable.length ? actionable : rows).reduce<Row | null>((top, s) => {
    if (!top) return s
    return Number(s.score ?? 0) > Number(top.score ?? 0) ? s : top
  }, null)
  const bestPlan = (best?.trade_plan as Row) ?? {}

  return (
    <div>
      {best && (
        <div className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-wider text-emerald-400">
            {actionable.length ? 'Best actionable' : 'Best result'}
          </p>
          <p className="mt-1 text-sm text-white">
            <strong>{String(best.ticker ?? '—')}</strong> · {String(best.timeframe ?? '—')} · {String(best.tab ?? '—')} ·
            {' '}Score {fmtNum(best.score, 1)}/10
          </p>
          <p className="mt-1 text-sm text-slate-300">{String(best.recommendation ?? best.verdict ?? '—')}</p>
          {(bestPlan.stop_loss_pct != null || bestPlan.take_profit_pct != null || bestPlan.expected_profit_pct != null) && (
            <p className="mt-1 text-xs text-slate-400">
              SL -{fmtNum(bestPlan.stop_loss_pct)}% · TP +{fmtNum(bestPlan.take_profit_pct)}% · Exp +{fmtNum(bestPlan.expected_profit_pct)}%
            </p>
          )}
        </div>
      )}
      <div className="mb-3 flex flex-wrap gap-2">
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>All ({rows.length})</Chip>
        <Chip selected={filter === 'trade'} onClick={() => setFilter('trade')}>Actionable</Chip>
        <Chip selected={filter === 'watch'} onClick={() => setFilter('watch')}>No signal</Chip>
        <Chip selected={filter === 'error'} onClick={() => setFilter('error')}>Errors</Chip>
      </div>
      <DataTable minWidth={900}>
        <thead>
          <tr>
            <Th>Ticker</Th>
            <Th>Engine</Th>
            <Th>TF</Th>
            <Th>Score</Th>
            <Th>Verdict</Th>
            <Th>Recommendation</Th>
            <Th>SL %</Th>
            <Th>TP %</Th>
            <Th>Exp %</Th>
          </tr>
        </thead>
        <tbody>
          {filtered.slice(0, 40).map((s, i) => {
            const plan = (s.trade_plan as Row) ?? {}
            const reasons = (s.reasons as string[]) ?? []
            const isTrade = s.signal_type === 'trade'
            return (
              <Fragment key={`${String(s.tab)}-${String(s.timeframe)}-${i}`}>
                <tr
                  className={reasons.length ? 'cursor-pointer hover:bg-slate-800/30' : undefined}
                  onClick={reasons.length ? () => setExpanded(expanded === i ? null : i) : undefined}
                >
                  <Td>{String(s.ticker ?? '—')}</Td>
                  <Td>{String(s.tab ?? '—')}</Td>
                  <Td>{String(s.timeframe ?? '—')}</Td>
                  <Td className={verdictClass(String(s.verdict ?? ''))}>
                    {s.score != null ? Number(s.score).toFixed(1) : '—'}
                  </Td>
                  <Td>{String(s.verdict ?? '—')}</Td>
                  <Td className="max-w-xs truncate text-slate-400">{String(s.recommendation ?? s.summary ?? '—')}</Td>
                  <Td>{isTrade ? fmtNum(plan.stop_loss_pct) : '—'}</Td>
                  <Td>{isTrade ? fmtNum(plan.take_profit_pct) : '—'}</Td>
                  <Td>{isTrade ? fmtNum(plan.expected_profit_pct) : '—'}</Td>
                </tr>
                {expanded === i && reasons.length > 0 && (
                  <tr>
                    <td colSpan={9} className="border-b border-slate-800/40 bg-slate-900/30 px-4 py-3">
                      <ul className="space-y-1 text-xs text-slate-300">
                        {reasons.map((r, ri) => <li key={ri}>• {r}</li>)}
                      </ul>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
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
      {recs.length > 1 && (
        <DataTable minWidth={720}>
          <thead>
            <tr>
              <Th>Ticker</Th><Th>Take trade?</Th><Th>Verdict</Th><Th>Score</Th>
              <Th>Confidence</Th><Th>SL %</Th><Th>TP %</Th><Th>Engines</Th>
            </tr>
          </thead>
          <tbody>
            {recs.map((r, i) => (
              <tr
                key={String(r.ticker)}
                className={`cursor-pointer hover:bg-slate-800/30 ${idx === i ? 'bg-slate-800/40' : ''}`}
                onClick={() => setIdx(i)}
              >
                <Td className="font-medium text-white">{String(r.ticker)}</Td>
                <Td>{r.take_trade ? '✅' : '❌'}</Td>
                <Td className={verdictClass(String(r.verdict ?? ''))}>{String(r.verdict ?? '—')}</Td>
                <Td>{fmtNum(r.score, 1)}</Td>
                <Td>{fmtNum(r.confidence_pct, 0)}%</Td>
                <Td>{fmtNum(r.sl_pct)}</Td>
                <Td>{fmtNum(r.tp_pct)}</Td>
                <Td>{String(r.engine_count ?? '—')}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
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

function MomentumPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const r = results[idx] ?? results[0]
  const combo = r.fundamentals_combo as Row | undefined
  const action = (r.actionability as Row) ?? {}
  const perTf = (r.per_tf as Row[]) ?? []
  const upPct = r.breakout_up_pct

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Momentum · {String(r.ticker)}</p>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(r.overall_direction ?? ''))}`}>
              {String(r.overall_direction ?? '—')}
            </p>
            {action.reason != null && (
              <p className="mt-2 text-sm text-slate-300"><strong>Verdict:</strong> {String(action.reason)}</p>
            )}
            {combo && (
              <div className="mt-2 text-sm text-slate-400">
                <p>{String(combo.note ?? '')}</p>
                <p className="text-xs text-slate-500">Technical-only confidence was {fmtNum(r.technical_confidence_pct, 0)}%.</p>
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Direction" value={String(r.overall_direction ?? '—')} />
            <StatCard label="Strength" value={String(r.overall_strength ?? '—')} />
            <StatCard label="Momentum" value={String(r.overall_momentum_change ?? '—')} />
            <StatCard
              label={upPct != null ? 'Breakout odds' : 'Confidence continues'}
              value={upPct != null ? `↑${fmtNum(upPct, 0)}% / ↓${fmtNum(r.breakout_down_pct, 0)}%` : `${fmtNum(r.confidence_continue_pct, 0)}%`}
            />
          </div>

          {r.alignment != null && <p className="text-sm text-slate-400">{String(r.alignment)}</p>}

          {((r.reasons as string[]) ?? []).length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Engine breakdown</h4>
              <ul className="space-y-1.5 text-sm text-slate-300">
                {(r.reasons as string[]).map((rr, i) => (
                  <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{rr}</li>
                ))}
              </ul>
            </div>
          )}

          {perTf.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Per-timeframe breakdown</h4>
              <DataTable minWidth={960}>
                <thead>
                  <tr>
                    <Th>TF</Th><Th>Direction</Th><Th>Strength</Th><Th>Momentum</Th><Th>S/R Event</Th>
                    <Th>ADX</Th><Th>ADX Δ</Th><Th>RSI</Th><Th>RSI zone</Th><Th>MACD hist</Th><Th>ROC %</Th>
                    <Th>Vol x</Th><Th>Conf %</Th><Th>Breakout ↑/↓ %</Th>
                  </tr>
                </thead>
                <tbody>
                  {perTf.map((tf, i) => (
                    <tr key={i}>
                      <Td>{String(tf.timeframe)}</Td>
                      <Td className={verdictClass(String(tf.trend_direction ?? ''))}>{String(tf.trend_direction ?? '—')}</Td>
                      <Td>{String(tf.strength ?? '—')}</Td>
                      <Td>{String(tf.momentum_change ?? '—')}</Td>
                      <Td>{SR_EVENT_LABEL[String(tf.breakout_event ?? 'NONE')] ?? '—'}</Td>
                      <Td>{fmtNum(tf.adx)}</Td>
                      <Td>{fmtNum(tf.adx_delta)}</Td>
                      <Td>{fmtNum(tf.rsi)}</Td>
                      <Td>{String(tf.rsi_zone ?? '—')}</Td>
                      <Td>{fmtNum(tf.macd_hist)}</Td>
                      <Td>{fmtNum(tf.roc_pct)}</Td>
                      <Td>{fmtNum(tf.volume_ratio)}</Td>
                      <Td>{fmtNum(tf.confidence_continue_pct, 0)}</Td>
                      <Td>{tf.breakout_up_pct != null ? `${fmtNum(tf.breakout_up_pct, 0)}/${fmtNum(tf.breakout_down_pct, 0)}` : '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function EmaPositionPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const r = results[idx] ?? results[0]
  const action = (r.actionability as Row) ?? {}
  const combo = r.fundamentals_combo as Row | undefined
  const ns = r.next_support as Row | undefined
  const nr = r.next_resistance as Row | undefined
  const emaSummary = (r.ema_summary as Row[]) ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${String(res.timeframe)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)} · {String(res.timeframe ?? '')}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              EMA Position · {String(r.ticker)} · {String(r.timeframe ?? '')}
            </p>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(action.bucket ?? ''))}`}>
              {String(action.bucket ?? '—')}{action.direction != null ? ` · ${String(action.direction)}` : ''}
            </p>
            {r.note != null && String(r.note).trim() !== '' && (
              <p className="mt-2 text-sm text-amber-300">{String(r.note)}</p>
            )}
            {action.reason != null && (
              <p className="mt-2 text-sm text-slate-300"><strong>Verdict:</strong> {String(action.reason)}</p>
            )}
            {combo && (
              <div className="mt-2 text-sm text-slate-400">
                <p>{String(combo.note ?? '')}</p>
                <p className="text-xs text-slate-500">Technical-only confidence was {fmtNum(r.technical_confidence_pct, 0)}%.</p>
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label="Last price" value={fmtNum(r.last_price, 4)} />
            <StatCard label="Next support" value={ns ? fmtNum(ns.price, 4) : '—'} />
            <StatCard label="Next resistance" value={nr ? fmtNum(nr.price, 4) : '—'} />
          </div>

          {emaSummary.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">EMA breakdown</h4>
              <DataTable minWidth={720}>
                <thead>
                  <tr>
                    <Th>EMA</Th><Th>Status@From</Th><Th>Status@To</Th><Th>Verdict</Th>
                    <Th># Crossings</Th><Th>EMA value now</Th><Th>Dist %</Th>
                  </tr>
                </thead>
                <tbody>
                  {emaSummary.map((e, i) => (
                    <tr key={i}>
                      <Td>{String(e.ema_period)}</Td>
                      <Td>{String(e.status_from ?? '—')}</Td>
                      <Td>{String(e.status_to ?? '—')}</Td>
                      <Td className={verdictClass(String(e.verdict ?? ''))}>{String(e.verdict_label ?? e.verdict ?? '—')}</Td>
                      <Td>{String(e.crossover_count ?? 0)}</Td>
                      <Td>{fmtNum(e.ema_value_now, 4)}</Td>
                      <Td>{fmtNum(e.distance_pct)}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function FundamentalAnalysisPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const r = results[idx] ?? results[0]
  const overall = (r.overall as Row) ?? {}
  const valuation = (r.valuation as Row) ?? {}
  const holdingTrend = (r.holding_trend as Record<string, Row>) ?? {}
  const prTrend = (r.profit_revenue_trend as Row) ?? {}
  const debt = (r.debt as Row) ?? {}
  const prosCons = (r.pros_cons as Row) ?? {}
  const pros = (prosCons.pros as string[]) ?? []
  const cons = (prosCons.cons as string[]) ?? []
  const dhan = r.dhan as Row | undefined
  const profile = (dhan?.profile as Row) ?? {}
  const peers = (dhan?.peers as Row) ?? {}
  const peerRows = (peers.peers as Row[]) ?? []
  const industryPe = peers.industry_pe as number | undefined
  const opts = dhan?.options_snapshot as Row | undefined
  const rating = dhan?.analyst_rating as Row | undefined
  const returns = (dhan?.investment_returns as Row) ?? {}
  const corpActs = (dhan?.corporate_actions as Row[]) ?? []
  const salesCagr = (prTrend.sales_cagr as Row) ?? {}
  const profitCagr = (prTrend.profit_cagr as Row) ?? {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Fundamental Analysis · {String(r.ticker)}</p>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(overall.signal ?? r.verdict ?? ''))}`}>
              {String(overall.signal ?? r.verdict ?? '—')} · {fmtNum(overall.confidence_pct, 0)}% confidence
            </p>
            {((overall.factors as string[]) ?? []).length > 0 && (
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                {(overall.factors as string[]).map((f, i) => <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{f}</li>)}
              </ul>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Price" value={`₹${fmtNum(r.current_price, 2)}`} />
            <StatCard label="Market Cap" value={`₹${fmtNum(r.market_cap_cr, 0)} Cr`} />
            <StatCard label="P/E" value={fmtNum(r.pe, 1)} />
            <StatCard label="ROCE" value={`${fmtNum(r.roce_pct, 1)}%`} />
            <StatCard label="ROE" value={`${fmtNum(r.roe_pct, 1)}%`} />
            <StatCard label="Div Yield" value={`${fmtNum(r.dividend_yield_pct, 2)}%`} />
          </div>

          {valuation.label != null && (
            <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 px-4 py-3">
              <p className={`font-semibold ${verdictClass(String(valuation.label ?? ''))}`}>{String(valuation.label)}</p>
              <p className="mt-1 text-sm text-slate-400">{String(valuation.reason ?? '')}</p>
            </div>
          )}

          {Object.keys(holdingTrend).length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Shareholding trend (~12 months)</h4>
              <DataTable minWidth={640}>
                <thead><tr><Th>Category</Th><Th>Latest %</Th><Th>Δ 12m (pp)</Th><Th>Trend</Th><Th>Implication</Th></tr></thead>
                <tbody>
                  {Object.entries(holdingTrend).map(([label, info]) => (
                    <tr key={label}>
                      <Td>{label}</Td>
                      <Td>{fmtNum(info.latest_pct, 1)}</Td>
                      <Td>{fmtNum(info.delta_pp_12m, 1)}</Td>
                      <Td>{String(info.trend ?? '—')}</Td>
                      <Td className="max-w-xs truncate">{String(info.implication ?? '—')}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}

          <div>
            <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Profit &amp; Revenue trend (TTM)</h4>
            <div className="grid gap-3 sm:grid-cols-3">
              <StatCard label="Revenue TTM growth" value={`${fmtNum(prTrend.revenue_ttm_growth_pct, 1)}%`} />
              <StatCard label="Profit TTM growth" value={`${fmtNum(prTrend.profit_ttm_growth_pct, 1)}%`} />
              <StatCard label="Debt trend" value={String(debt.trend ?? 'N/A')} />
            </div>
            <div className="mt-3">
              <DataTable minWidth={480}>
                <thead><tr><Th>Period</Th><Th>Sales CAGR %</Th><Th>Profit CAGR %</Th></tr></thead>
                <tbody>
                  {['10 Years', '5 Years', '3 Years', 'TTM'].map((period) => (
                    <tr key={period}>
                      <Td>{period}</Td>
                      <Td>{fmtNum(salesCagr[period], 1)}</Td>
                      <Td>{fmtNum(profitCagr[period], 1)}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          </div>

          {(pros.length > 0 || cons.length > 0) && (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h4 className="mb-2 text-sm font-semibold text-emerald-400">✅ Pros (screener.in)</h4>
                {pros.length > 0 ? (
                  <ul className="space-y-1 text-sm text-slate-300">{pros.map((p, i) => <li key={i}>- {p}</li>)}</ul>
                ) : <p className="text-sm text-slate-500">None flagged.</p>}
              </div>
              <div>
                <h4 className="mb-2 text-sm font-semibold text-rose-400">⚠️ Cons (screener.in)</h4>
                {cons.length > 0 ? (
                  <ul className="space-y-1 text-sm text-slate-300">{cons.map((c, i) => <li key={i}>- {c}</li>)}</ul>
                ) : <p className="text-sm text-slate-500">None flagged.</p>}
              </div>
            </div>
          )}

          {dhan ? (
            <>
              <div>
                <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Company Profile &amp; Peer Comparison (Dhan.co)</h4>
                <div className="grid gap-3 sm:grid-cols-4">
                  <StatCard label="Sector" value={String(profile.sector ?? '—')} />
                  <StatCard label="Industry" value={String(profile.industry ?? '—')} />
                  <StatCard label="Classification" value={String(profile.classification ?? '—')} />
                  <StatCard label="Industry P/E" value={industryPe != null ? `${fmtNum(industryPe, 1)}x` : '—'} />
                </div>
                {peerRows.length > 0 && (
                  <div className="mt-3">
                    <DataTable minWidth={900}>
                      <thead>
                        <tr>
                          <Th>Symbol</Th><Th>Name</Th><Th>Price</Th><Th>P/E</Th><Th>P/B</Th><Th>ROE %</Th>
                          <Th>ROCE %</Th><Th>Div Yield %</Th><Th>Mkt Cap (Cr)</Th><Th>1Y Return %</Th><Th>Qtr Profit Growth %</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {peerRows.map((p, i) => (
                          <tr key={i}>
                            <Td>{String(p.symbol ?? '—')}</Td>
                            <Td>{String(p.name ?? '—')}</Td>
                            <Td>{fmtNum(p.price)}</Td>
                            <Td>{fmtNum(p.pe, 1)}</Td>
                            <Td>{fmtNum(p.pb, 1)}</Td>
                            <Td>{fmtNum(p.roe_pct, 1)}</Td>
                            <Td>{fmtNum(p.roce_pct, 1)}</Td>
                            <Td>{fmtNum(p.div_yield_pct, 1)}</Td>
                            <Td>{fmtNum(p.market_cap_cr, 0)}</Td>
                            <Td>{fmtNum(p.return_1y_pct, 1)}</Td>
                            <Td>{fmtNum(p.qtr_profit_growth_pct, 1)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </div>
                )}
              </div>

              {rating && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Analyst Rating Consensus</h4>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <StatCard label="Consensus" value={String(rating.rating ?? '—')} />
                    <StatCard label="Buy" value={`${String(rating.buy ?? 0)} (${fmtNum(rating.buy_pct, 0)}%)`} />
                    <StatCard label="Hold" value={`${String(rating.hold ?? 0)} (${fmtNum(rating.hold_pct, 0)}%)`} />
                    <StatCard label="Sell" value={`${String(rating.sell ?? 0)} (${fmtNum(rating.sell_pct, 0)}%)`} />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">Based on {String(rating.total_analysts ?? 0)} analysts.</p>
                </div>
              )}

              {Object.keys(returns).length > 0 && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Investment Returns</h4>
                  <div className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-10">
                    {Object.entries(returns).map(([period, val]) => (
                      <StatCard key={period} label={period.toUpperCase()} value={val != null ? `${Number(val) >= 0 ? '+' : ''}${fmtNum(val, 1)}%` : '—'} />
                    ))}
                  </div>
                </div>
              )}

              {opts && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Options Snapshot ({String(opts.expiry_days ?? '—')} days to nearest expiry)
                  </h4>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <StatCard label="PCR" value={fmtNum(opts.pcr, 2)} />
                    <StatCard label="ATM IV" value={`${fmtNum(opts.atm_iv, 1)}%`} />
                    <StatCard label="Max Pain" value={String(opts.max_pain_strike ?? '—')} />
                    <StatCard label="ATM Strike" value={String(opts.atm_strike ?? '—')} />
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-4">
                    <StatCard label="OI Support" value={String(opts.oi_support ?? '—')} />
                    <StatCard label="OI Resistance" value={String(opts.oi_resistance ?? '—')} />
                    <StatCard label="Total Call OI" value={fmtNum(opts.total_call_oi, 0)} />
                    <StatCard label="Total Put OI" value={fmtNum(opts.total_put_oi, 0)} />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">PCR and max pain are sentiment/positioning indicators, not standalone trade signals.</p>
                </div>
              )}

              {corpActs.length > 0 && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Corporate Actions</h4>
                  <DataTable minWidth={640}>
                    <thead><tr><Th>Type</Th><Th>Announced</Th><Th>Ex-Date</Th><Th>Record Date</Th><Th>Dividend Type</Th></tr></thead>
                    <tbody>
                      {corpActs.map((a, i) => (
                        <tr key={i}>
                          <Td>{String(a.type ?? '—')}</Td>
                          <Td>{String(a.announced ?? '—')}</Td>
                          <Td>{String(a.ex_date ?? '—')}</Td>
                          <Td>{String(a.record_date ?? '—')}</Td>
                          <Td>{String(a.dividend_type ?? '—')}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              )}

              {dhan.source_url != null && (
                <p className="text-xs text-slate-500">
                  Dhan source: <a href={String(dhan.source_url)} target="_blank" rel="noreferrer" className="underline hover:text-slate-300">{String(dhan.source_url)}</a>
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-500">
              ℹ️ Dhan.co enrichment (peers/industry P/E, options snapshot, analyst rating, corporate actions) isn't available for this ticker — showing screener.in data only.
            </p>
          )}

          {r.source_url != null && (
            <p className="text-xs text-slate-500">
              Source: <a href={String(r.source_url)} target="_blank" rel="noreferrer" className="underline hover:text-slate-300">{String(r.source_url)}</a>
            </p>
          )}
        </>
      )}
    </div>
  )
}

function OneClickPanel({ data, style }: { data: Row; style: 'intraday' | 'scalping' | 'swing' }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const r = results[idx] ?? results[0]
  const combo = (r.combo as Row) ?? {}
  const votes = (combo.votes as Row[]) ?? []
  const combofa = r.fundamentals_combo as Row | undefined

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              One-Click {style.charAt(0).toUpperCase() + style.slice(1)} · {String(r.ticker)}
            </p>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(combo.verdict ?? ''))}`}>
              {String(combo.verdict ?? '—')}
            </p>
            <p className="mt-2 text-sm text-slate-300">
              {String(combo.n_agree ?? 0)} of {String(combo.n_total ?? 0)} engines agree
              {combo.min_agree_required != null ? ` (need ${String(combo.min_agree_required)})` : ''}
              {' '}· confidence {fmtNum(combo.confidence_pct, 0)}% · take threshold {fmtNum(combo.take_threshold, 0)}%
            </p>
            {combofa && (
              <div className="mt-2 text-sm text-slate-400">
                <p>{String(combofa.note ?? '')}</p>
                <p className="text-xs text-slate-500">Technical-only confidence was {fmtNum(r.technical_confidence_pct, 0)}%.</p>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-3 text-sm">
              <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                Direction: <strong>{String(combo.direction ?? '—')}</strong>
              </span>
              <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                Take trade: <strong>{combo.take_trade ? 'Yes' : 'No'}</strong>
              </span>
              {combo.strictness != null && (
                <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                  Strictness: <strong>{String(combo.strictness)}</strong>
                </span>
              )}
              {style === 'intraday' && r.regime != null && (
                <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                  Regime: <strong>{String(r.regime)}</strong>
                </span>
              )}
              {style === 'scalping' && (
                <>
                  <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                    Session OK: <strong>{r.session_ok ? 'Yes' : 'No'}</strong>
                  </span>
                  {r.rvol != null && (
                    <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                      RVOL: <strong>{fmtNum(r.rvol, 2)}x</strong>
                    </span>
                  )}
                  {r.htf != null && (
                    <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                      HTF/LTF: <strong>{String(r.htf)}/{String(r.ltf)}</strong>
                    </span>
                  )}
                </>
              )}
            </div>
          </div>

          {(combo.entry_price != null || combo.stop_price != null || combo.target1_price != null || combo.target2_price != null) && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Entry" value={fmtNum(combo.entry_price, 4)} />
              <StatCard label="Stop" value={fmtNum(combo.stop_price, 4)} />
              <StatCard label="TP1 (partial, SL→BE)" value={fmtNum(combo.target1_price, 4)} />
              <StatCard label="TP2 (runner)" value={fmtNum(combo.target2_price, 4)} />
            </div>
          )}

          {votes.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Engine votes</h4>
              <DataTable minWidth={720}>
                <thead>
                  <tr><Th>Engine</Th><Th>Direction</Th><Th>Confidence</Th><Th>Take</Th><Th>Agreed</Th><Th>Note</Th></tr>
                </thead>
                <tbody>
                  {votes.map((v, i) => (
                    <tr key={i}>
                      <Td>{String(v.engine ?? '—')}</Td>
                      <Td className={verdictClass(String(v.direction ?? ''))}>{String(v.direction ?? '—')}</Td>
                      <Td>{v.confidence != null ? `${fmtNum(v.confidence, 0)}%` : '—'}</Td>
                      <Td>{v.take ? '✅' : '—'}</Td>
                      <Td>{v.agreed ? '✅' : (v.direction === 'WAIT' ? '⚪' : '❌')}</Td>
                      <Td className="max-w-xs truncate text-slate-400">
                        {v.error != null ? String(v.error) : String(((v.reasons as string[]) ?? [])[0] ?? '')}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}

          {((combo.reasons as string[]) ?? []).length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Full reasoning</h4>
              <ul className="space-y-1.5 text-sm text-slate-300">
                {(combo.reasons as string[]).map((rr, i) => (
                  <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{rr}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function MoversTable({ label, bundle }: { label: string; bundle: Row | undefined }) {
  if (!bundle) return null
  const gainers = (bundle.gainers as Row[]) ?? []
  const losers = (bundle.losers as Row[]) ?? []
  if (bundle.error != null && !gainers.length && !losers.length) {
    return (
      <div>
        <h5 className="mb-2 text-sm font-semibold text-white">{label}</h5>
        <p className="text-xs text-amber-300">{String(bundle.error)}</p>
      </div>
    )
  }
  const rowLabel = (row: Row) => String(row.symbol ?? row.name ?? '—')
  return (
    <div>
      <h5 className="mb-2 text-sm font-semibold text-white">
        {label}{bundle.source != null ? <span className="ml-2 text-xs font-normal text-slate-500">({String(bundle.source)})</span> : null}
      </h5>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-emerald-400">Gainers</p>
          <ul className="space-y-1 text-sm text-slate-300">
            {gainers.slice(0, 8).map((g, i) => (
              <li key={i} className="flex justify-between"><span>{rowLabel(g)}</span><span className="text-emerald-400">+{fmtNum(g.pct, 2)}%</span></li>
            ))}
            {!gainers.length && <li className="text-slate-500">—</li>}
          </ul>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-rose-400">Losers</p>
          <ul className="space-y-1 text-sm text-slate-300">
            {losers.slice(0, 8).map((l, i) => (
              <li key={i} className="flex justify-between"><span>{rowLabel(l)}</span><span className="text-rose-400">{fmtNum(l.pct, 2)}%</span></li>
            ))}
            {!losers.length && <li className="text-slate-500">—</li>}
          </ul>
        </div>
      </div>
    </div>
  )
}

function GlobalMarketMoodPanel({ data }: { data: Row }) {
  const composite = (data.composite as Row) ?? {}
  const regions = (data.regions as Record<string, Row>) ?? {}
  const sectors = (data.sectors as Row) ?? {}
  const news = (data.geopolitical_news as Row[]) ?? []
  const indiaSentiment = data.india_sentiment as Row | undefined
  const movers = (data.stock_movers as Row) ?? {}
  const [moversTab, setMoversTab] = useState<'india' | 'us' | 'crypto'>('india')

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Composite mood</p>
        <p className={`mt-1 text-2xl font-bold ${verdictClass(String(composite.mood ?? ''))}`}>
          {String(composite.mood_emoji ?? '')} {String(composite.mood ?? '—')}
          {composite.avg_pct != null ? ` (${Number(composite.avg_pct).toFixed(2)}%)` : ''}
        </p>
        {indiaSentiment && (
          <p className="mt-2 text-sm text-slate-400">
            India sentiment: <strong>{String(indiaSentiment.label ?? indiaSentiment.sentiment ?? '—')}</strong>
            {indiaSentiment.score != null ? ` (${fmtNum(indiaSentiment.score, 1)})` : ''}
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Object.values(regions).map((r) => (
          <div key={String(r.region_id)} className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              {String(r.emoji ?? '')} {String(r.label ?? r.region_id ?? '—')}
            </p>
            <p className={`mt-1 text-lg font-bold ${verdictClass(String(r.mood ?? ''))}`}>
              {String(r.mood_emoji ?? '')} {String(r.mood ?? '—')}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              {fmtNum(r.avg_pct, 2)}% avg · 🟢{String(r.green_count ?? 0)} 🔴{String(r.red_count ?? 0)}
            </p>
            {r.headline != null && String(r.headline).trim() && (
              <p className="mt-1 text-xs text-amber-300">{String(r.headline)}</p>
            )}
            {((r.instruments as Row[]) ?? []).length > 0 && (
              <ul className="mt-2 space-y-0.5 text-xs text-slate-400">
                {((r.instruments as Row[]) ?? []).slice(0, 3).map((inst, i) => (
                  <li key={i} className="flex justify-between">
                    <span>{String(inst.name ?? '—')}</span>
                    <span className={Number(inst.pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                      {fmtNum(inst.pct, 2)}%
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      {((sectors.leading as Row[]) ?? []).length > 0 && (
        <div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h4 className="mb-2 text-sm font-semibold text-emerald-400">Leading sectors</h4>
              <DataTable minWidth={360}>
                <thead><tr><Th>Sector</Th><Th>% Chg</Th><Th>Adv</Th><Th>Dec</Th></tr></thead>
                <tbody>
                  {((sectors.leading as Row[]) ?? []).slice(0, 8).map((s, i) => (
                    <tr key={i}>
                      <Td>{String(s.name)}</Td>
                      <Td className="text-emerald-400">{fmtNum(s.pct, 2)}%</Td>
                      <Td>{String(s.advances ?? '—')}</Td>
                      <Td>{String(s.declines ?? '—')}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
            <div>
              <h4 className="mb-2 text-sm font-semibold text-rose-400">Lagging sectors</h4>
              <DataTable minWidth={360}>
                <thead><tr><Th>Sector</Th><Th>% Chg</Th><Th>Adv</Th><Th>Dec</Th></tr></thead>
                <tbody>
                  {((sectors.lagging as Row[]) ?? []).slice(0, 8).map((s, i) => (
                    <tr key={i}>
                      <Td>{String(s.name)}</Td>
                      <Td className="text-rose-400">{fmtNum(s.pct, 2)}%</Td>
                      <Td>{String(s.advances ?? '—')}</Td>
                      <Td>{String(s.declines ?? '—')}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          </div>
          {sectors.prediction != null && String(sectors.prediction).trim() && (
            <p className="mt-3 text-sm text-slate-300">{String(sectors.prediction)}</p>
          )}
        </div>
      )}

      {Boolean(movers.india || movers.us || movers.crypto) && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">Stock Leaders &amp; Laggards</h4>
          <div className="mb-3 flex flex-wrap gap-2">
            <Chip selected={moversTab === 'india'} onClick={() => setMoversTab('india')}>🇮🇳 India</Chip>
            <Chip selected={moversTab === 'us'} onClick={() => setMoversTab('us')}>🇺🇸 US</Chip>
            <Chip selected={moversTab === 'crypto'} onClick={() => setMoversTab('crypto')}>₿ Crypto</Chip>
          </div>
          {moversTab === 'india' && <MoversTable label={String((movers.india as Row)?.label ?? 'India')} bundle={movers.india as Row | undefined} />}
          {moversTab === 'us' && <MoversTable label={String((movers.us as Row)?.label ?? 'US')} bundle={movers.us as Row | undefined} />}
          {moversTab === 'crypto' && <MoversTable label={String((movers.crypto as Row)?.label ?? 'Crypto')} bundle={movers.crypto as Row | undefined} />}
        </div>
      )}

      {news.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">Geopolitical headlines</h4>
          <ul className="space-y-2 text-sm text-slate-300">
            {news.slice(0, 10).map((n, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-slate-500">•</span>
                <span>
                  {n.link != null ? (
                    <a href={String(n.link)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                      {String(n.title ?? n.headline ?? '')}
                    </a>
                  ) : String(n.title ?? n.headline ?? '')}
                  <span className="ml-1.5 text-xs text-slate-500">
                    {n.source != null ? `(${String(n.source)})` : ''}{n.age_hours != null ? ` · ${fmtNum(n.age_hours, 0)}h ago` : ''}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.built_at != null && (
        <p className="text-xs text-slate-500">Built at {String(data.built_at)}</p>
      )}
    </div>
  )
}

function MegaSetupAdvisorPanel({ data }: { data: Row }) {
  const enabled = (data.enabled_labels as string[]) ?? []
  const rationale = (data.rationale as string[]) ?? []
  const timeframes = (data.timeframes as string[]) ?? []
  const aiReport = data.ai_report as string | undefined
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Recommended scenario</p>
        <p className="mt-1 text-xl font-bold text-white">{String(data.scenario ?? '—')}</p>
        <p className="mt-1 text-sm text-slate-400">Source: {String(data.source ?? 'rule_based')}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Asset class" value={String(data.asset_class ?? '—')} />
        <StatCard label="Market" value={String(data.market ?? '—')} />
        <StatCard label="Timeframes" value={timeframes.length ? timeframes.join(', ') : '—'} />
      </div>
      {rationale.length > 0 && (
        <ul className="space-y-1.5 text-sm text-slate-300">
          {rationale.map((r, i) => <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{r}</li>)}
        </ul>
      )}
      {enabled.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">Enabled modules ({enabled.length})</h4>
          <div className="flex flex-wrap gap-1.5">
            {enabled.map((l) => <span key={l} className="rounded-lg bg-slate-800/60 px-2.5 py-1 text-xs text-slate-300">{l}</span>)}
          </div>
        </div>
      )}
      {aiReport != null && String(aiReport).trim() && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">AI report</h4>
          <p className="whitespace-pre-wrap rounded-xl border border-slate-800/60 bg-slate-900/30 p-4 text-sm leading-relaxed text-slate-300">
            {aiReport}
          </p>
        </div>
      )}
    </div>
  )
}

const _CATEGORY_LABELS: Record<string, string> = {
  BLOCK_DEAL: '🧱 Block Deal',
  MERGER_ACQUISITION: '🤝 Merger / Acquisition',
  UPGRADE: '⬆️ Upgrade',
  DOWNGRADE: '⬇️ Downgrade',
  TARGET_RAISE: '🎯 Target Raise',
  TARGET_CUT: '🎯 Target Cut',
  RERATING: '🔁 Re-rating',
  INITIATE: '🆕 Coverage Initiated',
  REITERATE: '🔂 Reiterated',
  RECOMMENDATION: '📋 Analyst Recommendation',
}

function StockUpgradeDowngradePanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const r = results[idx] ?? results[0]
  const consensus = (r.consensus as Row) ?? {}
  const items = (r.items as Row[]) ?? []
  const sitesChecked = (r.sites_checked as string[]) ?? []
  const categoryCounts = (r.category_counts as Record<string, number>) ?? {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Upgrade/Downgrade · {String(r.ticker)}</p>
        <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(consensus.consensus ?? ''))}`}>
          {String(consensus.consensus ?? 'NO DATA')}
        </p>
        <p className="mt-1 text-sm text-slate-400">
          {String(r.item_count ?? 0)} item(s) · Latest target {String(consensus.latest_target ?? '—')} ·
          {' '}Buy/Sell/Hold {String(consensus.buy ?? 0)}/{String(consensus.sell ?? 0)}/{String(consensus.hold ?? 0)}
        </p>
        {sitesChecked.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">Sites checked: {sitesChecked.map((s) => `✅ ${s}`).join('  ')}</p>
        )}
      </div>

      {Object.keys(categoryCounts).length > 0 && (
        <div className="grid gap-3 sm:grid-cols-4">
          {Object.entries(categoryCounts)
            .filter(([, count]) => count > 0)
            .map(([key, count]) => (
              <StatCard key={key} label={_CATEGORY_LABELS[key] ?? key} value={count} />
            ))}
          {Object.values(categoryCounts).every((c) => !c) && (
            <p className="col-span-full text-sm text-slate-500">No categorized items found.</p>
          )}
        </div>
      )}

      {items.length > 0 ? (
        <DataTable minWidth={900}>
          <thead>
            <tr><Th>Category</Th><Th>Action</Th><Th>Brokerage</Th><Th>Target</Th><Th>Title</Th><Th>Published</Th></tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i}>
                <Td>{String(it.category_label ?? it.call_type ?? '—')}</Td>
                <Td className={verdictClass(String(it.action ?? ''))}>{String(it.action ?? '—')}</Td>
                <Td>{String(it.brokerage ?? '—')}</Td>
                <Td>{String(it.price_target ?? '—')}</Td>
                <Td className="max-w-xs truncate">
                  {it.link != null ? (
                    <a href={String(it.link)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                      {String(it.title ?? '—')}
                    </a>
                  ) : String(it.title ?? '—')}
                </Td>
                <Td>{String(it.published ?? '—')}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      ) : (
        <p className="text-sm text-slate-500">No upgrade/downgrade items found for this ticker.</p>
      )}
    </div>
  )
}

export function CommandCenterResults({ tab, data }: { tab: string; data: Row }) {
  if (data.error && tab !== 'investigation' && tab !== 'investigation_strategies') {
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
    case 'global_market_mood':
      return <GlobalMarketMoodPanel data={data} />
    case 'mega_setup_advisor':
      return <MegaSetupAdvisorPanel data={data} />
    case 'momentum':
      return <MomentumPanel data={data} />
    case 'ema_position':
      return <EmaPositionPanel data={data} />
    case 'fundamental_analysis':
      return <FundamentalAnalysisPanel data={data} />
    case 'stock_upgrade_downgrade':
      return <StockUpgradeDowngradePanel data={data} />
    case 'one_click_intraday':
      return <OneClickPanel data={data} style="intraday" />
    case 'one_click_scalping':
      return <OneClickPanel data={data} style="scalping" />
    case 'one_click_swing':
      return <OneClickPanel data={data} style="swing" />
    case 'investigation_strategies':
      return (
        <TickerInvestigationPanel
          data={data}
          renderExtra={(r) => {
            const selected = (r.selected_strategies as string[]) ?? []
            const runs = (r.strategy_runs as Row[]) ?? []
            if (!selected.length && !runs.length) return null
            return (
              <div className="space-y-2">
                {selected.length > 0 && (
                  <p className="text-xs text-slate-500">Strategies combined: {selected.join(', ')}</p>
                )}
                {runs.length > 0 && (
                  <div>
                    <h4 className="mb-2 text-sm font-semibold text-white">Selected strategy runs</h4>
                    <DataTable>
                      <thead><tr><Th>Strategy</Th><Th>Verdict</Th><Th>Confidence</Th><Th>Take</Th></tr></thead>
                      <tbody>
                        {runs.map((run, i) => {
                          const analysis = (run.analysis as Row) ?? {}
                          const live = (analysis.live as Row) ?? analysis
                          const verdict = live.verdict ?? analysis.verdict ?? analysis.primary_label
                          const confidence = live.confidence_pct ?? live.confidence ?? analysis.confidence
                          const take = live.take_trade ?? analysis.take_trade ?? analysis.actionable
                          return (
                            <tr key={i}>
                              <Td>{String(run.label ?? run.strategy_id)}</Td>
                              <Td className={verdictClass(String(verdict ?? ''))}>{String(verdict ?? run.error ?? '—')}</Td>
                              <Td>{confidence != null ? `${fmtNum(confidence, 0)}%` : '—'}</Td>
                              <Td>{take ? '✅' : '—'}</Td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </DataTable>
                  </div>
                )}
              </div>
            )
          }}
        />
      )
    default:
      return <p className="text-sm text-slate-500">Unknown section.</p>
  }
}
