import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { AskAIPanel } from '../ai/AskAIPanel'
import { VolumeProfileChart, type VpChartBar, type VpLevel, type VpSeries } from './VolumeProfileChart'
import { TradeSetupBanner, tradeSetupFromResult } from './TradeSetupBanner'
import { tickerNameOnly } from '../ui/tickerDisplay'

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
  emaPeriod,
  mode,
}: {
  result: Row
  index: number
  currency: string
  assetClass: WatchlistMarket
  showCharts: boolean
  aiSystemPrompt: string
  emaPeriod: number
  mode: 'price' | 'crossover'
}) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade) || String(result.signal) === 'WATCH')
  const take = Boolean(result.take_trade)
  const checks = (result.checks as Row[] | undefined) ?? []
  const metrics = (result.metrics as Row | undefined) ?? {}
  const action = String((result.trade_suggestion as Row | undefined)?.action ?? result.action ?? 'WAIT')
  const tips = (result.pro_checklist as string[] | undefined) ?? []
  const period = Number(result.ema_period ?? metrics.ema_period ?? emaPeriod) || emaPeriod
  const sectionBase = mode === 'crossover' ? 'ema5-9-cross' : `ema${period}-cross`
  const emaValue =
    mode === 'crossover'
      ? metrics.ema5
      : (metrics[`ema${period}`] ?? metrics.ema ?? metrics.ema9)

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(() => {
    const fromApi = (result.chart_series as VpSeries[] | undefined) ?? []
    if (fromApi.length) return fromApi
    if (mode === 'crossover') {
      return [
        { key: 'bb_upper', label: 'BB Upper', color: '#94a3b8' },
        { key: 'bb_mid', label: 'BB Mid', color: '#38bdf8' },
        { key: 'bb_lower', label: 'BB Lower', color: '#94a3b8' },
        { key: 'ema5', label: 'EMA5', color: '#34d399' },
        { key: 'ema9', label: 'EMA9', color: '#fbbf24' },
      ]
    }
    return [
      { key: 'bb_upper', label: 'BB Upper', color: '#94a3b8' },
      { key: 'bb_mid', label: 'BB Mid', color: '#38bdf8' },
      { key: 'bb_lower', label: 'BB Lower', color: '#94a3b8' },
      { key: `ema${period}`, label: `EMA${period}`, color: '#fbbf24' },
    ]
  }, [result.chart_series, mode, period])
  const levels = useMemo<VpLevel[]>(() => {
    return ((result.chart_levels as VpLevel[] | undefined) ?? []).filter((l) => l && l.price != null)
  }, [result.chart_levels])

  const crossLabel =
    mode === 'crossover'
      ? Boolean(metrics.cross_up)
        ? '↑ 5/9 cross'
        : Boolean(metrics.cross_down)
          ? '↓ 5/9 cross'
          : null
      : Boolean(metrics.cross_up)
        ? `↑ cross ${period}EMA`
        : Boolean(metrics.cross_down)
          ? `↓ cross ${period}EMA`
          : null

  const bbZone = String(result.bb_zone ?? metrics.bb_zone ?? '')
  const pricePhase = String(result.price_phase ?? metrics.price_phase ?? '')
  const phaseBadge =
    pricePhase === 'upward'
      ? '↑ upward phase'
      : pricePhase === 'descent'
        ? '↓ descent phase'
        : pricePhase === 'sideways'
          ? '↔ sideways phase'
          : null
  const zoneBadge =
    bbZone === 'lower'
      ? 'Lower BB'
      : bbZone === 'upper'
        ? 'Upper BB'
        : bbZone === 'mid'
          ? 'Mid BB'
          : null

  const readingGuide =
    mode === 'crossover'
      ? 'Green = EMA5 · Gold = EMA9 · Grey = BB · Blue mid. Long: EMA5 crosses above EMA9 with price above both + RSI/volume. Short: opposite. T1 mid BB · T2 outer.'
      : `Gold = ${period} EMA · Grey = BB · Blue mid. Long: near Lower BB + RSI < 35. Short: Upper BB + RSI > 65. Mid BB = wait. Check last ~1000-bar upward/descent phase. T1 mid · T2 outer.`

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full flex-wrap items-center gap-3 px-4 py-3">
        <button type="button" onClick={() => setOpen((o) => !o)} className="flex flex-1 flex-wrap items-center gap-3 text-left">
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <span className="font-semibold text-white">
            {tickerNameOnly(result) || String(result.ticker)}
          </span>
          {tickerNameOnly(result) && (
            <span className="text-[11px] text-slate-500">{String(result.ticker)}</span>
          )}
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
          {zoneBadge && (
            <span className={`text-[11px] ${bbZone === 'lower' ? 'text-emerald-300' : bbZone === 'upper' ? 'text-rose-300' : 'text-slate-400'}`}>
              {zoneBadge}
            </span>
          )}
          {phaseBadge && (
            <span className={`text-[11px] ${pricePhase === 'upward' ? 'text-emerald-300' : pricePhase === 'descent' ? 'text-rose-300' : 'text-slate-400'}`}>
              {phaseBadge}
            </span>
          )}
          {crossLabel && (
            <span className={`text-[11px] ${String(crossLabel).startsWith('↑') ? 'text-emerald-300' : 'text-rose-300'}`}>
              {crossLabel}
            </span>
          )}
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
              <p className="text-xs text-slate-500">T1 mid BB</p>
              <p className="font-medium text-emerald-400">
                {result.tp_pct != null ? `${fmtNum(result.tp_pct, 1)}%` : '—'} · {currency}
                {fmtNum(result.target_price)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">T2 outer BB</p>
              <p className="font-medium text-sky-300">
                {currency}
                {fmtNum(result.target2_price)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">
                {mode === 'crossover' ? 'RR · RSI · 5/9' : `RR · RSI · EMA${period}`}
              </p>
              <p className="font-medium text-slate-200">
                {result.rr != null ? `1:${fmtNum(result.rr, 1)}` : '—'} · {fmtNum(metrics.rsi, 1)} ·{' '}
                {mode === 'crossover'
                  ? `${fmtNum(metrics.ema5)} / ${fmtNum(metrics.ema9)}`
                  : fmtNum(emaValue)}
              </p>
            </div>
          </div>

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
              ticker={String(result.ticker ?? '')}
              assetClass={assetClass}
              series={series}
              levels={levels}
              readingGuide={readingGuide}
            />
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/${sectionBase}/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

export function EmaPriceCrossPanel({
  data,
  showCharts = false,
  emaPeriod = 9,
}: {
  data: Row
  showCharts?: boolean
  emaPeriod?: number
}) {
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
          emaPeriod={emaPeriod}
          mode="price"
        />
      ))}
      {!filtered.length && <p className="text-sm text-slate-400">No rows for this filter.</p>}
    </div>
  )
}

/** Unified EMA Cross results — period comes from scan payload / each row. */
export function Ema9CrossPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allowed = new Set([5, 9, 20, 50, 200])
  const fromSummary = Number((data as Row).ema_period)
  const fromRow = Number((((data.results as Row[] | undefined) ?? [])[0] as Row | undefined)?.ema_period)
  const period = allowed.has(fromSummary) ? fromSummary : allowed.has(fromRow) ? fromRow : 9
  return <EmaPriceCrossPanel data={data} showCharts={showCharts} emaPeriod={period} />
}

/** @deprecated Prefer Ema9CrossPanel — period is read from the scan. */
export function Ema5CrossPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  return <Ema9CrossPanel data={data} showCharts={showCharts} />
}

export function Ema59CrossPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
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
          emaPeriod={5}
          mode="crossover"
        />
      ))}
      {!filtered.length && <p className="text-sm text-slate-400">No rows for this filter.</p>}
    </div>
  )
}
