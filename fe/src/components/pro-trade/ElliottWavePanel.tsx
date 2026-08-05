import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Chip } from '../ui/Chip'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { VolumeProfileChart, type VpChartBar, type VpLevel, type VpWaveSegment } from './VolumeProfileChart'

type Row = Record<string, unknown>

const PATTERN_COLORS: Record<string, string> = {
  IMPULSE: 'text-emerald-400',
  CORRECTIVE: 'text-amber-400',
  INCOMPLETE: 'text-slate-400',
  NONE: 'text-slate-500',
}

const WAVE_PALETTE = ['#38bdf8', '#a78bfa', '#f472b6', '#fb923c', '#facc15', '#4ade80', '#2dd4bf']

function signalTone(direction: string): string {
  const d = direction.toUpperCase()
  if (d === 'LONG') return 'BUY'
  if (d === 'SHORT') return 'SELL'
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

function fmtNum(v: unknown) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'
}

function TickerResultCard({
  result,
  currency,
  assetClass,
  showCharts,
}: {
  result: Row
  currency: string
  assetClass: WatchlistMarket
  showCharts: boolean
}) {
  const [open, setOpen] = useState(true)
  const take = Boolean(result.take_trade)
  const pattern = String(result.pattern ?? 'NONE')
  const waves = (result.waves as Row[]) ?? []
  const targets = (result.wave_targets as Record<string, number>) ?? {}

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )

  const waveSegments = useMemo<VpWaveSegment[]>(
    () =>
      waves.map((w, i) => ({
        label: String(w.wave_num ?? i + 1),
        startTime: String(w.start_time ?? ''),
        endTime: String(w.end_time ?? ''),
        startPrice: Number(w.start_price),
        endPrice: Number(w.end_price),
        color: WAVE_PALETTE[i % WAVE_PALETTE.length],
      })),
    [waves],
  )

  const chartLevels = useMemo<VpLevel[]>(() => {
    const out: VpLevel[] = []
    if (take) {
      if (result.entry_price != null) out.push({ label: 'Entry', price: Number(result.entry_price), color: '#38bdf8' })
      if (result.stop_price != null) out.push({ label: 'SL', price: Number(result.stop_price), color: '#f87171' })
      if (result.target_price != null) out.push({ label: 'TP', price: Number(result.target_price), color: '#34d399' })
    }
    Object.entries(targets).forEach(([label, price], i) => {
      out.push({ label, price: Number(price), color: i === 0 ? '#facc15' : '#94a3b8' })
    })
    return out
  }, [targets, take, result.entry_price, result.stop_price, result.target_price])

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
          <SignalBadge signal={String(result.signal ?? 'NEUTRAL')} />
          {take && <Badge action={signalTone(String(result.direction ?? ''))} />}
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{Number(result.confidence_pct).toFixed(0)}% confidence</span>
          )}
          <span className={`text-xs font-medium ${PATTERN_COLORS[pattern] ?? 'text-slate-400'}`}>{pattern}</span>
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
                    {result.sl_pct != null ? `-${Number(result.sl_pct).toFixed(1)}%` : '—'} ({currency}
                    {fmtNum(result.stop_price)})
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Target</p>
                  <p className="font-medium text-emerald-400">
                    {result.tp_pct != null ? `+${Number(result.tp_pct).toFixed(1)}%` : '—'} ({currency}
                    {fmtNum(result.target_price)})
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Reward : Risk</p>
                  <p className="font-medium text-white">{result.rr != null ? `1 : ${Number(result.rr).toFixed(2)}` : '—'}</p>
                </div>
              </div>
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart chartData={chartData} levels={chartLevels} waves={waveSegments} histogram={[]} />
            </div>
          )}

          {waves.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Wave legs</p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-xs text-slate-400">
                  <thead>
                    <tr className="text-left text-slate-500">
                      <th className="py-1 pr-3">Wave</th>
                      <th className="py-1 pr-3">Direction</th>
                      <th className="py-1 pr-3">Start</th>
                      <th className="py-1 pr-3">End</th>
                      <th className="py-1 pr-3">Move %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {waves.map((w, i) => {
                      const sp = Number(w.start_price)
                      const ep = Number(w.end_price)
                      const movePct = sp ? ((ep - sp) / sp) * 100 : null
                      return (
                        <tr key={i} className="border-t border-slate-800/60">
                          <td className="py-1 pr-3 font-medium text-slate-200">{String(w.wave_num)}</td>
                          <td className="py-1 pr-3">{String(w.direction)}</td>
                          <td className="py-1 pr-3">
                            {currency}
                            {fmtNum(sp)}
                          </td>
                          <td className="py-1 pr-3">
                            {currency}
                            {fmtNum(ep)}
                          </td>
                          <td className={`py-1 pr-3 ${movePct != null && movePct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {movePct != null ? `${movePct >= 0 ? '+' : ''}${movePct.toFixed(2)}%` : '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable'

export function ElliottWavePanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = (String(data.asset_class ?? 'india') as WatchlistMarket)
  const [filter, setFilter] = useState<FilterMode>('all')

  const sorted = useMemo(() => {
    const filtered = filter === 'actionable' ? allResults.filter((r) => Boolean(r.take_trade)) : allResults
    return [...filtered].sort((a, b) => {
      const at = a.take_trade ? 1 : 0
      const bt = b.take_trade ? 1 : 0
      if (at !== bt) return bt - at
      const ap = a.pattern === 'IMPULSE' || a.pattern === 'CORRECTIVE' ? 1 : 0
      const bp = b.pattern === 'IMPULSE' || b.pattern === 'CORRECTIVE' ? 1 : 0
      return bp - ap
    })
  }, [allResults, filter])

  if (!allResults.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2.5 text-xs leading-relaxed text-slate-300">
        <strong className="text-sky-300">How to read this, in plain terms:</strong> numbers <strong>1→5</strong> mark a
        trending move ("impulse"); letters <strong>A→B→C</strong> mark a pullback against that trend ("correction").
        The colored lines on each chart connect the swings in order — follow the numbers/letters to see the count.
        Dashed lines are projected price targets. <strong className="text-emerald-400">IMPULSE</strong> = a clean
        5-wave trend just finished, expect a pullback next. <strong className="text-amber-400">CORRECTIVE</strong> = an
        ABC pullback just finished, expect the original trend to resume. <strong className="text-slate-400">INCOMPLETE</strong>{' '}
        = the swings don't form a clean pattern yet — nothing to act on, just watch.
        <br />
        <br />
        Every card also shows a <strong className="text-sky-300">SIGNAL</strong> —{' '}
        <strong className="text-emerald-400">BULLISH</strong> (go long),{' '}
        <strong className="text-rose-400">BEARISH</strong> (go short), or{' '}
        <strong className="text-slate-400">NEUTRAL</strong> (no trade yet) — only produced once a pattern is fully
        complete. A signal always comes with a <strong>confidence %</strong> (how strong the setup is), plus a{' '}
        <strong>stop-loss %</strong> and <strong>target %</strong> so you know exactly how much you'd be risking vs.
        aiming to make.
      </div>

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
        <div className="ml-auto flex gap-2">
          <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>
            All ({allResults.length})
          </Chip>
          <Chip selected={filter === 'actionable'} onClick={() => setFilter('actionable')}>
            Actionable ({allResults.filter((r) => r.take_trade).length})
          </Chip>
        </div>
      </div>

      <div className="space-y-2">
        {sorted.length === 0 && <p className="text-sm text-slate-500">No tickers match this filter.</p>}
        {sorted.map((res, i) => (
          <TickerResultCard key={String(res.ticker ?? i)} result={res} currency={currency} assetClass={assetClass} showCharts={showCharts} />
        ))}
      </div>
      {Boolean(data.disclaimer) && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
