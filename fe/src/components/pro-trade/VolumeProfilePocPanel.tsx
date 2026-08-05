import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { VolumeProfileChart, type VpChartBar, type VpHistBin, type VpLevel } from './VolumeProfileChart'

type Row = Record<string, unknown>

function signalTone(signal: string): string {
  const s = signal.toUpperCase()
  if (s.includes('BUY') || s.includes('LONG')) return 'BUY'
  if (s.includes('SELL') || s.includes('SHORT')) return 'SELL'
  return 'HOLD'
}

function SetupCard({ setup }: { setup: Row }) {
  const signal = String(setup.signal ?? 'WAIT')
  const reasons = (setup.reasons as string[]) ?? []
  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-200">{String(setup.setup ?? 'setup')}</span>
        <Badge action={signalTone(signal)} />
        <span className="text-xs text-slate-500">{signal}</span>
        {setup.direction ? <span className="text-xs text-slate-400">{String(setup.direction)}</span> : null}
        {setup.confidence_pct != null && (
          <span className="text-xs font-medium text-emerald-300">{String(setup.confidence_pct)}% confidence</span>
        )}
      </div>
      <p className="text-xs leading-relaxed text-slate-400">{String(setup.logic ?? '')}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        {setup.entry != null && <span>Entry: {String(setup.entry)}</span>}
        {setup.entry_time != null && <span>Time: {String(setup.entry_time)}</span>}
        {setup.stop_loss != null && <span>SL (LVN): {String(setup.stop_loss)}</span>}
        {setup.target_1 != null && <span>TP (before next HVN): {String(setup.target_1)}</span>}
        {setup.bars_since_touch != null && <span>Touch: {String(setup.bars_since_touch)} bar(s) ago</span>}
      </div>
      {(setup.sl_pct != null || setup.tp_pct != null || setup.hold_duration != null) && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-800/60 pt-2 text-xs">
          {setup.sl_pct != null && <span className="text-rose-400">SL: -{String(setup.sl_pct)}%</span>}
          {setup.tp_pct != null && <span className="text-emerald-400">TP: +{String(setup.tp_pct)}%</span>}
          {setup.hold_duration != null && <span className="text-slate-400">Hold: {String(setup.hold_duration)}</span>}
        </div>
      )}
      {reasons.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {reasons.map((r, i) => (
            <p key={i} className="text-[11px] text-slate-500">
              · {r}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function levelsFromResult(levels: Row, result: Row): VpLevel[] {
  const out: VpLevel[] = []
  if (levels.zone_lower != null) out.push({ label: 'Zone Lo', price: Number(levels.zone_lower), color: '#34d399' })
  if (levels.poc != null) out.push({ label: 'POC', price: Number(levels.poc), color: '#f43f5e' })
  if (levels.zone_upper != null) out.push({ label: 'Zone Hi', price: Number(levels.zone_upper), color: '#fbbf24' })
  if (levels.stop_loss_lvn_long != null) {
    out.push({ label: 'LVN SL↑', price: Number(levels.stop_loss_lvn_long), color: '#94a3b8' })
  }
  if (levels.target_long != null) out.push({ label: 'TP↑', price: Number(levels.target_long), color: '#38bdf8' })
  const supportZone = result.support_zone as [number, number] | null | undefined
  const resistanceZone = result.resistance_zone as [number, number] | null | undefined
  if (supportZone) out.push({ label: 'Support', price: Number(supportZone[1]), color: '#22c55e' })
  if (resistanceZone) out.push({ label: 'Resistance', price: Number(resistanceZone[0]), color: '#ef4444' })
  return out
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
  const setups = (result.setups as Row[]) ?? []
  const levels = (result.levels as Row) || {}
  const take = Boolean(result.take_trade)
  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const histogram = useMemo(
    () => ((result.vp_histogram as VpHistBin[]) ?? []).filter((b) => b && b.price != null),
    [result.vp_histogram],
  )
  const chartLevels = useMemo(() => levelsFromResult(levels, result), [levels, result])

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 items-center gap-3 text-left"
        >
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {String(result.ltp)}
            </span>
          )}
          <Badge action={take ? signalTone(String(result.direction ?? '')) : 'HOLD'} />
          <span className="text-xs text-slate-500">{String(result.verdict ?? 'WAIT')}</span>
          {result.error ? <span className="text-xs text-amber-400">{String(result.error)}</span> : null}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker ?? '')} marketType={assetClass} compact />
      </div>
      {open && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          {levels.poc != null && (
            <div className="flex flex-wrap gap-3 text-xs text-slate-400">
              <span>
                POC <strong className="text-rose-300">{String(levels.poc)}</strong>
              </span>
              <span>
                Zone <strong className="text-slate-200">{String(levels.zone_lower)}</strong>–
                <strong className="text-slate-200">{String(levels.zone_upper)}</strong>
              </span>
              {levels.stop_loss_lvn_long != null && (
                <span>
                  LVN SL (long) <strong className="text-slate-200">{String(levels.stop_loss_lvn_long)}</strong>
                </span>
              )}
              {levels.target_long != null && (
                <span>
                  TP↑ <strong className="text-slate-200">{String(levels.target_long)}</strong>
                </span>
              )}
            </div>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart chartData={chartData} levels={chartLevels} histogram={histogram} />
            </div>
          )}

          <div className="space-y-2">
            {setups.map((s, i) => (
              <SetupCard key={`${String(s.setup)}-${i}`} setup={s} />
            ))}
          </div>

          {((result.rules as string[]) ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-500">
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

export function VolumeProfilePocPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = (String(data.asset_class ?? 'india') as WatchlistMarket)
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm text-slate-400">
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
        {data.youtube != null && (
          <a href={String(data.youtube)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
            Source video
          </a>
        )}
      </div>
      <div className="space-y-2">
        {results.map((res, i) => (
          <TickerResultCard key={String(res.ticker ?? i)} result={res} index={i} currency={currency} assetClass={assetClass} showCharts={showCharts} />
        ))}
      </div>
      {Boolean(data.disclaimer) && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
