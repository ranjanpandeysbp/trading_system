import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
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
  const setupName = String(setup.setup ?? 'setup')
  const label =
    setupName === 'fvg_volume_profile'
      ? 'FVG + Volume Profile'
      : setupName === 'sr_flip_volume_profile'
        ? 'S/R Flip + Volume Profile'
        : setupName

  const reasons = (setup.reasons as string[]) ?? []
  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-200">{label}</span>
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
        {setup.level_time != null && <span>Time: {String(setup.level_time)}</span>}
        {setup.fvg_time != null && <span>FVG: {String(setup.fvg_time)}</span>}
        {setup.poc != null && <span>POC: {String(setup.poc)}</span>}
        {setup.stop_loss != null && <span>SL: {String(setup.stop_loss)}</span>}
        {setup.target_1 != null && <span>TP: {String(setup.target_1)}</span>}
        {setup.zone_low != null && setup.zone_high != null && (
          <span>
            VP zone: {String(setup.zone_low)}–{String(setup.zone_high)}
          </span>
        )}
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

function levelsFromResult(levels: Row, setups: Row[]): VpLevel[] {
  const out: VpLevel[] = []
  if (levels.zone_low != null) out.push({ label: 'Zone Lo', price: Number(levels.zone_low), color: '#34d399' })
  if (levels.poc != null) out.push({ label: 'POC', price: Number(levels.poc), color: '#f43f5e' })
  if (levels.zone_high != null) out.push({ label: 'Zone Hi', price: Number(levels.zone_high), color: '#fbbf24' })

  const actionable = setups.filter((s) => ['BUY', 'SELL'].includes(String(s.signal ?? '').toUpperCase()))
  for (const s of actionable.slice(0, 3)) {
    if (s.entry != null) {
      const dir = String(s.direction ?? '')
      out.push({
        label: dir === 'LONG' ? 'Entry↑' : dir === 'SHORT' ? 'Entry↓' : 'Entry',
        price: Number(s.entry),
        color: dir === 'LONG' ? '#38bdf8' : '#fb7185',
      })
    }
    if (s.stop_loss != null) out.push({ label: 'SL', price: Number(s.stop_loss), color: '#94a3b8' })
    if (s.target_1 != null) out.push({ label: 'TP', price: Number(s.target_1), color: '#a78bfa' })
  }
  return out
}

function TickerResultCard({ result, index, currency }: { result: Row; index: number; currency: string }) {
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
  const chartLevels = useMemo(() => levelsFromResult(levels, setups), [levels, setups])

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
        <span className="font-semibold text-white">{String(result.ticker)}</span>
        {result.ltp != null && (
          <span className="text-sm text-slate-400">
            {currency}
            {String(result.ltp)}
          </span>
        )}
        <Badge action={take ? 'BUY' : 'HOLD'} />
        <span className="text-xs text-slate-500">{String(result.verdict ?? 'WAIT')}</span>
        {result.error ? <span className="text-xs text-amber-400">{String(result.error)}</span> : null}
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          {levels.poc != null && (
            <div className="flex flex-wrap gap-3 text-xs text-slate-400">
              <span>
                POC <strong className="text-rose-300">{String(levels.poc)}</strong>
              </span>
              <span>
                Zone <strong className="text-slate-200">{String(levels.zone_low)}</strong>–
                <strong className="text-slate-200">{String(levels.zone_high)}</strong>
              </span>
            </div>
          )}

          {chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart chartData={chartData} levels={chartLevels} histogram={histogram} />
            </div>
          )}

          <div className="space-y-2">
            {setups.length === 0 && !result.error && (
              <p className="text-xs text-slate-500">No FVG or S/R flip setups with VP confluence in lookback.</p>
            )}
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

export function PaVolumeProfilePanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
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
          <TickerResultCard key={String(res.ticker ?? i)} result={res} index={i} currency={currency} />
        ))}
      </div>
      {Boolean(data.disclaimer) && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
