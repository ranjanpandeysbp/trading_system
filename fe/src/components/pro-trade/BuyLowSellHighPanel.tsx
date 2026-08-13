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

function StatusBadge({ status }: { status: string }) {
  const s = status.toUpperCase()
  const sell = s.includes('SELL')
  const buy = s.includes('BUY') || s.includes('ADD') || s.includes('ARM') || s.includes('TRIGGER')
  const cls = sell
    ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
    : buy
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : 'border-slate-700/60 bg-slate-800/40 text-slate-400'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function SignalBadge({ signal }: { signal: string }) {
  const s = signal.toUpperCase()
  const cls =
    s === 'BULLISH'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : s === 'BEARISH'
        ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
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
  const levels = (result.levels as Row | undefined) ?? {}
  const suggestion = (result.trade_suggestion as Row | undefined) ?? {}

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(() => {
    const fromApi = (result.chart_series as VpSeries[] | undefined) ?? []
    if (fromApi.length) return fromApi
    return [
      { key: 'low_25', label: '25 DL', color: '#94a3b8' },
      { key: 'buy_gtt', label: 'Buy GTT (+5%)', color: '#22c55e' },
    ]
  }, [result.chart_series])
  const chartLevels = useMemo<VpLevel[]>(() => {
    const fromApi = (result.chart_levels as VpLevel[] | undefined) ?? []
    if (fromApi.length) return fromApi
    const out: VpLevel[] = []
    if (levels.low_25 != null) out.push({ label: '25 DL', price: Number(levels.low_25), color: '#94a3b8' })
    if (levels.buy_gtt != null) out.push({ label: 'Buy GTT', price: Number(levels.buy_gtt), color: '#22c55e' })
    if (levels.sell_target != null) out.push({ label: 'Sell +5% avg', price: Number(levels.sell_target), color: '#f59e0b' })
    if (levels.avg_cost != null) out.push({ label: 'Avg cost', price: Number(levels.avg_cost), color: '#38bdf8' })
    return out
  }, [result.chart_levels, levels])

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
            </span>
          )}
          {result.status != null && <StatusBadge status={String(result.status)} />}
          <SignalBadge signal={String(result.signal ?? 'WAIT')} />
          {take && <Badge action={String(suggestion.action ?? 'BUY') === 'SELL' ? 'SELL' : 'BUY'} />}
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

          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500">25-day low</p>
              <p className="font-medium text-slate-200">{currency}{fmtNum(levels.low_25)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Buy GTT (+5%)</p>
              <p className="font-medium text-emerald-300">{currency}{fmtNum(levels.buy_gtt)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Avg cost (sim)</p>
              <p className="font-medium text-sky-300">
                {levels.avg_cost != null ? `${currency}${fmtNum(levels.avg_cost)}` : '— flat'}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Sell all (avg+5%)</p>
              <p className="font-medium text-amber-300">
                {levels.sell_target != null ? `${currency}${fmtNum(levels.sell_target)}` : '—'}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {levels.dist_to_gtt_pct != null && (
              <span>
                Dist to GTT:{' '}
                <strong className="text-slate-300">{fmtNum(levels.dist_to_gtt_pct, 2)}%</strong>
              </span>
            )}
            {levels.add_arm_level != null && (
              <span>
                Add-arm (−10% avg): <strong className="text-slate-300">{currency}{fmtNum(levels.add_arm_level)}</strong>
              </span>
            )}
            <span className="text-slate-400">No stop-loss by design</span>
            {suggestion.action_label != null && (
              <span>
                Action: <strong className="text-slate-200">{String(suggestion.action_label)}</strong>
              </span>
            )}
          </div>

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart
                chartData={chartData}
                ticker={String(result.ticker ?? '')}
                assetClass={assetClass}
                levels={chartLevels}
                series={series}
                readingGuide="Grey = 25-day low. Green = buy GTT (25 DL + 5%). Amber = sell-all at average + 5% when in a simulated position. Update the GTT whenever a new 25 DL prints before fill. No stop-loss — exit is the +5% average target."
              />
            </div>
          )}

          {((result.reasons as string[]) ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-500">
              {(result.reasons as string[]).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}

          {((result.recent_events as Row[]) ?? []).length > 0 && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Recent simulated GTT events</p>
              <ul className="space-y-0.5 text-xs text-slate-500">
                {(result.recent_events as Row[]).slice(-6).map((ev, i) => (
                  <li key={i}>
                    <span className="text-slate-400">{String(ev.time)}</span>
                    {' · '}
                    <span className="text-slate-300">{String(ev.type)}</span>
                    {ev.price != null && <> @ {currency}{fmtNum(ev.price)}</>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/buy-low-sell-high/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable'

export function BuyLowSellHighPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = String(data.asset_class ?? 'india') as WatchlistMarket
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const [filter, setFilter] = useState<FilterMode>('all')

  const filtered = useMemo(() => {
    if (filter === 'actionable') return allResults.filter((r) => Boolean(r.take_trade))
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
    </div>
  )
}
