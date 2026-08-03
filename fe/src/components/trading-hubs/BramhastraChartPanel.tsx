import { useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { apiErrorMessage, fetchBramhastraChart } from '../../api/client'
import { SupportResistanceChart } from './SupportResistanceChart'
import { Button } from '../ui/Button'
import { Alert, Loading } from '../ui/Feedback'

const PHASE_LABEL: Record<string, string> = {
  BUILDING_RANGE: 'Building 1H range',
  NO_RANGE_DATA: 'Insufficient data',
  MONSTER_CANDLE_SKIP: 'Monster candle — session skipped',
  NO_BREAK_YET: 'Range marked, no break yet',
  CONFIRMED_LONG: 'Breakout confirmed — watching for trigger (LONG)',
  CONFIRMED_SHORT: 'Breakout confirmed — watching for trigger (SHORT)',
  TRIGGERED_LONG: 'Triggered — TAKE LONG',
  TRIGGERED_SHORT: 'Triggered — TAKE SHORT',
}

function phaseBadgeClass(phase: string): string {
  if (phase.startsWith('TRIGGERED')) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (phase.startsWith('CONFIRMED')) return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  if (phase === 'MONSTER_CANDLE_SKIP') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  return 'border-slate-700/60 bg-slate-800/50 text-slate-300'
}

export function BramhastraChartPanel({
  ticker, assetClass, config,
}: {
  ticker: string
  assetClass: string
  config?: Record<string, unknown>
}) {
  const mut = useMutation({
    mutationFn: () => fetchBramhastraChart({ ticker, asset_class: assetClass, config }),
  })

  useEffect(() => {
    mut.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, assetClass])

  const data = mut.data

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-slate-500">1H range + 5m two-stage breakout chart</p>
        <Button size="sm" variant="ghost" onClick={() => mut.mutate()} disabled={mut.isPending}>
          {mut.isPending ? 'Loading…' : 'Refresh'}
        </Button>
      </div>

      {mut.isPending && <Loading message="Loading chart…" />}
      {mut.isError && <Alert type="error">{apiErrorMessage(mut.error)}</Alert>}

      {data && !mut.isPending && (
        <>
          <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center rounded-lg border px-2.5 py-1 text-xs font-medium ${phaseBadgeClass(data.phase)}`}>
                  {PHASE_LABEL[data.phase] ?? data.phase}
                </span>
                <span className="text-xs text-slate-500">
                  {data.session_date}{data.is_today ? ' (today)' : ' (most recent complete session)'}
                </span>
              </div>
              <span className="text-[11px] text-slate-500">
                1H {data.observation_start}–{data.observation_end} · 5m to {data.session_close} {data.tz}
              </span>
            </div>
            {data.range_pct != null && (
              <p className="mt-1.5 text-xs text-slate-400">
                1H range is {data.range_pct}% of price
                {data.support_zone && data.resistance_zone
                  ? ` (Low ${data.support_zone[0].toLocaleString('en-IN', { maximumFractionDigits: 2 })} / High ${data.resistance_zone[0].toLocaleString('en-IN', { maximumFractionDigits: 2 })})`
                  : ''}
              </p>
            )}
          </div>

          <SupportResistanceChart
            chartData={data.chart_data}
            supportZone={data.support_zone}
            resistanceZone={data.resistance_zone}
            trendlines={[]}
            lastClose={data.last_close}
            levels={data.levels}
          />
        </>
      )}
    </div>
  )
}
