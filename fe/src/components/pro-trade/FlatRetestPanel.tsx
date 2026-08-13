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

function PhaseBadge({ phase }: { phase: string }) {
  const p = phase || 'NO_FLAT'
  const hot = p === 'LONG' || p === 'SHORT'
  const mid = p.includes('BREAK') || p.includes('RETEST') || p.includes('REJECT')
  const cls = hot
    ? 'border-sky-500/40 bg-sky-500/10 text-sky-200'
    : mid
      ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
      : 'border-slate-700/60 bg-slate-800/40 text-slate-400'
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {p.replaceAll('_', ' ')}
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
  const phase = String(result.phase ?? metrics.phase ?? 'NO_FLAT')

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(() => {
    const fromApi = (result.chart_series as VpSeries[] | undefined) ?? []
    return fromApi.length
      ? fromApi
      : [
          { key: 'resistance', label: 'Resistance', color: '#f87171' },
          { key: 'support', label: 'Support', color: '#34d399' },
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
          <PhaseBadge phase={phase} />
          {take && <Badge action={action === 'SELL' ? 'SELL' : 'BUY'} />}
          {result.grade != null && <GradeBadge grade={String(result.grade)} />}
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{fmtNum(result.confidence_pct, 0)}% conf</span>
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
              <p className="text-xs text-slate-500">T1</p>
              <p className="font-medium text-emerald-400">
                {result.tp_pct != null ? `${fmtNum(result.tp_pct, 1)}%` : '—'} · {currency}
                {fmtNum(result.target_price)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Box R / S</p>
              <p className="font-medium text-slate-200">
                {fmtNum(metrics.resistance)} / {fmtNum(metrics.support)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">RR · flat bars</p>
              <p className="font-medium text-slate-200">
                {result.rr != null ? `1:${fmtNum(result.rr, 1)}` : '—'} · {fmtNum(metrics.flat_bars, 0)}
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
              readingGuide="Red = box resistance · Green = cons low. LONG = break → retest hold as support. SHORT = reject → break low → failed retest. Mid-sequence = WATCH only."
            />
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/flat-retest/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

export function FlatRetestPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
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
