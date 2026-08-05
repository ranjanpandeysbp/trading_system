import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Chip } from '../ui/Chip'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { SupportResistanceChart, type SRChartBar, type SRLevel } from '../trading-hubs/SupportResistanceChart'

type Row = Record<string, unknown>

const EXTRA_CHECK_LABELS: Record<string, string> = {
  fibonacci: 'Fibonacci',
  ema_position: 'EMA position',
  ema_crossover: 'EMA crossover',
  stochastic_rsi: 'Stochastic RSI',
  vwap: 'VWAP',
  volume_profile: 'Volume Profile',
  smart_money: 'Smart Money',
  reversal_strategy: 'Reversal strategy',
  macd: 'MACD',
  support_resistance: 'Support & Resistance',
  trend_direction_strength: 'Trend direction & strength',
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
}: {
  result: Row
  index: number
  currency: string
  assetClass: WatchlistMarket
  showCharts: boolean
}) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade))
  const take = Boolean(result.take_trade)
  const signal = String(result.signal ?? 'NEUTRAL')

  const chartData = useMemo(
    () => ((result.chart_data as SRChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const emas = useMemo(() => {
    const out: Record<string, Array<{ time: string; value: number }>> = {}
    if (((result.bb_upper as Row[]) ?? []).length) out['BB Upper'] = result.bb_upper as Array<{ time: string; value: number }>
    if (((result.bb_mid as Row[]) ?? []).length) out['BB Mean'] = result.bb_mid as Array<{ time: string; value: number }>
    if (((result.bb_lower as Row[]) ?? []).length) out['BB Lower'] = result.bb_lower as Array<{ time: string; value: number }>
    return out
  }, [result.bb_upper, result.bb_mid, result.bb_lower])
  const levels = useMemo<SRLevel[]>(() => {
    const out: SRLevel[] = []
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
                  ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100'
                  : 'border-slate-700/60 bg-slate-950/50 text-slate-300'
              }`}
            >
              {String(result.plain_english)}
            </div>
          )}

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {result.percent_b != null && <span>%B: <strong className="text-slate-300">{fmtNum(result.percent_b, 2)}</strong></span>}
            {result.rsi != null && <span>RSI: <strong className="text-slate-300">{fmtNum(result.rsi, 0)}</strong></span>}
            {result.efficiency_ratio != null && <span>Efficiency Ratio: <strong className="text-slate-300">{fmtNum(result.efficiency_ratio, 2)}</strong></span>}
            {result.volume_zscore != null && <span>Volume z: <strong className="text-slate-300">{fmtNum(result.volume_zscore, 1)}σ</strong></span>}
            {result.is_squeeze != null && Boolean(result.is_squeeze) && <span className="text-amber-400">Band squeeze</span>}
            {result.matched_pattern != null && <span>Pattern: <strong className="text-slate-300">{String(result.matched_pattern)}</strong></span>}
            {result.zone_confluence != null && Boolean(result.zone_confluence) && <span className="text-emerald-400">S/R confluence</span>}
          </div>

          {take && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-xs text-slate-500">Entry</p>
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
                  <p className="text-xs text-slate-500">Target (mean)</p>
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
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <SupportResistanceChart
                chartData={chartData}
                supportZone={(result.support_zone as [number, number] | null | undefined) ?? null}
                resistanceZone={(result.resistance_zone as [number, number] | null | undefined) ?? null}
                trendlines={[]}
                lastClose={result.ltp as number | undefined}
                emas={emas}
                levels={levels}
                readingGuide="Candles show price with the three Bollinger Band lines overlaid — Upper/Lower are the 20-bar, 2σ range, the middle line is the mean this strategy targets on a reversion. Price piercing the outer bands is 'stretched'; a move back toward the middle line is the expected reversion. The green/red Support/Resistance band marks an independent swing-based zone — a band touch that also lines up with this zone is stronger confluence. Entry/SL/TP lines (if shown) mark the suggested trade."
              />
            </div>
          )}

          {((result.extra_checks_applied as string[]) ?? []).length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">Extra checks applied:</span>
              {(result.extra_checks_applied as string[]).map((c) => (
                <span key={c} className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] text-indigo-300">
                  {EXTRA_CHECK_LABELS[c] ?? c}
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
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable'

export function BbMeanReversionPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = String(data.asset_class ?? 'india') as WatchlistMarket
  const [filter, setFilter] = useState<FilterMode>('all')
  const [tfFilter, setTfFilter] = useState<string>('all')

  const timeframes = useMemo(
    () => Array.from(new Set(allResults.map((r) => String(r.timeframe ?? '')).filter(Boolean))),
    [allResults],
  )

  const filtered = useMemo(() => {
    let out = allResults
    if (filter === 'actionable') out = out.filter((r) => Boolean(r.take_trade))
    if (tfFilter !== 'all') out = out.filter((r) => String(r.timeframe ?? '') === tfFilter)
    return out
  }, [allResults, filter, tfFilter])

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
        {timeframes.length > 1 && (
          <>
            <span className="mx-1 text-slate-700">|</span>
            <Chip selected={tfFilter === 'all'} onClick={() => setTfFilter('all')}>
              All timeframes
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
          />
        ))}
      </div>
      {data.disclaimer != null && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
