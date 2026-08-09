import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Chip } from '../ui/Chip'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { AskAIPanel } from '../ai/AskAIPanel'
import { VolumeProfileChart, type VpChartBar, type VpLevel, type VpSeries } from './VolumeProfileChart'

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
  const checks = (result.checks as Row[] | undefined) ?? []
  const metrics = (result.metrics as Row | undefined) ?? {}

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(() => {
    const fromApi = (result.chart_series as VpSeries[] | undefined) ?? []
    return fromApi.length
      ? fromApi
      : [
          { key: 'sma50', label: 'SMA50', color: '#38bdf8' },
          { key: 'sma100', label: 'SMA100', color: '#a78bfa' },
          { key: 'sma200', label: 'SMA200', color: '#f59e0b' },
          { key: 'car', label: 'CAR', color: '#f472b6' },
        ]
  }, [result.chart_series])
  const levels = useMemo<VpLevel[]>(() => {
    const fromApi = (result.chart_levels as VpLevel[] | undefined) ?? []
    return fromApi.length ? fromApi : []
  }, [result.chart_levels])

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full flex-wrap items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 flex-wrap items-center gap-3 text-left"
        >
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          {result.rank != null && (
            <span className="rounded-md border border-slate-700/60 bg-slate-800/50 px-1.5 py-0.5 text-[11px] text-slate-400">
              #{String(result.rank)}
            </span>
          )}
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {String(result.ltp)}
            </span>
          )}
          <SignalBadge signal={String(result.signal ?? 'WAIT')} />
          {take && <Badge action="BUY" />}
          {metrics.pct_above_200 != null && (
            <span className="text-xs text-amber-200/90">+{fmtNum(metrics.pct_above_200, 2)}% vs 200</span>
          )}
          {metrics.car_streak_days != null && (
            <span className="text-xs text-slate-400">
              CAR {String(metrics.car_streak_days)}/{String(metrics.car_days_required ?? 10)}d
            </span>
          )}
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{fmtNum(result.confidence_pct, 0)}%</span>
          )}
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
                  ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100'
                  : 'border-slate-700/60 bg-slate-950/50 text-slate-300'
              }`}
            >
              {String(result.plain_english)}
            </div>
          )}

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {metrics.sma200 != null && (
              <span>
                SMA200: <strong className="text-slate-300">{fmtNum(metrics.sma200)}</strong>
              </span>
            )}
            {metrics.car != null && (
              <span>
                CAR: <strong className="text-pink-300">{fmtNum(metrics.car)}</strong>
              </span>
            )}
            {metrics.week52_high != null && (
              <span>
                52w high: <strong className="text-slate-300">{fmtNum(metrics.week52_high)}</strong>
              </span>
            )}
            <span className="text-slate-400">Exit +{fmtNum(metrics.profit_target_pct ?? 6.28, 2)}% of avg · no hard SL</span>
          </div>

          {checks.length > 0 && (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {checks.map((ch) => {
                const ok = Boolean(ch.pass)
                return (
                  <div
                    key={String(ch.id)}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                      ok
                        ? 'border-emerald-500/25 bg-emerald-500/5 text-emerald-200'
                        : 'border-slate-800/80 bg-slate-950/40 text-slate-500'
                    }`}
                  >
                    <span className="font-medium">{ok ? '✓' : '✗'} {String(ch.label)}</span>
                    <p className="mt-0.5 text-[11px] opacity-80">{String(ch.detail)}</p>
                  </div>
                )
              })}
            </div>
          )}

          {take && (
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-xs text-slate-500">Entry (scan close)</p>
                <p className="font-medium text-white">{currency}{fmtNum(result.entry_price)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Target +6.28%</p>
                <p className="font-medium text-emerald-400">{currency}{fmtNum(result.target_price)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">SIP line (−20%)</p>
                <p className="font-medium text-amber-300">{currency}{fmtNum(metrics.sip_trigger_from_ltp)}</p>
              </div>
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart
                chartData={chartData}
                levels={levels}
                series={series}
                readingGuide="Blue/purple/amber = SMA50/100/200. Pink = CAR (cumulative average from 52w high). Buy when price is above all DMAs, not more than 10% above the 200, and CAR has risen for N days. Prefer names closest to the 200 DMA. Exit all at average + 6.28%."
              />
            </div>
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/3-in-1-trade-system/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable' | 'watch'

export function ThreeInOneTradeSystemPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = String(data.asset_class ?? 'india') as WatchlistMarket
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const playbook = (data.capital_playbook as Row | undefined) ?? undefined
  const [filter, setFilter] = useState<FilterMode>('all')

  const filtered = useMemo(() => {
    if (filter === 'actionable') return allResults.filter((r) => Boolean(r.take_trade))
    if (filter === 'watch') return allResults.filter((r) => String(r.signal ?? '') === 'WATCH')
    return allResults
  }, [allResults, filter])

  if (!allResults.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
        {data.entry_count != null && (
          <span>
            BUY signals: <strong className="text-white">{String(data.entry_count)}</strong>
          </span>
        )}
        {data.scanned != null && (
          <span>
            Scanned: <strong className="text-white">{String(data.scanned)}</strong>
          </span>
        )}
        <span className="text-xs text-slate-500">Ranked closest → farthest from 200 DMA among buys</span>
      </div>

      {playbook && (
        <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2.5 text-xs text-slate-400">
          <p className="font-medium text-slate-200">Capital playbook</p>
          <p className="mt-1">
            New buying {String(playbook.new_buying)} · Reserve {String(playbook.reserve_for_sip)} · Max holdings{' '}
            {String(playbook.max_holdings)}
          </p>
          <p className="mt-0.5">Exit: {String(playbook.exit)}</p>
          <p className="mt-0.5">SIP: {String(playbook.sip)}</p>
          <p className="mt-0.5">{String(playbook.compounding)}</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>
          All ({allResults.length})
        </Chip>
        <Chip selected={filter === 'actionable'} onClick={() => setFilter('actionable')}>
          BUY ({allResults.filter((r) => r.take_trade).length})
        </Chip>
        <Chip selected={filter === 'watch'} onClick={() => setFilter('watch')}>
          CAR watch ({allResults.filter((r) => String(r.signal ?? '') === 'WATCH').length})
        </Chip>
      </div>

      <div className="space-y-2">
        {filtered.length === 0 && <p className="text-sm text-slate-500">No tickers match this filter.</p>}
        {filtered.map((res, i) => (
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
    </div>
  )
}
