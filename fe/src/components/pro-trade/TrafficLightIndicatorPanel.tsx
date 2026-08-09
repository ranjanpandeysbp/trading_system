import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Chip } from '../ui/Chip'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { AskAIPanel } from '../ai/AskAIPanel'
import { VolumeProfileChart, type VpChartBar, type VpLevel, type VpSeries } from './VolumeProfileChart'

type Row = Record<string, unknown>

const FURTHER_ANALYSIS_LABELS: Record<string, string> = {
  mtf_trend_strength: 'Trend & Strength (MTF)',
}

function signalTone(signal: string): string {
  const s = signal.toUpperCase()
  if (s === 'BULLISH') return 'BUY'
  if (s === 'BEARISH') return 'SELL'
  return 'HOLD'
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
  const stack = (result.stack as Row | undefined) ?? {}
  const smas = (result.smas as Row | undefined) ?? {}
  const trendStrength = result.trend_strength as Row | null | undefined

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(() => {
    const fromApi = (result.chart_series as VpSeries[] | undefined) ?? []
    if (fromApi.length) return fromApi
    return [
      { key: 'sma_red', label: 'SMA200 (Red)', color: '#ef4444' },
      { key: 'sma_yellow', label: 'SMA50 (Yellow)', color: '#eab308' },
      { key: 'sma_green', label: 'SMA20 (Green)', color: '#22c55e' },
    ]
  }, [result.chart_series])
  const levels = useMemo<VpLevel[]>(() => {
    const out: VpLevel[] = []
    if (take) {
      if (result.entry_price != null) out.push({ label: 'Entry', price: Number(result.entry_price), color: '#38bdf8' })
      if (result.stop_price != null) out.push({ label: 'SL', price: Number(result.stop_price), color: '#f87171' })
      if (result.target_price != null) out.push({ label: 'TP', price: Number(result.target_price), color: '#34d399' })
    }
    return out
  }, [take, result.entry_price, result.stop_price, result.target_price])

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
          <SignalBadge signal={signal} />
          {take && <Badge action={signalTone(signal)} />}
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{fmtNum(result.confidence_pct, 0)}% confidence</span>
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
            {stack.label != null && (
              <span>
                Stack: <strong className="text-slate-300">{String(stack.label)}</strong>
              </span>
            )}
            {smas.red_200 != null && (
              <span>
                Red 200: <strong className="text-rose-300">{fmtNum(smas.red_200)}</strong>
              </span>
            )}
            {smas.yellow_50 != null && (
              <span>
                Yellow 50: <strong className="text-amber-300">{fmtNum(smas.yellow_50)}</strong>
              </span>
            )}
            {smas.green_20 != null && (
              <span>
                Green 20: <strong className="text-emerald-300">{fmtNum(smas.green_20)}</strong>
              </span>
            )}
            {Boolean(stack.price_below_all) && <span className="text-emerald-400">Close below all SMAs</span>}
            {Boolean(stack.price_above_all) && <span className="text-rose-400">Close above all SMAs</span>}
          </div>

          {result.large_cap_note != null && (
            <p className="text-xs text-amber-200/80">{String(result.large_cap_note)}</p>
          )}

          {take && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-xs text-slate-500">Entry (next morning)</p>
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
                  <p className="text-xs text-slate-500">Target</p>
                  <p className="font-medium text-emerald-400">
                    {result.tp_pct != null ? `+${fmtNum(result.tp_pct, 1)}%` : '—'} ({currency}
                    {fmtNum(result.target_price)})
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Direction</p>
                  <p className="font-medium text-white">{String(result.direction ?? '—')}</p>
                </div>
              </div>
            </div>
          )}

          {trendStrength && (
            <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 px-3 py-2 text-xs text-slate-400">
              <span className="font-medium text-indigo-300">Trend & Strength: </span>
              {String(trendStrength.summary ?? trendStrength.label ?? JSON.stringify(trendStrength)).slice(0, 280)}
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart
                chartData={chartData}
                levels={levels}
                series={series}
                readingGuide="Toggle Candles / Line above. Red = SMA200, Yellow = SMA50, Green = SMA20. BUY when Red>Yellow>Green and price closes under all three; SELL when Green>Yellow>Red and price closes above all three. Entry/SL/TP lines appear when a trade is suggested."
              />
            </div>
          )}

          {((result.further_analysis_applied as string[]) ?? []).length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">Further analysis:</span>
              {(result.further_analysis_applied as string[]).map((c) => (
                <span
                  key={c}
                  className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-300"
                >
                  {FURTHER_ANALYSIS_LABELS[c] ?? c}
                </span>
              ))}
            </div>
          )}

          {((result.reasons as string[]) ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-500">
              {(result.reasons as string[]).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            section={`pro-trade/traffic-light-indicator/${String(result.ticker ?? '')}`}
            systemPrompt={aiSystemPrompt}
          />
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable'

export function TrafficLightIndicatorPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = String(data.asset_class ?? 'india') as WatchlistMarket
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const [filter, setFilter] = useState<FilterMode>('all')
  const youtube = data.youtube != null ? String(data.youtube) : null

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
        {youtube && (
          <a
            href={youtube}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300"
          >
            Strategy video <ExternalLink size={12} />
          </a>
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
