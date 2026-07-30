import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { apiErrorMessage, fetchSupportResistanceChart } from '../../api/client'
import { SupportResistanceChart, type SRChartBar, type SRTrendline } from './SupportResistanceChart'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { FormField, Input, Select } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'

const EMA_CHOICES = [5, 9, 20, 50, 200]
const CHART_TIMEFRAMES = ['15m', '30m', '1h', '4h', '1d', '1wk']
const ENTRY_TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h']

function verdictAction(direction: string | null): 'BUY' | 'SELL' | 'HOLD' {
  if (direction === 'LONG') return 'BUY'
  if (direction === 'SHORT') return 'SELL'
  return 'HOLD'
}

export function SupportResistanceChartPanel({
  ticker, assetClass, timeframe, fallback, lastClose,
}: {
  ticker: string
  assetClass: string
  timeframe: string
  fallback: {
    chartData: SRChartBar[]
    supportZone: [number, number] | null
    resistanceZone: [number, number] | null
    trendlines: SRTrendline[]
  }
  lastClose?: number
}) {
  const [chartTf, setChartTf] = useState(CHART_TIMEFRAMES.includes(timeframe) ? timeframe : '1d')
  const [entryTf, setEntryTf] = useState('15m')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [includeVolume, setIncludeVolume] = useState(true)
  const [emaPeriods, setEmaPeriods] = useState<number[]>([20, 50])
  const [includeRsi, setIncludeRsi] = useState(false)
  const [includeFibonacci, setIncludeFibonacci] = useState(false)
  const [includeSupplyDemand, setIncludeSupplyDemand] = useState(false)
  const [includeOrderBlocks, setIncludeOrderBlocks] = useState(false)
  const [chartType, setChartType] = useState<'candles' | 'line'>('candles')

  const mut = useMutation({
    mutationFn: () =>
      fetchSupportResistanceChart({
        ticker,
        asset_class: assetClass,
        timeframe: chartTf,
        ltf: entryTf,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        include_volume: includeVolume,
        ema_periods: emaPeriods,
        include_rsi: includeRsi,
        include_fibonacci: includeFibonacci,
        include_supply_demand: includeSupplyDemand,
        include_order_blocks: includeOrderBlocks,
      }),
  })

  // Load once with sensible defaults so there's a chart to look at
  // immediately, without requiring the user to press "Update" first.
  useEffect(() => {
    mut.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  const toggleEma = (p: number) =>
    setEmaPeriods((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p].sort((a, b) => a - b)))

  const data = mut.data
  const setup = data?.trade_setup

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <FormField label="Zone timeframe">
            <Select value={chartTf} onChange={(e) => setChartTf(e.target.value)} className="w-28">
              {CHART_TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
            </Select>
          </FormField>
          <FormField label="Entry timeframe">
            <Select value={entryTf} onChange={(e) => setEntryTf(e.target.value)} className="w-28">
              {ENTRY_TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
            </Select>
          </FormField>
          <FormField label="From">
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-40" />
          </FormField>
          <FormField label="To">
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-40" />
          </FormField>
          <Button size="sm" onClick={() => mut.mutate()} disabled={mut.isPending}>
            {mut.isPending ? 'Loading…' : 'Update chart'}
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">Chart:</span>
          <Chip selected={chartType === 'candles'} onClick={() => setChartType('candles')}>Candlestick</Chip>
          <Chip selected={chartType === 'line'} onClick={() => setChartType('line')}>Line</Chip>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">Show:</span>
          <Chip selected={includeVolume} onClick={() => { setIncludeVolume((v) => !v); }}>Volume</Chip>
          {EMA_CHOICES.map((p) => (
            <Chip key={p} selected={emaPeriods.includes(p)} onClick={() => toggleEma(p)}>{p} EMA</Chip>
          ))}
          <Chip selected={includeRsi} onClick={() => { setIncludeRsi((v) => !v); }}>RSI</Chip>
          <Chip selected={includeFibonacci} onClick={() => { setIncludeFibonacci((v) => !v); }}>Fibonacci retracement</Chip>
          <Chip selected={includeSupplyDemand} onClick={() => { setIncludeSupplyDemand((v) => !v); }}>Supply/Demand zones</Chip>
          <Chip selected={includeOrderBlocks} onClick={() => { setIncludeOrderBlocks((v) => !v); }}>Order blocks</Chip>
        </div>
      </div>

      {mut.isPending && <Loading message="Loading chart…" />}
      {mut.isError && <Alert type="error">{apiErrorMessage(mut.error)}</Alert>}

      {setup && (
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Trade setup</p>
              <Badge action={verdictAction(setup.direction)} />
              <span className="text-xs text-slate-400">{setup.verdict}</span>
            </div>
            <span className="text-[11px] text-slate-500">{setup.ltf} entry · {setup.htf} zones</span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500">Confidence</p>
              <p className="font-medium text-white">{setup.confidence_pct != null ? `${setup.confidence_pct}%` : '—'}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Stop-loss</p>
              <p className="font-medium text-rose-400">{setup.sl_pct != null ? `-${setup.sl_pct}%` : '—'}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Take-profit</p>
              <p className="font-medium text-emerald-400">{setup.tp_pct != null ? `+${setup.tp_pct}%` : '—'}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Time to stay in trade</p>
              <p className="font-medium text-white">{setup.hold_duration ?? '—'}</p>
            </div>
          </div>
          {Boolean(setup.confluence_notes?.length) && (
            <div className="mt-3 border-t border-slate-800/60 pt-2">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Confluence</p>
              <ul className="space-y-1 text-xs text-slate-400">
                {setup.confluence_notes.map((n, i) => <li key={i}>• {n}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {(data?.breakout || data?.breakdown) && (
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Breakout / breakdown probability <span className="normal-case text-slate-600">(rules-based estimate, not a statistical forecast)</span>
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {data?.breakout && (
              <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 p-2.5">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-emerald-400">Breakout above {data.breakout.level.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</p>
                  <p className="text-lg font-semibold text-emerald-400">{data.breakout.probability_pct.toFixed(0)}%</p>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">
                  Tested {data.breakout.touches_recent}x recently · {data.breakout.distance_pct >= 0 ? `${data.breakout.distance_pct.toFixed(1)}% away` : 'already inside the zone'}
                  {data.breakout.projected_move_pct != null && ` · typical move ~${data.breakout.projected_move_pct.toFixed(1)}% higher if it breaks`}
                </p>
              </div>
            )}
            {data?.breakdown && (
              <div className="rounded-md border border-rose-500/20 bg-rose-500/5 p-2.5">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-rose-400">Breakdown below {data.breakdown.level.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</p>
                  <p className="text-lg font-semibold text-rose-400">{data.breakdown.probability_pct.toFixed(0)}%</p>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">
                  Tested {data.breakdown.touches_recent}x recently · {data.breakdown.distance_pct >= 0 ? `${data.breakdown.distance_pct.toFixed(1)}% away` : 'already inside the zone'}
                  {data.breakdown.projected_move_pct != null && ` · typical move ~${data.breakdown.projected_move_pct.toFixed(1)}% lower if it breaks`}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {Boolean((data?.bollinger && data.bollinger.signal !== 'none') || data?.fibonacci) && (
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Bollinger &amp; Fibonacci <span className="normal-case text-slate-600">(extra confluence, not a replacement for the trade setup)</span>
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {data?.bollinger && data.bollinger.signal !== 'none' && (
              <div className={`rounded-md border p-2.5 ${
                data.bollinger.signal === 'bullish'
                  ? 'border-emerald-500/20 bg-emerald-500/5'
                  : 'border-rose-500/20 bg-rose-500/5'
              }`}
              >
                <div className="flex items-center justify-between">
                  <p className={`text-xs font-medium ${data.bollinger.signal === 'bullish' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    Bollinger mean-reversion — {data.bollinger.signal}
                  </p>
                  <p className={`text-sm font-semibold ${data.bollinger.signal === 'bullish' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    %B {data.bollinger.percent_b.toFixed(2)}
                  </p>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">{data.bollinger.note}</p>
              </div>
            )}
            {data?.fibonacci && (
              <div className={`rounded-md border p-2.5 ${data.fibonacci.at_key_level ? 'border-violet-500/30 bg-violet-500/5' : 'border-slate-700/40 bg-slate-800/30'}`}>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-violet-400">Fibonacci retracement ({data.fibonacci.trend})</p>
                  <p className="text-sm font-semibold text-violet-400">{(data.fibonacci.nearest_level.ratio * 100).toFixed(1)}%</p>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">
                  Nearest level {data.fibonacci.nearest_level.price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                  {data.fibonacci.at_key_level ? ' — price sitting right at this level.' : `, between swing ${data.fibonacci.swing_low.toLocaleString('en-IN', { maximumFractionDigits: 2 })}–${data.fibonacci.swing_high.toLocaleString('en-IN', { maximumFractionDigits: 2 })}.`}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {Boolean(data?.candlestick_patterns?.length || data?.chart_patterns?.length || data?.divergences?.length) && (
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Patterns &amp; divergences <span className="normal-case text-slate-600">(rules-based pattern read, not a trained model)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data!.candlestick_patterns.map((p, i) => (
              <span
                key={`cp-${i}`}
                title={p.note}
                className={`rounded-full border px-2 py-1 text-[11px] font-medium ${
                  p.direction === 'bullish'
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                    : p.direction === 'bearish'
                      ? 'border-rose-500/30 bg-rose-500/10 text-rose-400'
                      : 'border-slate-600/30 bg-slate-600/10 text-slate-400'
                }`}
              >
                {p.name}{p.bars_ago > 0 ? ` · ${p.bars_ago}b ago` : ''}
              </span>
            ))}
            {data!.chart_patterns.map((p, i) => (
              <span
                key={`chp-${i}`}
                title={p.note}
                className={`rounded-full border px-2 py-1 text-[11px] font-medium ${
                  p.direction === 'bullish'
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                    : 'border-rose-500/30 bg-rose-500/10 text-rose-400'
                }`}
              >
                {p.name}
              </span>
            ))}
            {data!.divergences.map((d, i) => (
              <span
                key={`dv-${i}`}
                title={d.note}
                className={`rounded-full border px-2 py-1 text-[11px] font-medium ${
                  d.direction === 'bullish'
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                    : 'border-rose-500/30 bg-rose-500/10 text-rose-400'
                }`}
              >
                {d.name}
              </span>
            ))}
          </div>
        </div>
      )}

      <SupportResistanceChart
        chartData={data?.chart_data ?? fallback.chartData}
        supportZone={data ? data.support_zone : fallback.supportZone}
        resistanceZone={data ? data.resistance_zone : fallback.resistanceZone}
        trendlines={data ? data.trendlines : fallback.trendlines}
        lastClose={lastClose}
        emas={data?.emas}
        rsi={data?.rsi}
        chartType={chartType}
        fibonacci={data?.fibonacci ?? null}
        supplyDemandZones={data?.supply_demand_zones ?? []}
        orderBlocks={data?.order_blocks ?? []}
      />

      {Boolean(data?.summary?.length) && (
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Summary of observations</p>
          <ul className="space-y-1 text-xs text-slate-300">
            {data!.summary.map((s, i) => <li key={i}>• {s}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
