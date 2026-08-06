import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Chip } from '../ui/Chip'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { SupportResistanceChart, type SRChartBar, type SRLevel } from '../trading-hubs/SupportResistanceChart'
import { AskAIPanel } from '../ai/AskAIPanel'

type Row = Record<string, unknown>

const FURTHER_ANALYSIS_LABELS: Record<string, string> = {
  pa_vp_smc: 'PA-VP-SMC',
  volume_spread_next_candle: 'Volume Spread - Next Candle',
  elliott_wave: 'Elliott Wave',
  bb_mean_reversion: 'BB Mean Reversion',
  support_resistance: 'Support & Resistance',
  mtf_trend_strength: 'Trend & Strength (MTF)',
}

function directionLabel(direction: string): string {
  return direction === 'LONG' ? 'BTST' : direction === 'SHORT' ? 'STBT' : direction
}

function SignalBadge({ signal, direction }: { signal: string; direction: string }) {
  const s = signal.toUpperCase()
  const cls =
    s === 'BULLISH'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : s === 'BEARISH'
        ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
        : 'border-slate-700/60 bg-slate-800/40 text-slate-400'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${cls}`}>
      {directionLabel(direction)} · {s}
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

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: digits }) : '—'
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
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade))
  const take = Boolean(result.take_trade)
  const signal = String(result.signal ?? 'NEUTRAL')
  const direction = String(result.direction ?? 'NONE')
  const isShort = direction === 'SHORT'

  const chartData = useMemo(
    () => ((result.chart_data as SRChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const levels = useMemo<SRLevel[]>(() => {
    const out: SRLevel[] = []
    if (take) {
      if (result.entry_price != null) out.push({ label: 'Entry', price: Number(result.entry_price), color: '#38bdf8' })
      if (result.stop_price != null) out.push({ label: 'SL', price: Number(result.stop_price), color: '#f87171' })
      if (result.target_price != null) out.push({ label: 'TP', price: Number(result.target_price), color: '#34d399' })
    }
    return out
  }, [take, result.entry_price, result.stop_price, result.target_price])

  const oiBuildup = result.oi_buildup as Row | null | undefined
  const relStrength = result.relative_strength as Row | null | undefined
  const histEdge = result.historical_edge as Row | null | undefined
  const lateSession = result.late_session_check as Row | null | undefined

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full flex-wrap items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 flex-wrap items-center gap-3 text-left"
        >
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {String(result.ltp)}
              {result.day_chg_pct != null && (
                <span className={Number(result.day_chg_pct) >= 0 ? 'ml-1 text-emerald-400' : 'ml-1 text-rose-400'}>
                  ({fmtNum(result.day_chg_pct, 2)}%)
                </span>
              )}
            </span>
          )}
          {take && <SignalBadge signal={signal} direction={direction} />}
          {take && <Badge action={direction === 'LONG' ? 'BUY' : 'SELL'} />}
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{fmtNum(result.confidence_pct, 0)}% confidence</span>
          )}
          {result.grade != null && <GradeBadge grade={String(result.grade)} />}
          {result.error ? <span className="text-xs text-amber-400">{String(result.error)}</span> : null}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker ?? '')} marketType={assetClass} compact />
      </div>
      {open && !result.error && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          {result.plain_english != null && (
            <div
              className={`rounded-lg border px-3 py-2.5 text-sm leading-relaxed ${
                take
                  ? isShort
                    ? 'border-rose-500/30 bg-rose-500/5 text-rose-100'
                    : 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100'
                  : 'border-slate-700/60 bg-slate-950/50 text-slate-300'
              }`}
            >
              {String(result.plain_english)}
            </div>
          )}

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {result.clv != null && <span>CLV: <strong className="text-slate-300">{fmtNum(result.clv, 2)}</strong></span>}
            {result.trend != null && <span>Trend: <strong className="text-slate-300">{String(result.trend)}</strong></span>}
            {result.rsi != null && <span>RSI: <strong className="text-slate-300">{fmtNum(result.rsi, 0)}</strong></span>}
            {result.volume_zscore != null && <span>Volume z: <strong className="text-slate-300">{fmtNum(result.volume_zscore, 1)}σ</strong></span>}
            {Boolean(result.volume_climax) && <span className="text-amber-400">Volume climax</span>}
            {result.vwap != null && <span>VWAP: <strong className="text-slate-300">{currency}{fmtNum(result.vwap)}</strong></span>}
            {relStrength && (
              <span>
                vs Nifty: <strong className={Number(relStrength.relative_pct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {Number(relStrength.relative_pct) >= 0 ? '+' : ''}{fmtNum(relStrength.relative_pct, 2)}pts
                </strong>
              </span>
            )}
          </div>

          {(oiBuildup || histEdge || lateSession) && (
            <div className="grid gap-2 sm:grid-cols-3">
              {oiBuildup && (
                <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-2.5">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Options OI buildup</p>
                  <p className="text-sm font-medium text-slate-200">{String(oiBuildup.label ?? '—')}</p>
                </div>
              )}
              {histEdge && (
                <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-2.5">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Historical follow-through</p>
                  <p className="text-sm font-medium text-slate-200">
                    {fmtNum(histEdge.hit_rate_pct, 0)}% ({String(histEdge.sample_size)} occurrences)
                  </p>
                </div>
              )}
              {lateSession && (
                <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-2.5">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Late-session check</p>
                  <p className={`text-sm font-medium ${lateSession.confirms ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {lateSession.confirms ? 'Held into close' : 'Faded into close'} ({fmtNum(lateSession.last_move_pct, 2)}%)
                  </p>
                </div>
              )}
            </div>
          )}

          {take && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-xs text-slate-500">Entry (near close)</p>
                  <p className="font-medium text-white">
                    {currency}
                    {fmtNum(result.entry_price)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Stop-loss</p>
                  <p className="font-medium text-rose-400">
                    {result.sl_pct != null ? `-${fmtNum(result.sl_pct, 1)}%` : '—'} ({currency}
                    {fmtNum(result.stop_price)})
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Target (next session)</p>
                  <p className="font-medium text-emerald-400">
                    {result.tp_pct != null ? `+${fmtNum(result.tp_pct, 1)}%` : '—'} ({currency}
                    {fmtNum(result.target_price)})
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Reward : Risk</p>
                  <p className="font-medium text-white">{result.rr != null ? `1 : ${fmtNum(result.rr, 2)}` : '—'}</p>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-slate-500">
                Overnight hold — no live stop-loss order protects this position while the market is closed. The
                stop above is the level to act on at tomorrow's open, not a guaranteed exit.
                {isShort && ' STBT requires execution via stock futures/options, not a cash-market sell.'}
              </p>
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <SupportResistanceChart
                chartData={chartData}
                supportZone={null}
                resistanceZone={null}
                trendlines={[]}
                lastClose={result.ltp as number | undefined}
                emas={{}}
                levels={levels}
                readingGuide="Daily candles. Entry/SL/TP lines (if shown) mark the suggested overnight BTST/STBT trade — entry is today's close, stop and target are ATR-scaled for a one-session hold."
              />
            </div>
          )}

          {((result.further_analysis_applied as string[]) ?? []).length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">Further analysis applied:</span>
              {(result.further_analysis_applied as string[]).map((c) => (
                <span key={c} className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-300">
                  {FURTHER_ANALYSIS_LABELS[c] ?? c}
                </span>
              ))}
            </div>
          )}

          {((result.confidence_reasons as string[]) ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-500">
              {(result.confidence_reasons as string[]).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}

          {((result.rules as string[]) ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-600">
              {(result.rules as string[]).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            systemPrompt={aiSystemPrompt}
            section={`pro-trade/btst/${String(result.ticker ?? '')}`}
            className="mt-0"
          />
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable' | 'btst' | 'stbt'

export function BtstPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = String(data.asset_class ?? 'india') as WatchlistMarket
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const [filter, setFilter] = useState<FilterMode>('all')

  const filtered = useMemo(() => {
    if (filter === 'actionable') return allResults.filter((r) => Boolean(r.take_trade))
    if (filter === 'btst') return allResults.filter((r) => r.direction === 'LONG')
    if (filter === 'stbt') return allResults.filter((r) => r.direction === 'SHORT')
    return allResults
  }, [allResults, filter])

  const sorted = useMemo(
    () =>
      [...filtered].sort((a, b) => {
        const at = a.take_trade ? 1 : 0
        const bt = b.take_trade ? 1 : 0
        if (at !== bt) return bt - at
        return Number(b.confidence_pct ?? 0) - Number(a.confidence_pct ?? 0)
      }),
    [filtered],
  )

  if (!allResults.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
        {data.entry_count != null && (
          <span>
            Actionable: <strong className="text-white">{String(data.entry_count)}</strong>
          </span>
        )}
        {data.btst_count != null && (
          <span>
            BTST: <strong className="text-emerald-400">{String(data.btst_count)}</strong>
          </span>
        )}
        {data.stbt_count != null && (
          <span>
            STBT: <strong className="text-rose-400">{String(data.stbt_count)}</strong>
          </span>
        )}
        {data.scanned != null && (
          <span>
            Scanned: <strong className="text-white">{String(data.scanned)}</strong>
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>
          All ({allResults.length})
        </Chip>
        <Chip selected={filter === 'actionable'} onClick={() => setFilter('actionable')}>
          Actionable ({allResults.filter((r) => r.take_trade).length})
        </Chip>
        <Chip selected={filter === 'btst'} onClick={() => setFilter('btst')}>
          BTST only
        </Chip>
        <Chip selected={filter === 'stbt'} onClick={() => setFilter('stbt')}>
          STBT only
        </Chip>
      </div>

      <div className="space-y-2">
        {sorted.length === 0 && <p className="text-sm text-slate-500">No tickers match this filter.</p>}
        {sorted.map((res, i) => (
          <TickerResultCard
            key={String(res.ticker ?? i)}
            result={res}
            index={i}
            currency={currency}
            assetClass={assetClass}
            showCharts={showCharts}
            aiSystemPrompt={aiSystemPrompt}
          />
        ))}
      </div>
      {data.disclaimer != null && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
