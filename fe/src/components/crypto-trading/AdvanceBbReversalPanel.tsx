import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { VolumeProfileChart, type VpChartBar, type VpLevel, type VpSeries } from '../pro-trade/VolumeProfileChart'
import { TradeSetupBanner, tradeSetupFromResult } from '../pro-trade/TradeSetupBanner'
import { tickerNameOnly } from '../ui/tickerDisplay'

type Row = Record<string, unknown>

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: digits }) : '—'
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

function TickerResultCard({
  result,
  index,
  currency,
  showCharts,
}: {
  result: Row
  index: number
  currency: string
  showCharts: boolean
}) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade) || String(result.signal) === 'WATCH')
  const take = Boolean(result.take_trade)
  const checks = (result.checks as Row[] | undefined) ?? []
  const metrics = (result.metrics as Row | undefined) ?? {}
  const money = (result.money_plan as Row | undefined) ?? {}
  const tips = (result.pro_checklist as string[] | undefined) ?? []
  const action = String((result.trade_suggestion as Row | undefined)?.action ?? result.action ?? 'WAIT')

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
          { key: 'ema_trend', label: 'EMA20', color: '#fbbf24' },
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
          <span className="font-semibold text-white">{tickerNameOnly(result) || String(result.ticker)}</span>
          {result.timeframe != null && (
            <span className="rounded-md border border-slate-700/60 bg-slate-800/50 px-1.5 py-0.5 text-[11px] text-slate-400">
              {String(result.timeframe)}
            </span>
          )}
          {(result.ltp != null || metrics.price != null) && (
            <span className="text-sm text-slate-400">
              {currency}
              {fmtNum(result.ltp ?? metrics.price, 4)}
            </span>
          )}
          <SignalBadge signal={String(result.signal ?? 'WAIT')} />
          {take && <Badge action={action === 'SELL' ? 'SELL' : 'BUY'} />}
          <span className="text-[11px] text-slate-500">~80%</span>
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{fmtNum(result.confidence_pct, 0)}% conf</span>
          )}
          {result.error != null && <span className="text-xs text-amber-400">{String(result.error)}</span>}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker ?? '')} marketType={'crypto' as WatchlistMarket} compact />
      </div>

      {open && !result.error && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          <TradeSetupBanner setup={tradeSetupFromResult(result)} />
          {(result.plain_english != null || result.reason != null) && (
            <div
              className={`rounded-lg border px-3 py-2.5 text-sm leading-relaxed ${
                take
                  ? 'border-sky-500/30 bg-sky-500/5 text-sky-100'
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
                {fmtNum(result.entry_price, 4)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Stop</p>
              <p className="font-medium text-rose-400">
                {currency}
                {fmtNum(result.stop_price, 4)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Target (opp BB)</p>
              <p className="font-medium text-emerald-400">
                {currency}
                {fmtNum(result.target_price, 4)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Money plan</p>
              <p className="font-medium text-slate-200">
                SL ₹{fmtNum(money.sl_inr ?? 200, 0)} · TGT ₹{fmtNum(money.tgt_inr ?? 600, 0)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">BB U / Mid / L</p>
              <p className="font-medium text-slate-200 text-[11px]">
                {fmtNum(metrics.bb_upper, 3)} / {fmtNum(metrics.bb_mid, 3)} / {fmtNum(metrics.bb_lower, 3)}
              </p>
            </div>
          </div>

          {checks.length > 0 && (
            <div className="grid gap-1.5 sm:grid-cols-3">
              {checks.map((ch) => {
                const ok = Boolean(ch.passed ?? ch.pass ?? ch.ok)
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
                      {ok ? '✓' : '✗'} {String(ch.label ?? ch.id)}
                    </span>
                    <p className="mt-0.5 text-[11px] opacity-80">{String(ch.detail)}</p>
                  </div>
                )
              })}
            </div>
          )}

          {tips.length > 0 && (
            <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2 text-xs text-slate-400">
              <p className="mb-1 font-medium text-slate-300">Avoid bad trades</p>
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
              assetClass="crypto"
              series={series}
              levels={levels}
              readingGuide="Grey = Bollinger bands · Yellow = EMA trend. SHORT: outside upper → close inside → target lower. LONG: outside lower → close inside → target upper. Prefer with-trend + S/R."
            />
          )}
        </div>
      )}
    </div>
  )
}

export function AdvanceBbReversalPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const results = (data.results as Row[] | undefined) ?? []
  const currency = String(data.currency ?? '$')
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
          Scanned {String(data.scanned ?? results.length)} · Entries {String(data.entry_count ?? 0)} · ~80% claim
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
          key={`${r.ticker}-${i}`}
          result={r}
          index={i}
          currency={currency}
          showCharts={showCharts}
        />
      ))}
      {!filtered.length && <p className="text-sm text-slate-400">No rows for this filter.</p>}
    </div>
  )
}
