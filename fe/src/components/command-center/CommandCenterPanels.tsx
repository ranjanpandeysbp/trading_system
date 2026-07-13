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

function TickerResultsPanel({ results, buildRow, keyField = 'ticker' }: {
  results: Row[]
  buildRow: (r: Row) => Row
  keyField?: string
}) {
  const [idx, setIdx] = useState(0)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const raw = results[idx] ?? results[0]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((r, i) => (
          <Chip key={`${String(r[keyField] ?? i)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(r[keyField] ?? `#${i + 1}`)}
          </Chip>
        ))}
      </div>
      {raw.error ? <Alert type="error">{String(raw.error)}</Alert> : <SummaryCard title="Result" row={buildRow(raw)} />}
    </div>
  )
}

function GlobalMarketMoodPanel({ data }: { data: Row }) {
  const composite = (data.composite as Row) ?? {}
  const regions = (data.regions as Record<string, Row>) ?? {}
  const sectors = (data.sectors as Row) ?? {}
  const news = (data.geopolitical_news as Row[]) ?? []
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Composite mood</p>
        <p className={`mt-1 text-2xl font-bold ${verdictClass(String(composite.mood ?? ''))}`}>
          {String(composite.mood_emoji ?? '')} {String(composite.mood ?? '—')}
          {composite.avg_pct != null ? ` (${Number(composite.avg_pct).toFixed(2)}%)` : ''}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(regions).map(([key, r]) => (
          <StatCard key={key} label={key.replace(/_/g, ' ')} value={`${String(r.mood_emoji ?? '')} ${String(r.mood ?? '—')}`} />
        ))}
      </div>
      {((sectors.leading as Row[]) ?? []).length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h4 className="mb-2 text-sm font-semibold text-emerald-400">Leading sectors</h4>
            <ul className="space-y-1 text-sm text-slate-300">
              {((sectors.leading as Row[]) ?? []).slice(0, 8).map((s, i) => (
                <li key={i}>{String(s.name)} — {Number(s.pct ?? 0).toFixed(2)}%</li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="mb-2 text-sm font-semibold text-rose-400">Lagging sectors</h4>
            <ul className="space-y-1 text-sm text-slate-300">
              {((sectors.lagging as Row[]) ?? []).slice(0, 8).map((s, i) => (
                <li key={i}>{String(s.name)} — {Number(s.pct ?? 0).toFixed(2)}%</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {news.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">Geopolitical headlines</h4>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {news.slice(0, 10).map((n, i) => (
              <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{String(n.title ?? n.headline ?? '')}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function MegaSetupAdvisorPanel({ data }: { data: Row }) {
  const enabled = (data.enabled_labels as string[]) ?? []
  const rationale = (data.rationale as string[]) ?? []
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Recommended scenario</p>
        <p className="mt-1 text-xl font-bold text-white">{String(data.scenario ?? '—')}</p>
        <p className="mt-1 text-sm text-slate-400">Source: {String(data.source ?? 'rule_based')}</p>
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
    </div>
  )
}

function StockUpgradeDowngradeRow(r: Row): Row {
  const consensus = (r.consensus as Row) ?? {}
  const items = (r.items as Row[]) ?? []
  return {
    ticker: r.ticker,
    verdict: consensus.consensus ?? 'NO DATA',
    summary: `${r.item_count ?? 0} item(s) across ${((r.sites_checked as string[]) ?? []).length} sites`,
    reasons: items.slice(0, 6).map((it) => `${String(it.call_type ?? '')}: ${String(it.title ?? '')}`),
  }
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
      return (
        <TickerResultsPanel
          results={(data.results as Row[]) ?? []}
          buildRow={(r) => ({
            ticker: r.ticker,
            verdict: r.overall_direction,
            direction: r.overall_direction,
            confidence_pct: r.confidence_continue_pct,
            summary: `Strength: ${String(r.overall_strength ?? '—')} · Alignment: ${String(r.alignment ?? '—')}`,
            reasons: r.reasons as string[],
          })}
        />
      )
    case 'ema_position':
      return (
        <TickerResultsPanel
          results={(data.results as Row[]) ?? []}
          buildRow={(r) => {
            const act = (r.actionability as Row) ?? {}
            return {
              ticker: `${String(r.ticker)} · ${String(r.timeframe ?? '')}`,
              verdict: act.bucket ?? '—',
              direction: act.direction,
              summary: String(act.reason ?? r.note ?? ''),
            }
          }}
        />
      )
    case 'fundamental_analysis':
      return (
        <TickerResultsPanel
          results={(data.results as Row[]) ?? []}
          buildRow={(r) => ({
            ticker: r.ticker,
            verdict: r.verdict,
            summary: `PE ${r.pe ?? '—'} · ROCE ${r.roce_pct ?? '—'}% · ROE ${r.roe_pct ?? '—'}%`,
            reasons: ((r.pros_cons as Row)?.pros as string[]) ?? [],
          })}
        />
      )
    case 'stock_upgrade_downgrade':
      return <TickerResultsPanel results={(data.results as Row[]) ?? []} buildRow={StockUpgradeDowngradeRow} />
    case 'one_click_intraday':
    case 'one_click_scalping':
    case 'one_click_swing':
      return (
        <TickerResultsPanel
          results={(data.results as Row[]) ?? []}
          buildRow={(r) => {
            const combo = (r.combo as Row) ?? {}
            return {
              ticker: r.ticker,
              verdict: combo.verdict,
              direction: combo.direction,
              confidence_pct: combo.confidence_pct,
              take_trade: combo.take_trade,
              reasons: combo.reasons as string[],
            }
          }}
        />
      )
    case 'investigation_strategies':
      return (
        <div className="space-y-6">
          <TickerInvestigationPanel data={data} />
          {((data.strategy_runs as Row[]) ?? []).length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold text-white">Selected strategy runs</h4>
              <DataTable>
                <thead><tr><Th>Strategy</Th><Th>Verdict</Th><Th>Notes</Th></tr></thead>
                <tbody>
                  {(data.strategy_runs as Row[]).map((run, i) => {
                    const analysis = (run.analysis as Row) ?? {}
                    return (
                      <tr key={i}>
                        <Td>{String(run.label ?? run.strategy_id)}</Td>
                        <Td className={verdictClass(String(analysis.verdict ?? ''))}>{String(analysis.verdict ?? run.error ?? '—')}</Td>
                        <Td className="max-w-xs truncate text-slate-400">{String(analysis.primary_label ?? '')}</Td>
                      </tr>
                    )
                  })}
                </tbody>
              </DataTable>
            </div>
          )}
        </div>
      )
    default:
      return <p className="text-sm text-slate-500">Unknown section.</p>
  }
}
