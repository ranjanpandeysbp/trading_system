import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
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
          { key: 'ema20', label: 'EMA20', color: '#38bdf8' },
          { key: 'ema50', label: 'EMA50', color: '#fb923c' },
        ]
  }, [result.chart_series])
  const levels = useMemo<VpLevel[]>(() => {
    const fromApi = (result.chart_levels as VpLevel[] | undefined) ?? []
    if (fromApi.length) return fromApi
    const out: VpLevel[] = []
    if (metrics.prev_high != null) out.push({ label: 'Prior high', price: Number(metrics.prev_high), color: '#a78bfa' })
    if (metrics.ema20 != null) out.push({ label: 'EMA20', price: Number(metrics.ema20), color: '#38bdf8' })
    if (metrics.ema50 != null) out.push({ label: 'EMA50', price: Number(metrics.ema50), color: '#fb923c' })
    if (take && result.stop_price != null) out.push({ label: 'SL', price: Number(result.stop_price), color: '#f87171' })
    if (take && result.target_price != null) out.push({ label: 'TP', price: Number(result.target_price), color: '#34d399' })
    return out
  }, [result.chart_levels, metrics, take, result.stop_price, result.target_price])

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
          <SignalBadge signal={String(result.signal ?? 'WAIT')} />
          {take && <Badge action="BUY" />}
          <span className="text-xs text-slate-400">
            {String(result.passed_count ?? 0)}/{String(result.checks_total ?? 7)}
          </span>
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
            {metrics.rsi != null && (
              <span>
                RSI: <strong className="text-slate-300">{fmtNum(metrics.rsi, 1)}</strong>
              </span>
            )}
            {metrics.day_chg_pct != null && (
              <span>
                Day:{' '}
                <strong className={Number(metrics.day_chg_pct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {fmtNum(metrics.day_chg_pct, 2)}%
                </strong>
              </span>
            )}
            {metrics.prev_high != null && (
              <span>
                Prior high: <strong className="text-slate-300">{currency}{fmtNum(metrics.prev_high)}</strong>
              </span>
            )}
            {metrics.ema20 != null && (
              <span>
                EMA20: <strong className="text-slate-300">{fmtNum(metrics.ema20)}</strong>
              </span>
            )}
            {metrics.ema50 != null && (
              <span>
                EMA50: <strong className="text-slate-300">{fmtNum(metrics.ema50)}</strong>
              </span>
            )}
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
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div>
                <p className="text-xs text-slate-500">Entry</p>
                <p className="font-medium text-white">{currency}{fmtNum(result.entry_price)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Stop</p>
                <p className="font-medium text-rose-400">
                  {result.sl_pct != null ? `-${fmtNum(result.sl_pct, 1)}%` : '—'} ({currency}
                  {fmtNum(result.stop_price)})
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Target</p>
                <p className="font-medium text-emerald-400">
                  {result.tp_pct != null ? `+${fmtNum(result.tp_pct, 1)}%` : '—'} ({currency}
                  {fmtNum(result.target_price)})
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Status</p>
                <p className="font-medium text-slate-200">{String(result.status ?? '—').replace(/_/g, ' ')}</p>
              </div>
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart
                chartData={chartData}
                ticker={String(result.ticker ?? '')}
                assetClass={assetClass}
                levels={levels}
                series={series}
                readingGuide="RLB wants a green breakout day through the prior high, above EMA20 and EMA50, with RSI strength, >2% daily gain, and volume above the 5-day average. Blue = EMA20, orange = EMA50, purple = prior high."
              />
            </div>
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/rlb-breakout/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable' | 'near'

export function RlbBreakoutPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = String(data.asset_class ?? 'india') as WatchlistMarket
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const youtube = data.youtube != null ? String(data.youtube) : null
  const [filter, setFilter] = useState<FilterMode>('all')

  const filtered = useMemo(() => {
    if (filter === 'actionable') return allResults.filter((r) => Boolean(r.take_trade))
    if (filter === 'near') return allResults.filter((r) => Number(r.passed_count ?? 0) >= 5)
    return allResults
  }, [allResults, filter])

  const sorted = useMemo(
    () =>
      [...filtered].sort((a, b) => {
        const at = a.take_trade ? 1 : 0
        const bt = b.take_trade ? 1 : 0
        if (at !== bt) return bt - at
        const pc = Number(b.passed_count ?? 0) - Number(a.passed_count ?? 0)
        if (pc !== 0) return pc
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
            RLB pass: <strong className="text-white">{String(data.entry_count)}</strong>
          </span>
        )}
        {data.scanned != null && (
          <span>
            Scanned: <strong className="text-white">{String(data.scanned)}</strong>
          </span>
        )}
        {youtube && (
          <a href={youtube} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300">
            Strategy video <ExternalLink size={12} />
          </a>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>
          All ({allResults.length})
        </Chip>
        <Chip selected={filter === 'actionable'} onClick={() => setFilter('actionable')}>
          RLB pass ({allResults.filter((r) => r.take_trade).length})
        </Chip>
        <Chip selected={filter === 'near'} onClick={() => setFilter('near')}>
          Near-miss ≥5/7 ({allResults.filter((r) => Number(r.passed_count ?? 0) >= 5).length})
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
