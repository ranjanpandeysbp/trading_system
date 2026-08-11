import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { AskAIPanel } from '../ai/AskAIPanel'
import { VolumeProfileChart, type VpChartBar, type VpLevel, type VpSeries } from './VolumeProfileChart'
import { TradeSetupBanner, tradeSetupFromResult } from './TradeSetupBanner'

type Row = Record<string, unknown>

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: digits }) : '—'
}

function SignalBadge({ signal }: { signal: string }) {
  const s = signal.toUpperCase()
  const cls =
    s === 'BULLISH'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : s === 'BEARISH'
        ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
        : s === 'WATCH'
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
          : 'border-slate-700/60 bg-slate-800/40 text-slate-400'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${cls}`}>
      {s}
    </span>
  )
}

function GradeBadge({ grade }: { grade: string }) {
  const cls =
    grade === 'A'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : grade === 'B'
        ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
        : 'border-slate-700/60 bg-slate-800/40 text-slate-400'
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold ${cls}`}>
      Grade {grade}
    </span>
  )
}

function TickerResultCard({
  result,
  index,
  currency,
  assetClass,
  showCharts,
  aiSystemPrompt,
}: {
  result: Row
  index: number
  currency: string
  assetClass: WatchlistMarket
  showCharts: boolean
  aiSystemPrompt: string
}) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade) || String(result.signal) === 'WATCH')
  const take = Boolean(result.take_trade)
  const checks = (result.checks as Row[] | undefined) ?? []
  const metrics = (result.metrics as Row | undefined) ?? {}
  const action = String((result.trade_suggestion as Row | undefined)?.action ?? result.action ?? 'WAIT')
  const tips = (result.pro_checklist as string[] | undefined) ?? []

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(() => {
    const fromApi = (result.chart_series as VpSeries[] | undefined) ?? []
    return fromApi.length
      ? fromApi
      : [
          { key: 'bb_upper', label: 'BB Upper', color: '#94a3b8' },
          { key: 'bb_mid', label: 'BB Mid', color: '#38bdf8' },
          { key: 'bb_lower', label: 'BB Lower', color: '#94a3b8' },
          { key: 'ema5', label: 'EMA5', color: '#2dd4bf' },
          { key: 'ema9', label: 'EMA9', color: '#fbbf24' },
          { key: 'ema50', label: 'EMA50', color: '#a78bfa' },
        ]
  }, [result.chart_series])
  const levels = useMemo<VpLevel[]>(() => {
    return ((result.chart_levels as VpLevel[] | undefined) ?? []).filter((l) => l && l.price != null)
  }, [result.chart_levels])

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full flex-wrap items-center gap-3 px-4 py-3">
        <button type="button" onClick={() => setOpen((o) => !o)} className="flex flex-1 flex-wrap items-center gap-3 text-left">
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.timeframe != null && (
            <span className="rounded-md border border-slate-700/60 bg-slate-800/50 px-1.5 py-0.5 text-[11px] text-slate-400">
              {String(result.timeframe)}
            </span>
          )}
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {fmtNum(result.ltp)}
            </span>
          )}
          <SignalBadge signal={String(result.signal ?? 'WAIT')} />
          {take && <Badge action={action === 'SELL' ? 'SELL' : 'BUY'} />}
          {result.grade != null && <GradeBadge grade={String(result.grade)} />}
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{fmtNum(result.confidence_pct, 0)}% conf</span>
          )}
          {(() => {
            const ema = (result.ema_continuation as Row | undefined) ?? {}
            if (ema.confidence_pct == null) return null
            const dir = String(ema.short_term_direction ?? '')
            return (
              <span className="text-[11px] text-teal-300/90">
                EMA {dir || '—'} · next2 {ema.will_continue ? 'cont' : 'stall'} · {fmtNum(ema.confidence_pct, 0)}%
              </span>
            )
          })()}
          {result.sl_pct != null && result.tp_pct != null && (
            <span className="text-xs text-slate-400">
              SL {fmtNum(result.sl_pct, 1)}% · TP {fmtNum(result.tp_pct, 1)}%
            </span>
          )}
          {result.error != null && <span className="text-xs text-amber-400">{String(result.error)}</span>}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker ?? '')} marketType={assetClass} compact />
      </div>

      {open && !result.error && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          <TradeSetupBanner setup={tradeSetupFromResult(result)} />
          {(result.plain_english != null || result.reason != null) && (
            <div
              className={`rounded-lg border px-3 py-2.5 text-sm leading-relaxed ${
                take
                  ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100'
                  : 'border-slate-700/60 bg-slate-950/50 text-slate-300'
              }`}
            >
              {String(result.plain_english ?? result.reason)}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
            <div>
              <p className="text-xs text-slate-500">Entry</p>
              <p className="font-medium text-white">
                {currency}
                {fmtNum(result.entry_price)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Stop (SL%)</p>
              <p className="font-medium text-rose-400">
                {result.sl_pct != null ? `${fmtNum(result.sl_pct, 1)}%` : '—'} · {currency}
                {fmtNum(result.stop_price)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">T1 (TP%)</p>
              <p className="font-medium text-emerald-400">
                {result.tp_pct != null ? `${fmtNum(result.tp_pct, 1)}%` : '—'} · {currency}
                {fmtNum(result.target_price)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">T2</p>
              <p className="font-medium text-sky-300">
                {currency}
                {fmtNum(result.target2_price)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">RR · RSI</p>
              <p className="font-medium text-slate-200">
                {result.rr != null ? `1:${fmtNum(result.rr, 1)}` : '—'} · {fmtNum(metrics.rsi, 1)}
              </p>
            </div>
          </div>

          {(() => {
            const ema = (result.ema_continuation as Row | undefined) ?? {}
            if (!ema || ema.error) return null
            const dir = String(ema.short_term_direction ?? 'flat')
            const dirCls =
              dir === 'rising' ? 'text-emerald-300' : dir === 'falling' ? 'text-rose-300' : 'text-slate-300'
            const will = ema.will_continue
            return (
              <div className="rounded-lg border border-teal-500/25 bg-teal-500/5 px-3 py-2.5 text-sm text-slate-200">
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-teal-300/90">
                  EMA5 / EMA9 · next-2 continuation ({String(ema.history_days ?? 100)}d hist)
                </p>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    <p className="text-[11px] text-slate-500">vs EMA5</p>
                    <p className="font-medium text-white">
                      {String(ema.price_vs_ema5 ?? '—')} ({fmtNum(ema.distance_ema5_pct, 2)}%)
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-500">vs EMA9</p>
                    <p className="font-medium text-white">
                      {String(ema.price_vs_ema9 ?? '—')} ({fmtNum(ema.distance_ema9_pct, 2)}%)
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-500">Short-term</p>
                    <p className={`font-medium ${dirCls}`}>
                      {dir} · {String(ema.intensity ?? '—')} ({fmtNum(ema.move_pct, 2)}%)
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-500">Next {String(ema.continuation_bars ?? 2)} candles</p>
                    <p className="font-medium text-white">
                      {will == null ? '—' : will ? 'Likely continue' : 'Stall / reverse'}
                      {ema.confidence_pct != null ? ` · ${fmtNum(ema.confidence_pct, 0)}% conf` : ''}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      Pred move {ema.predicted_next_2_return_pct != null ? `${Number(ema.predicted_next_2_return_pct) >= 0 ? '+' : ''}${fmtNum(ema.predicted_next_2_return_pct, 2)}%` : '—'}
                      {ema.predicted_intensity != null ? ` · ${String(ema.predicted_intensity)}` : ''}
                      {ema.continuation_rate_pct != null
                        ? ` · hist ${fmtNum(ema.continued_count, 0)}/${fmtNum(ema.analogues, 0)} (${fmtNum(ema.continuation_rate_pct, 0)}%)`
                        : ''}
                    </p>
                  </div>
                </div>
                {ema.plain_english != null && (
                  <p className="mt-2 text-xs leading-relaxed text-slate-400">{String(ema.plain_english)}</p>
                )}
                {Array.isArray(ema.recent_analogues) && (ema.recent_analogues as Row[]).length > 0 && (
                  <div className="mt-2 overflow-x-auto">
                    <p className="mb-1 text-[11px] font-medium text-slate-500">Recent similar setups</p>
                    <table className="w-full text-left text-[11px] text-slate-400">
                      <thead>
                        <tr className="text-slate-500">
                          <th className="pr-2">When</th>
                          <th className="pr-2">Move</th>
                          <th className="pr-2">Next-2</th>
                          <th>Continued?</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(ema.recent_analogues as Row[]).slice(-6).map((a, i) => (
                          <tr key={`${a.time}-${i}`}>
                            <td className="pr-2 whitespace-nowrap">{String(a.time ?? '').replace('T', ' ').slice(0, 16)}</td>
                            <td className="pr-2">{fmtNum(a.move_pct, 2)}%</td>
                            <td className="pr-2">{fmtNum(a.next_2_return_pct, 2)}%</td>
                            <td className={a.continued ? 'text-emerald-400' : 'text-rose-400'}>
                              {a.continued ? 'yes' : 'no'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )
          })()}

          {checks.length > 0 && (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {checks.map((ch) => {
                const ok = Boolean(ch.passed ?? ch.pass)
                return (
                  <div
                    key={String(ch.id)}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                      ok
                        ? 'border-emerald-500/25 bg-emerald-500/5 text-emerald-200'
                        : 'border-slate-800/80 bg-slate-950/40 text-slate-500'
                    }`}
                  >
                    <span className="font-medium">
                      {ok ? '✓' : '✗'} {String(ch.label)}
                    </span>
                    <p className="mt-0.5 text-[11px] opacity-80">{String(ch.detail)}</p>
                  </div>
                )
              })}
            </div>
          )}

          {tips.length > 0 && (
            <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2 text-xs text-slate-400">
              <p className="mb-1 font-medium text-slate-300">Pro checklist</p>
              <ul className="list-inside list-disc space-y-0.5">
                {tips.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <VolumeProfileChart
              chartData={chartData}
              series={series}
              levels={levels}
              readingGuide="Grey = BB · Blue mid · Teal EMA5 · Gold EMA9 · Purple EMA50. Buy: lower band + RSI≤35 + low vol at support, close above EMA9. Sell: upper + RSI≥70 + high vol at resistance, close below EMA9. Continuation uses ~100d EMA analogues for next-2 candles."
            />
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/bb-rsi-vol/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

export function BbRsiVolPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const results = (data.results as Row[] | undefined) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = (data.asset_class as WatchlistMarket) || 'india'
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const [filter, setFilter] = useState<'all' | 'actionable' | 'watch'>('all')

  const filtered = useMemo(() => {
    if (filter === 'actionable') return results.filter((r) => r.take_trade)
    if (filter === 'watch') return results.filter((r) => String(r.signal) === 'WATCH')
    return results
  }, [results, filter])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span>
          Scanned {String(data.scanned ?? results.length)} · Entries {String(data.entry_count ?? 0)}
        </span>
        <button type="button" className={`rounded-full border px-2.5 py-1 ${filter === 'all' ? 'border-sky-500/40 text-sky-200' : 'border-slate-700'}`} onClick={() => setFilter('all')}>
          All
        </button>
        <button type="button" className={`rounded-full border px-2.5 py-1 ${filter === 'actionable' ? 'border-emerald-500/40 text-emerald-200' : 'border-slate-700'}`} onClick={() => setFilter('actionable')}>
          Take
        </button>
        <button type="button" className={`rounded-full border px-2.5 py-1 ${filter === 'watch' ? 'border-amber-500/40 text-amber-200' : 'border-slate-700'}`} onClick={() => setFilter('watch')}>
          Watch
        </button>
      </div>
      {filtered.map((r, i) => (
        <TickerResultCard
          key={`${r.ticker}-${r.timeframe}-${i}`}
          result={r}
          index={i}
          currency={currency}
          assetClass={assetClass}
          showCharts={showCharts}
          aiSystemPrompt={aiSystemPrompt}
        />
      ))}
      {!filtered.length && <p className="text-sm text-slate-400">No rows for this filter.</p>}
    </div>
  )
}
