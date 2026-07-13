import { useState, type ReactNode } from 'react'
import { DataTable, Th, Td } from '../ui/Table'
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
            <Th>Ticker</Th>
            <Th>TF</Th>
            <Th>Score</Th>
            <Th>Rating</Th>
            <Th>Signal</Th>
            <Th>Conf</Th>
            <Th>RSI</Th>
            <Th>SL/TP %</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
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

  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!tickers.length) return <p className="text-sm text-slate-500">No MTF results.</p>

  const item = results[selected] as Row | undefined
  const confluence = item?.confluence as Row | undefined
  const setups = (item?.trade_setups as Row[]) ?? []
  const tfResults = (item?.timeframes as Record<string, Row>) ?? {}

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
            <thead><tr><Th>TF</Th><Th>Score</Th><Th>Bias</Th><Th>Conf</Th></tr></thead>
            <tbody>
              {Object.entries(tfResults).map(([tf, tfData]) => (
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

  if (data.error && !results.length) return <Alert type="error">{String(data.error)}</Alert>
  if (!results.length) return <p className="text-sm text-slate-500">No investigation results.</p>

  const r = results[idx] ?? results[0]
  const news = (r.news as Row[]) ?? []
  const priceWindows = (r.price_windows as Row[]) ?? []
  const sr = r.sr as Row | undefined
  const srImmediate = (sr?.immediate as Row) ?? {}
  const srByTf = (sr?.by_tf as Record<string, Row>) ?? {}
  const priceAction = r.price_action as Row | undefined
  const paPrimary = (priceAction?.primary as Row) ?? undefined
  const paByTf = (priceAction?.by_tf as Record<string, Row>) ?? {}
  const strategies = (r.strategies as Row[]) ?? []
  const tradeSetup = r.trade_setup as Row | undefined
  const suggestedTrades = (r.suggested_trades as Row[]) ?? []
  const analystCalls = (r.analyst_calls as Row[]) ?? []
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
                <thead><tr><Th>TF</Th><Th>Bias</Th><Th>Trend</Th><Th>RSI</Th><Th>EMA stack</Th><Th>VWAP</Th><Th>RVOL</Th><Th>Verdict</Th></tr></thead>
                <tbody>
                  {Object.entries(paByTf).map(([tf, p]) => (
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
            <thead><tr><Th>Window</Th><Th>Change</Th><Th>RSI</Th><Th>Zone</Th></tr></thead>
            <tbody>
              {priceWindows.map((w) => (
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
                <thead><tr><Th>TF</Th><Th>Support</Th><Th>Resistance</Th><Th>Breakout %</Th><Th>Breakdown %</Th><Th>Bias</Th></tr></thead>
                <tbody>
                  {Object.entries(srByTf).map(([tf, s]) => (
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
              <thead><tr><Th>Action</Th><Th>Type</Th><Th>Brokerage</Th><Th>Target</Th><Th>Title</Th></tr></thead>
              <tbody>
                {analystCalls.slice(0, 10).map((c, i) => (
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
            <thead><tr><Th>Status</Th><Th>Direction</Th><Th>Name</Th><Th>Conf %</Th><Th>SL %</Th><Th>TP %</Th><Th>R:R</Th><Th>Style</Th><Th>TF</Th></tr></thead>
            <tbody>
              {suggestedTrades.map((t, i) => (
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
            <thead><tr><Th>Flag</Th><Th>Name</Th><Th>Direction</Th><Th>Style</Th><Th>TF</Th><Th>Conf %</Th><Th>SL %</Th><Th>TP %</Th></tr></thead>
            <tbody>
              {strategies.slice(0, 12).map((s, i) => (
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
