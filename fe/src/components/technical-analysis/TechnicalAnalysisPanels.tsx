import { useState, type ReactNode } from 'react'
import { DataTable, Td, SortableTh, useSort } from '../ui/Table'
import { Alert } from '../ui/Feedback'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { StatCard } from '../ui/StatCard'

type Row = Record<string, unknown>

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const v = Number(n)
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}`
}

function scoreClass(score: number) {
  if (score >= 35) return 'text-emerald-400'
  if (score <= -35) return 'text-rose-400'
  return 'text-amber-400'
}

export function SentimentScreenerPanel({ data }: { data: Row }) {
  const rows = (data.rows as Row[]) ?? []
  const errors = (data.errors as string[]) ?? []
  const [expanded, setExpanded] = useState<string | null>(null)
  const { sorted, sortKey, sortDir, handleSort } = useSort(rows, {
    ticker: (r) => String(r.ticker ?? ''),
    timeframe: (r) => String(r.timeframe ?? ''),
    score: (r) => Number(r.score ?? 0),
    rating: (r) => String(r.rating ?? ''),
    trade_signal: (r) => String(r.trade_signal ?? ''),
    trade_confidence: (r) => (r.trade_confidence != null ? Number(r.trade_confidence) : null),
    rsi: (r) => (r.rsi != null ? Number(r.rsi) : null),
    sl_pct: (r) => (r.sl_pct != null ? Number(r.sl_pct) : null),
  })

  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!rows.length) return <p className="text-sm text-slate-500">No results — add tickers and run scan.</p>

  return (
    <div className="space-y-4">
      {errors.length > 0 && (
        <Alert type="error">{errors.length} scan error(s) — partial results shown.</Alert>
      )}
      <DataTable>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
            <SortableTh active={sortKey === 'timeframe'} direction={sortDir} onSort={() => handleSort('timeframe')}>TF</SortableTh>
            <SortableTh active={sortKey === 'score'} direction={sortDir} onSort={() => handleSort('score')}>Score</SortableTh>
            <SortableTh active={sortKey === 'rating'} direction={sortDir} onSort={() => handleSort('rating')}>Rating</SortableTh>
            <SortableTh active={sortKey === 'trade_signal'} direction={sortDir} onSort={() => handleSort('trade_signal')}>Signal</SortableTh>
            <SortableTh active={sortKey === 'trade_confidence'} direction={sortDir} onSort={() => handleSort('trade_confidence')}>Conf</SortableTh>
            <SortableTh active={sortKey === 'rsi'} direction={sortDir} onSort={() => handleSort('rsi')}>RSI</SortableTh>
            <SortableTh active={sortKey === 'sl_pct'} direction={sortDir} onSort={() => handleSort('sl_pct')}>SL/TP %</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const key = `${r.ticker}-${r.timeframe}`
            const score = Number(r.score ?? 0)
            return (
              <tr key={key} className="cursor-pointer hover:bg-slate-800/30" onClick={() => setExpanded(expanded === key ? null : key)}>
                <Td className="font-medium">{String(r.ticker)}</Td>
                <Td>{String(r.timeframe)}</Td>
                <Td className={scoreClass(score)}>{fmtPct(score)}</Td>
                <Td className="max-w-[12rem] truncate text-xs">{String(r.rating ?? '—')}</Td>
                <Td>{String(r.trade_signal ?? '—')}</Td>
                <Td>{r.trade_confidence != null ? `${r.trade_confidence}%` : '—'}</Td>
                <Td>{r.rsi != null ? Number(r.rsi).toFixed(1) : '—'}</Td>
                <Td>{r.sl_pct != null ? `${r.sl_pct}/${r.tp_pct}` : '—'}</Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>
      {expanded && (
        <Card className="mt-2">
          {(() => {
            const row = rows.find((r) => `${r.ticker}-${r.timeframe}` === expanded)
            const insights = (row?.insights as string[]) ?? []
            return (
              <div>
                <p className="mb-2 text-sm font-medium text-white">{String(row?.ticker)} · {String(row?.timeframe)}</p>
                <ul className="max-h-64 space-y-1 overflow-y-auto text-xs text-slate-300">
                  {insights.map((i) => <li key={i}>{i}</li>)}
                </ul>
              </div>
            )
          })()}
        </Card>
      )}
    </div>
  )
}

export function MtfScannerPanel({ data }: { data: Row }) {
  const results = (data.results as Record<string, Row>) ?? {}
  const tickers = Object.keys(results)
  const [selected, setSelected] = useState(tickers[0] ?? '')

  const item = results[selected] as Row | undefined
  const confluence = item?.confluence as Row | undefined
  const setups = (item?.trade_setups as Row[]) ?? []
  const tfResults = (item?.timeframes as Record<string, Row>) ?? {}
  const tfEntries = Object.entries(tfResults)
  const { sorted: sortedTf, sortKey: tfSortKey, sortDir: tfSortDir, handleSort: handleTfSort } = useSort(tfEntries, {
    tf: ([tf]) => tf,
    score: ([, d]) => Number(d.score ?? 0),
    bias: ([, d]) => String(d.bias ?? ''),
    confidence: ([, d]) => Number(d.confidence ?? 0),
  })

  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!tickers.length) return <p className="text-sm text-slate-500">No MTF results.</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {tickers.map((t) => (
          <Chip key={t} selected={selected === t} onClick={() => setSelected(t)}>{t}</Chip>
        ))}
      </div>
      {confluence && (
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
          <p className="text-lg font-semibold text-white">
            {String(confluence.verdict ?? confluence.bias ?? 'Confluence')}
          </p>
          <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-300">
            <span>Avg score: <strong className={scoreClass(Number(confluence.avg_score))}>{fmtPct(Number(confluence.avg_score))}</strong></span>
            <span>Confidence: <strong>{Number(confluence.avg_confidence ?? 0).toFixed(0)}%</strong></span>
            <span>Bull/Bear/Neutral: <strong>{String(confluence.bull_count)}/{String(confluence.bear_count)}/{String(confluence.neutral_count)}</strong></span>
          </div>
          {(confluence.suggested_play as string[] | undefined)?.length ? (
            <ul className="mt-3 space-y-1 text-sm text-slate-400">
              {(confluence.suggested_play as string[]).map((p) => <li key={p}>• {p}</li>)}
            </ul>
          ) : null}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Per-timeframe components</h4>
          <DataTable>
            <thead>
              <tr>
                <SortableTh active={tfSortKey === 'tf'} direction={tfSortDir} onSort={() => handleTfSort('tf')}>TF</SortableTh>
                <SortableTh active={tfSortKey === 'score'} direction={tfSortDir} onSort={() => handleTfSort('score')}>Score</SortableTh>
                <SortableTh active={tfSortKey === 'bias'} direction={tfSortDir} onSort={() => handleTfSort('bias')}>Bias</SortableTh>
                <SortableTh active={tfSortKey === 'confidence'} direction={tfSortDir} onSort={() => handleTfSort('confidence')}>Conf</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedTf.map(([tf, tfData]) => (
                <tr key={tf}>
                  <Td>{tf}</Td>
                  <Td className={scoreClass(Number(tfData.score))}>{fmtPct(Number(tfData.score))}</Td>
                  <Td>{String(tfData.bias ?? '—')}</Td>
                  <Td>{Number(tfData.confidence ?? 0).toFixed(0)}%</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Trade setups</h4>
          {setups.length === 0 ? (
            <p className="text-sm text-slate-500">No setups generated.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {setups.slice(0, 6).map((s, i) => (
                <li key={i} className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-3">
                  <p className="font-medium text-white">{String(s.style ?? s.type ?? 'Setup')} · {String(s.direction ?? '—')}</p>
                  <p className="text-xs text-slate-400">{String(s.status ?? '')} · {String(s.timeframe ?? '')}</p>
                  {s.entry != null && <p className="mt-1 text-slate-300">Entry: ₹{Number(s.entry).toFixed(2)}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function fmtN(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

function verdictTone(verdict: string) {
  const v = verdict.toUpperCase()
  if (v.includes('BUY') || v.includes('BULL') || v.includes('LONG') || v === 'TAKE') return 'text-emerald-400'
  if (v.includes('SELL') || v.includes('BEAR') || v.includes('SHORT') || v.includes('AVOID')) return 'text-rose-400'
  return 'text-amber-400'
}

const SR_EVENT_LABELS: Record<string, string> = {
  BREAKOUT: '🚀 Breakout',
  BREAKDOWN: '🔻 Breakdown',
  FAKEOUT: '⚠️ Fakeout',
  REVERSAL: '🔄 Reversal',
  RANGE: '↔️ Range',
}

function PriceActionSnapshot({ pa, title }: { pa: Row; title: string }) {
  if (!pa || pa.insufficient) return null
  const bestSetup = pa.best_setup as Row | undefined
  const alerts = (pa.approaching_alerts as string[]) ?? []
  return (
    <div className="rounded-lg border border-slate-800/60 p-3">
      <p className="mb-2 text-sm font-medium text-white">{title}</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-300 sm:grid-cols-3">
        <span>Bias: <strong className={verdictTone(String(pa.overall_bias ?? ''))}>{String(pa.overall_bias ?? '—')}</strong></span>
        <span>Trend: <strong>{String(pa.trend ?? '—')}</strong></span>
        <span>RSI: <strong>{fmtN(pa.rsi, 1)}</strong> ({String(pa.rsi_zone ?? '—')})</span>
        <span>EMA stack: <strong>{String(pa.ema_stack ?? '—')}</strong></span>
        <span>Fib golden: <strong>{pa.fib_golden ? 'Yes' : 'No'}</strong></span>
        <span>VWAP: <strong>{String(pa.vwap_position ?? '—')}</strong> ({fmtN(pa.vwap_distance_pct, 2)}%)</span>
        <span>RVOL: <strong>{fmtN(pa.volume_ratio, 2)}x</strong> ({String(pa.volume_label ?? '—')})</span>
        <span>MFI: <strong>{fmtN(pa.mfi, 1)}</strong></span>
        <span>SMC OB bull/bear: <strong>{String(pa.smc_bull_ob ?? 0)}/{String(pa.smc_bear_ob ?? 0)}</strong></span>
        <span>SMC FVG bull/bear: <strong>{String(pa.smc_bull_fvg ?? 0)}/{String(pa.smc_bear_fvg ?? 0)}</strong></span>
        <span>Verdict: <strong className={verdictTone(String(pa.verdict ?? ''))}>{String(pa.verdict ?? '—')}</strong></span>
      </div>
      {alerts.length > 0 && (
        <p className="mt-2 text-xs text-amber-300">{alerts.slice(0, 3).join(' · ')}</p>
      )}
      {bestSetup && (
        <p className="mt-2 text-xs text-slate-400">
          Best PA setup: <strong className={verdictTone(String(bestSetup.direction ?? ''))}>{String(bestSetup.direction ?? '—')}</strong>
          {' '}conf {fmtN(bestSetup.confidence, 0)}% · SL {fmtN(bestSetup.sl_pct)}% · TP {fmtN(bestSetup.tp1_pct)}%
        </p>
      )}
    </div>
  )
}

export function TickerInvestigationPanel({
  data,
  renderExtra,
}: {
  data: Row
  renderExtra?: (result: Row) => ReactNode
}) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)

  const r = results[idx] ?? results[0]
  const priceWindows = (r?.price_windows as Row[]) ?? []
  const sr = r?.sr as Row | undefined
  const srByTf = (sr?.by_tf as Record<string, Row>) ?? {}
  const priceAction = r?.price_action as Row | undefined
  const paByTf = (priceAction?.by_tf as Record<string, Row>) ?? {}
  const strategies = (r?.strategies as Row[]) ?? []
  const suggestedTrades = (r?.suggested_trades as Row[]) ?? []
  const analystCalls = (r?.analyst_calls as Row[]) ?? []

  const paByTfEntries = Object.entries(paByTf)
  const { sorted: sortedPaByTf, sortKey: paTfSortKey, sortDir: paTfSortDir, handleSort: handlePaTfSort } = useSort(paByTfEntries, {
    tf: ([tf]) => tf,
    bias: ([, p]) => String(p.overall_bias ?? ''),
    trend: ([, p]) => String(p.trend ?? ''),
    rsi: ([, p]) => (p.rsi != null ? Number(p.rsi) : null),
    ema_stack: ([, p]) => String(p.ema_stack ?? ''),
    vwap: ([, p]) => String(p.vwap_position ?? ''),
    rvol: ([, p]) => (p.volume_ratio != null ? Number(p.volume_ratio) : null),
    verdict: ([, p]) => String(p.verdict ?? ''),
  })

  const { sorted: sortedPriceWindows, sortKey: pwSortKey, sortDir: pwSortDir, handleSort: handlePwSort } = useSort(priceWindows, {
    window: (w) => String(w.window ?? ''),
    change_pct: (w) => (w.change_pct != null ? Number(w.change_pct) : null),
    rsi: (w) => (w.rsi != null ? Number(w.rsi) : null),
    rsi_zone: (w) => String(w.rsi_zone ?? ''),
  })

  const srByTfEntries = Object.entries(srByTf)
  const { sorted: sortedSrByTf, sortKey: srTfSortKey, sortDir: srTfSortDir, handleSort: handleSrTfSort } = useSort(srByTfEntries, {
    tf: ([tf]) => tf,
    support: ([, s]) => (s.support != null ? Number(s.support) : null),
    resistance: ([, s]) => (s.resistance != null ? Number(s.resistance) : null),
    breakout: ([, s]) => (s.breakout_chance_pct != null ? Number(s.breakout_chance_pct) : null),
    breakdown: ([, s]) => (s.breakdown_chance_pct != null ? Number(s.breakdown_chance_pct) : null),
    bias: ([, s]) => String(s.sr_bias ?? ''),
  })

  const analystCallsSlice = analystCalls.slice(0, 10)
  const { sorted: sortedAnalystCalls, sortKey: acSortKey, sortDir: acSortDir, handleSort: handleAcSort } = useSort(analystCallsSlice, {
    action: (c) => String(c.action ?? ''),
    call_type: (c) => String(c.call_type ?? ''),
    brokerage: (c) => String(c.brokerage ?? ''),
    price_target: (c) => (c.price_target != null ? Number(c.price_target) : null),
    title: (c) => String(c.title ?? ''),
  })

  const { sorted: sortedTrades, sortKey: tradeSortKey, sortDir: tradeSortDir, handleSort: handleTradeSort } = useSort(suggestedTrades, {
    status: (t) => String(t.status ?? ''),
    direction: (t) => String(t.direction ?? ''),
    name: (t) => String(t.name ?? ''),
    confidence_pct: (t) => (t.confidence_pct != null ? Number(t.confidence_pct) : null),
    sl_pct: (t) => (t.sl_pct != null ? Number(t.sl_pct) : null),
    tp_pct: (t) => (t.tp_pct != null ? Number(t.tp_pct) : null),
    rr_ratio: (t) => (t.rr_ratio != null ? Number(t.rr_ratio) : null),
    style: (t) => String(t.style ?? ''),
    timeframe: (t) => String(t.timeframe ?? ''),
  })

  const strategiesSlice = strategies.slice(0, 12)
  const { sorted: sortedStrategies, sortKey: stratSortKey, sortDir: stratSortDir, handleSort: handleStratSort } = useSort(strategiesSlice, {
    flag: (s) => (s.take_trade ? 'TAKE' : s.forming ? 'FORMING' : 'watch'),
    name: (s) => String(s.name ?? ''),
    direction: (s) => String(s.direction ?? ''),
    style: (s) => String(s.style ?? ''),
    timeframe: (s) => String(s.timeframe ?? ''),
    confidence_pct: (s) => (s.confidence_pct != null ? Number(s.confidence_pct) : null),
    sl_pct: (s) => (s.sl_pct != null ? Number(s.sl_pct) : null),
    tp_pct: (s) => (s.tp_pct != null ? Number(s.tp_pct) : null),
  })

  if (data.error && !results.length) return <Alert type="error">{String(data.error)}</Alert>
  if (!results.length) return <p className="text-sm text-slate-500">No investigation results.</p>

  const news = (r.news as Row[]) ?? []
  const srImmediate = (sr?.immediate as Row) ?? {}
  const paPrimary = (priceAction?.primary as Row) ?? undefined
  const tradeSetup = r.trade_setup as Row | undefined
  const consensus = (r.analyst_consensus as Row) ?? {}
  const newsSentiment = r.news_sentiment as Row | undefined
  const analystSentiment = r.analyst_sentiment as Row | undefined

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((item, i) => (
          <Chip key={String(item.ticker)} selected={idx === i} onClick={() => setIdx(i)}>
            {String(item.ticker)}
          </Chip>
        ))}
      </div>

      <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
        <p className="text-lg font-semibold text-white">{String(r.display_name ?? r.ticker)}</p>
        <p className="text-sm text-slate-400">
          Price: {r.current_price != null ? `₹${Number(r.current_price).toFixed(2)}` : '—'}
          {' '}· {news.length} headlines · {analystCalls.length} analyst calls
          {r.mtf_label ? ` · MTF ${String(r.mtf_label)}` : ''}
          {r.pa_verdict != null ? ` · PA ${String(r.pa_verdict)}` : ''}
        </p>
        {r.error != null ? <Alert type="error">{String(r.error)}</Alert> : null}
      </div>

      {paPrimary && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Price Action (multi-indicator)</h4>
          <PriceActionSnapshot pa={paPrimary} title={`Primary (${String(priceAction?.primary_tf ?? '')})`} />
          {Object.keys(paByTf).length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-slate-500">By timeframe ({Object.keys(paByTf).length})</summary>
              <DataTable minWidth={640}>
                <thead>
                  <tr>
                    <SortableTh active={paTfSortKey === 'tf'} direction={paTfSortDir} onSort={() => handlePaTfSort('tf')}>TF</SortableTh>
                    <SortableTh active={paTfSortKey === 'bias'} direction={paTfSortDir} onSort={() => handlePaTfSort('bias')}>Bias</SortableTh>
                    <SortableTh active={paTfSortKey === 'trend'} direction={paTfSortDir} onSort={() => handlePaTfSort('trend')}>Trend</SortableTh>
                    <SortableTh active={paTfSortKey === 'rsi'} direction={paTfSortDir} onSort={() => handlePaTfSort('rsi')}>RSI</SortableTh>
                    <SortableTh active={paTfSortKey === 'ema_stack'} direction={paTfSortDir} onSort={() => handlePaTfSort('ema_stack')}>EMA stack</SortableTh>
                    <SortableTh active={paTfSortKey === 'vwap'} direction={paTfSortDir} onSort={() => handlePaTfSort('vwap')}>VWAP</SortableTh>
                    <SortableTh active={paTfSortKey === 'rvol'} direction={paTfSortDir} onSort={() => handlePaTfSort('rvol')}>RVOL</SortableTh>
                    <SortableTh active={paTfSortKey === 'verdict'} direction={paTfSortDir} onSort={() => handlePaTfSort('verdict')}>Verdict</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedPaByTf.map(([tf, p]) => (
                    <tr key={tf}>
                      <Td>{tf}</Td>
                      <Td className={verdictTone(String(p.overall_bias ?? ''))}>{String(p.overall_bias ?? '—')}</Td>
                      <Td>{String(p.trend ?? '—')}</Td>
                      <Td>{fmtN(p.rsi, 1)}</Td>
                      <Td>{String(p.ema_stack ?? '—')}</Td>
                      <Td>{String(p.vwap_position ?? '—')}</Td>
                      <Td>{fmtN(p.volume_ratio, 2)}x</Td>
                      <Td className={verdictTone(String(p.verdict ?? ''))}>{String(p.verdict ?? '—')}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </details>
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">News ({news.length})</h4>
          <ul className="max-h-56 space-y-2 overflow-y-auto text-sm">
            {news.slice(0, 12).map((a, i) => (
              <li key={i} className="text-slate-300">
                {a.link ? (
                  <a href={String(a.link)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                    {String(a.title ?? 'Article')}
                  </a>
                ) : String(a.title ?? 'Article')}
                <div className="text-xs text-slate-500">
                  {a.source != null ? String(a.source) : ''}{a.published != null ? ` · ${String(a.published)}` : ''}
                </div>
                {a.summary != null && String(a.summary).trim() && (
                  <p className="mt-0.5 text-xs text-slate-400 line-clamp-2">{String(a.summary)}</p>
                )}
              </li>
            ))}
            {!news.length && <li className="text-slate-500">No recent headlines.</li>}
          </ul>
        </div>
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Price windows</h4>
          <DataTable>
            <thead>
              <tr>
                <SortableTh active={pwSortKey === 'window'} direction={pwSortDir} onSort={() => handlePwSort('window')}>Window</SortableTh>
                <SortableTh active={pwSortKey === 'change_pct'} direction={pwSortDir} onSort={() => handlePwSort('change_pct')}>Change</SortableTh>
                <SortableTh active={pwSortKey === 'rsi'} direction={pwSortDir} onSort={() => handlePwSort('rsi')}>RSI</SortableTh>
                <SortableTh active={pwSortKey === 'rsi_zone'} direction={pwSortDir} onSort={() => handlePwSort('rsi_zone')}>Zone</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedPriceWindows.map((w) => (
                <tr key={String(w.window)}>
                  <Td>{String(w.window)} ({String(w.timeframe)})</Td>
                  <Td className={Number(w.change_pct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    {w.change_pct != null ? `${Number(w.change_pct) > 0 ? '+' : ''}${Number(w.change_pct).toFixed(2)}%` : '—'}
                  </Td>
                  <Td>{w.rsi != null ? Number(w.rsi).toFixed(1) : '—'}</Td>
                  <Td>{String(w.rsi_zone ?? '—')}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      </div>

      {Object.keys(srImmediate).length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Support / Resistance ({String(sr?.primary_tf ?? '—')})</h4>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label="Support" value={`${fmtN(srImmediate.support, 4)} (${String(srImmediate.support_strength ?? '—')}, ${String(srImmediate.support_touches ?? 0)} touches)`} />
            <StatCard label="Resistance" value={`${fmtN(srImmediate.resistance, 4)} (${String(srImmediate.resistance_strength ?? '—')})`} />
            <StatCard label="Event" value={String(srImmediate.event_label ?? SR_EVENT_LABELS[String(srImmediate.event ?? '')] ?? srImmediate.event ?? '—')} />
          </div>
          <p className="mt-2 text-xs text-slate-400">
            Breakout {fmtN(srImmediate.breakout_chance_pct, 0)}% · Breakdown {fmtN(srImmediate.breakdown_chance_pct, 0)}% · Bias {String(srImmediate.sr_bias ?? '—')}
          </p>
          {Object.keys(srByTf).length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-slate-500">By timeframe ({Object.keys(srByTf).length})</summary>
              <DataTable minWidth={640}>
                <thead>
                  <tr>
                    <SortableTh active={srTfSortKey === 'tf'} direction={srTfSortDir} onSort={() => handleSrTfSort('tf')}>TF</SortableTh>
                    <SortableTh active={srTfSortKey === 'support'} direction={srTfSortDir} onSort={() => handleSrTfSort('support')}>Support</SortableTh>
                    <SortableTh active={srTfSortKey === 'resistance'} direction={srTfSortDir} onSort={() => handleSrTfSort('resistance')}>Resistance</SortableTh>
                    <SortableTh active={srTfSortKey === 'breakout'} direction={srTfSortDir} onSort={() => handleSrTfSort('breakout')}>Breakout %</SortableTh>
                    <SortableTh active={srTfSortKey === 'breakdown'} direction={srTfSortDir} onSort={() => handleSrTfSort('breakdown')}>Breakdown %</SortableTh>
                    <SortableTh active={srTfSortKey === 'bias'} direction={srTfSortDir} onSort={() => handleSrTfSort('bias')}>Bias</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedSrByTf.map(([tf, s]) => (
                    <tr key={tf}>
                      <Td>{tf}</Td>
                      <Td>{fmtN(s.support, 4)}</Td>
                      <Td>{fmtN(s.resistance, 4)}</Td>
                      <Td>{fmtN(s.breakout_chance_pct, 0)}</Td>
                      <Td>{fmtN(s.breakdown_chance_pct, 0)}</Td>
                      <Td>{String(s.sr_bias ?? '—')}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </details>
          )}
        </div>
      )}

      {(analystCalls.length > 0 || Object.keys(consensus).length > 0) && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Analyst calls &amp; consensus</h4>
          <div className="mb-3 grid gap-3 sm:grid-cols-4">
            <StatCard label="Consensus" value={String(consensus.consensus ?? '—')} />
            <StatCard label="Buy / Sell / Hold" value={`${String(consensus.buy ?? 0)}/${String(consensus.sell ?? 0)}/${String(consensus.hold ?? 0)}`} />
            <StatCard label="Upgrades / Downgrades" value={`${String(consensus.upgrades ?? 0)}/${String(consensus.downgrades ?? 0)}`} />
            <StatCard label="Latest target" value={String(consensus.latest_target ?? '—')} />
          </div>
          {analystCalls.length > 0 && (
            <DataTable minWidth={640}>
              <thead>
                <tr>
                  <SortableTh active={acSortKey === 'action'} direction={acSortDir} onSort={() => handleAcSort('action')}>Action</SortableTh>
                  <SortableTh active={acSortKey === 'call_type'} direction={acSortDir} onSort={() => handleAcSort('call_type')}>Type</SortableTh>
                  <SortableTh active={acSortKey === 'brokerage'} direction={acSortDir} onSort={() => handleAcSort('brokerage')}>Brokerage</SortableTh>
                  <SortableTh active={acSortKey === 'price_target'} direction={acSortDir} onSort={() => handleAcSort('price_target')}>Target</SortableTh>
                  <SortableTh active={acSortKey === 'title'} direction={acSortDir} onSort={() => handleAcSort('title')}>Title</SortableTh>
                </tr>
              </thead>
              <tbody>
                {sortedAnalystCalls.map((c, i) => (
                  <tr key={i}>
                    <Td className={verdictTone(String(c.action ?? ''))}>{String(c.action ?? '—')}</Td>
                    <Td>{String(c.call_type ?? '—')}</Td>
                    <Td>{String(c.brokerage ?? '—')}</Td>
                    <Td>{fmtN(c.price_target)}{c.prior_target != null ? ` (was ${fmtN(c.prior_target)})` : ''}</Td>
                    <Td className="max-w-xs truncate text-slate-400">{String(c.title ?? '—')}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </div>
      )}

      {suggestedTrades.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Suggested trades</h4>
          {(newsSentiment || analystSentiment) && (
            <p className="mb-2 text-xs text-slate-500">
              News sentiment: {String(newsSentiment?.label ?? '—')} ({String(newsSentiment?.score ?? 0)}) ·
              {' '}Analyst tone: {String(analystSentiment?.label ?? '—')}
            </p>
          )}
          <DataTable minWidth={800}>
            <thead>
              <tr>
                <SortableTh active={tradeSortKey === 'status'} direction={tradeSortDir} onSort={() => handleTradeSort('status')}>Status</SortableTh>
                <SortableTh active={tradeSortKey === 'direction'} direction={tradeSortDir} onSort={() => handleTradeSort('direction')}>Direction</SortableTh>
                <SortableTh active={tradeSortKey === 'name'} direction={tradeSortDir} onSort={() => handleTradeSort('name')}>Name</SortableTh>
                <SortableTh active={tradeSortKey === 'confidence_pct'} direction={tradeSortDir} onSort={() => handleTradeSort('confidence_pct')}>Conf %</SortableTh>
                <SortableTh active={tradeSortKey === 'sl_pct'} direction={tradeSortDir} onSort={() => handleTradeSort('sl_pct')}>SL %</SortableTh>
                <SortableTh active={tradeSortKey === 'tp_pct'} direction={tradeSortDir} onSort={() => handleTradeSort('tp_pct')}>TP %</SortableTh>
                <SortableTh active={tradeSortKey === 'rr_ratio'} direction={tradeSortDir} onSort={() => handleTradeSort('rr_ratio')}>R:R</SortableTh>
                <SortableTh active={tradeSortKey === 'style'} direction={tradeSortDir} onSort={() => handleTradeSort('style')}>Style</SortableTh>
                <SortableTh active={tradeSortKey === 'timeframe'} direction={tradeSortDir} onSort={() => handleTradeSort('timeframe')}>TF</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedTrades.map((t, i) => (
                <tr key={i}>
                  <Td className={verdictTone(String(t.status ?? ''))}>{String(t.status ?? '—')}</Td>
                  <Td className={verdictTone(String(t.direction ?? ''))}>{String(t.direction ?? '—')}</Td>
                  <Td className="max-w-xs truncate">{String(t.name ?? '—')}</Td>
                  <Td>{fmtN(t.confidence_pct, 0)}</Td>
                  <Td>{fmtN(t.sl_pct)}</Td>
                  <Td>{fmtN(t.tp_pct)}</Td>
                  <Td>{t.rr_ratio != null ? String(t.rr_ratio) : '—'}</Td>
                  <Td>{String(t.style ?? '—')}</Td>
                  <Td>{String(t.timeframe ?? '—')}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}

      {tradeSetup && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <h4 className="text-sm font-medium text-emerald-400">Primary trade setup</h4>
          <p className="mt-1 text-white">
            {String(tradeSetup.name ?? 'Setup')} ·
            {' '}<span className={verdictTone(String(tradeSetup.direction ?? ''))}>{tradeSetup.take_trade ? `TAKE ${String(tradeSetup.direction ?? '')}` : 'NO TRADE / WAIT'}</span>
          </p>
          <p className="mt-1 text-sm text-slate-300">
            Conf {fmtN(tradeSetup.confidence_pct, 0)}% · SL -{fmtN(tradeSetup.sl_pct)}% · TP +{fmtN(tradeSetup.tp_pct)}% ·
            {' '}R:R {tradeSetup.rr_ratio != null ? String(tradeSetup.rr_ratio) : '—'} · {String(tradeSetup.style ?? '—')} · {String(tradeSetup.timeframe ?? '—')}
          </p>
          {tradeSetup.detail != null && <p className="mt-1 text-sm text-slate-400">{String(tradeSetup.detail)}</p>}
          {((tradeSetup.reasons as string[]) ?? []).length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-slate-400">
              {(tradeSetup.reasons as string[]).map((rr, i) => <li key={i}>• {rr}</li>)}
            </ul>
          )}
          {tradeSetup.invalidation != null && (
            <p className="mt-2 text-xs text-slate-500">Invalidation: {String(tradeSetup.invalidation)}</p>
          )}
        </div>
      )}

      {strategies.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Ranked setups ({strategies.length})</h4>
          <DataTable minWidth={800}>
            <thead>
              <tr>
                <SortableTh active={stratSortKey === 'flag'} direction={stratSortDir} onSort={() => handleStratSort('flag')}>Flag</SortableTh>
                <SortableTh active={stratSortKey === 'name'} direction={stratSortDir} onSort={() => handleStratSort('name')}>Name</SortableTh>
                <SortableTh active={stratSortKey === 'direction'} direction={stratSortDir} onSort={() => handleStratSort('direction')}>Direction</SortableTh>
                <SortableTh active={stratSortKey === 'style'} direction={stratSortDir} onSort={() => handleStratSort('style')}>Style</SortableTh>
                <SortableTh active={stratSortKey === 'timeframe'} direction={stratSortDir} onSort={() => handleStratSort('timeframe')}>TF</SortableTh>
                <SortableTh active={stratSortKey === 'confidence_pct'} direction={stratSortDir} onSort={() => handleStratSort('confidence_pct')}>Conf %</SortableTh>
                <SortableTh active={stratSortKey === 'sl_pct'} direction={stratSortDir} onSort={() => handleStratSort('sl_pct')}>SL %</SortableTh>
                <SortableTh active={stratSortKey === 'tp_pct'} direction={stratSortDir} onSort={() => handleStratSort('tp_pct')}>TP %</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedStrategies.map((s, i) => (
                <tr key={i}>
                  <Td>{s.take_trade ? 'TAKE' : s.forming ? 'FORMING' : 'watch'}</Td>
                  <Td className="max-w-xs truncate">{String(s.name ?? `Strategy ${i + 1}`)}</Td>
                  <Td className={verdictTone(String(s.direction ?? ''))}>{String(s.direction ?? '—')}</Td>
                  <Td>{String(s.style ?? '—')}</Td>
                  <Td>{String(s.timeframe ?? '—')}</Td>
                  <Td>{fmtN(s.confidence_pct, 0)}</Td>
                  <Td>{fmtN(s.sl_pct)}</Td>
                  <Td>{fmtN(s.tp_pct)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}

      {renderExtra ? renderExtra(r) : null}
    </div>
  )
}
