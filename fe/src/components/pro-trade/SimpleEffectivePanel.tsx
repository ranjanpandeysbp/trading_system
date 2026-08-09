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
  const action = String((result.trade_suggestion as Row | undefined)?.action ?? 'WAIT')

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(() => {
    const fromApi = (result.chart_series as VpSeries[] | undefined) ?? []
    return fromApi.length
      ? fromApi
      : [
          { key: 'ma_fast', label: 'MA fast', color: '#38bdf8' },
          { key: 'ma_slow', label: 'MA slow', color: '#fb923c' },
        ]
  }, [result.chart_series])
  const levels = useMemo<VpLevel[]>(() => {
    return ((result.chart_levels as VpLevel[] | undefined) ?? []).filter((l) => l && l.price != null)
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
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.timeframe != null && (
            <span className="rounded-md border border-slate-700/60 bg-slate-800/50 px-1.5 py-0.5 text-[11px] text-slate-400">
              {String(result.timeframe)}
            </span>
          )}
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {String(result.ltp)}
            </span>
          )}
          <SignalBadge signal={String(result.signal ?? 'WAIT')} />
          {take && <Badge action={action === 'SELL' ? 'SELL' : 'BUY'} />}
          {metrics.hist_zone != null && (
            <span className="text-xs text-slate-400">MACD hist: {String(metrics.hist_zone)}</span>
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
            {metrics.band_lo != null && metrics.band_hi != null && (
              <span>
                Band: <strong className="text-slate-300">{fmtNum(metrics.band_lo)}–{fmtNum(metrics.band_hi)}</strong>
              </span>
            )}
            {metrics.macd_hist != null && (
              <span>
                Hist: <strong className="text-slate-300">{fmtNum(metrics.macd_hist, 4)}</strong>
              </span>
            )}
            {metrics.rr_multiple != null && (
              <span>
                RRR: <strong className="text-slate-300">1:{fmtNum(metrics.rr_multiple, 1)}</strong>
              </span>
            )}
            {metrics.signal_time != null && (
              <span>
                Signal: <strong className="text-slate-300">{String(metrics.signal_time)}</strong>
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

          {(take || String(result.signal) === 'WATCH') && (
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div>
                <p className="text-xs text-slate-500">Entry / trigger</p>
                <p className="font-medium text-white">{currency}{fmtNum(result.entry_price)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Stop (opp. band)</p>
                <p className="font-medium text-rose-400">
                  {result.sl_pct != null ? `${fmtNum(result.sl_pct, 1)}%` : '—'} ({currency}
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
                levels={levels}
                series={series}
                readingGuide="Blue/orange = MA band. Signal needs a full close outside the band plus MACD crossover inside the matching histogram (green for Buy, red for Sell). Enter only after the signal High/Low breaks. SL sits on the opposite band edge; book at 1:1–1.5 RRR."
              />
            </div>
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/simple-effective/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable' | 'setup'

export function SimpleEffectivePanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = String(data.asset_class ?? 'india') as WatchlistMarket
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const [filter, setFilter] = useState<FilterMode>('all')
  const [tfFilter, setTfFilter] = useState('all')

  const timeframes = useMemo(
    () => Array.from(new Set(allResults.map((r) => String(r.timeframe ?? '')).filter(Boolean))),
    [allResults],
  )

  const filtered = useMemo(() => {
    let out = allResults
    if (filter === 'actionable') out = out.filter((r) => Boolean(r.take_trade))
    if (filter === 'setup') out = out.filter((r) => String(r.signal ?? '') === 'WATCH' || Boolean(r.take_trade))
    if (tfFilter !== 'all') out = out.filter((r) => String(r.timeframe ?? '') === tfFilter)
    return out
  }, [allResults, filter, tfFilter])

  const sorted = useMemo(
    () =>
      [...filtered].sort((a, b) => {
        const at = a.take_trade ? 2 : String(a.signal) === 'WATCH' ? 1 : 0
        const bt = b.take_trade ? 2 : String(b.signal) === 'WATCH' ? 1 : 0
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
            Triggered: <strong className="text-white">{String(data.entry_count)}</strong>
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
          Triggered ({allResults.filter((r) => r.take_trade).length})
        </Chip>
        <Chip selected={filter === 'setup'} onClick={() => setFilter('setup')}>
          Setups ({allResults.filter((r) => r.take_trade || String(r.signal) === 'WATCH').length})
        </Chip>
        {timeframes.length > 1 && (
          <>
            <span className="mx-1 text-slate-700">|</span>
            <Chip selected={tfFilter === 'all'} onClick={() => setTfFilter('all')}>
              All TFs
            </Chip>
            {timeframes.map((tf) => (
              <Chip key={tf} selected={tfFilter === tf} onClick={() => setTfFilter(tf)}>
                {tf}
              </Chip>
            ))}
          </>
        )}
      </div>

      <div className="space-y-2">
        {sorted.length === 0 && <p className="text-sm text-slate-500">No tickers match this filter.</p>}
        {sorted.map((res, i) => (
          <TickerResultCard
            key={`${String(res.ticker ?? i)}-${String(res.timeframe ?? '')}`}
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
