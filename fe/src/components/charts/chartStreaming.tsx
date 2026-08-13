import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Wifi } from 'lucide-react'
import { fetchPaperPrice } from '../../api/client'
import { Chip } from '../ui/Chip'
import { Select } from '../ui/Form'

export const BAR_COUNT_OPTIONS = [40, 60, 80, 100, 120, 150, 200, 300] as const

export type OhlcBar = {
  open: number
  high: number
  low: number
  close: number
  [key: string]: unknown
}

export function applyLiveBars<T extends OhlcBar>(
  bars: T[],
  maxBars: number,
  liveLtp: number | null | undefined,
): T[] {
  let rows = maxBars > 0 && bars.length > maxBars ? bars.slice(-maxBars) : bars.slice()
  if (rows.length && liveLtp != null && Number.isFinite(Number(liveLtp))) {
    const last = { ...rows[rows.length - 1] }
    const px = Number(liveLtp)
    last.close = px
    last.high = Math.max(Number(last.high), px, Number(last.open))
    last.low = Math.min(Number(last.low), px, Number(last.open))
    rows = [...rows.slice(0, -1), last]
  }
  return rows
}

export function useChartLiveStream(opts: {
  ticker?: string | null
  assetClass?: string | null
  defaultBars?: number
  /** Default true — live LTP streaming on. */
  defaultStreamOn?: boolean
}) {
  const [streamOn, setStreamOn] = useState(opts.defaultStreamOn ?? true)
  const [barCount, setBarCount] = useState(opts.defaultBars ?? 100)
  const ticker = String(opts.ticker ?? '').trim()
  const assetClass = String(opts.assetClass ?? 'india') || 'india'
  const canStream = ticker.length > 0

  const priceQuery = useQuery({
    queryKey: ['chart-live-ltp', assetClass, ticker],
    queryFn: () => fetchPaperPrice(ticker, assetClass),
    enabled: canStream && streamOn,
    refetchInterval: streamOn ? 2_500 : false,
    refetchIntervalInBackground: true,
    staleTime: 1_000,
    retry: false,
  })

  const liveLtp = priceQuery.data?.price ?? null

  return {
    streamOn,
    setStreamOn,
    barCount,
    setBarCount,
    liveLtp: streamOn ? liveLtp : null,
    canStream,
  }
}

function fmtLtp(v: number) {
  return v.toLocaleString(undefined, { maximumFractionDigits: v >= 100 ? 2 : 4 })
}

/** Streaming + bars toolbar for candle/line charts. */
export function ChartStreamControls({
  streamOn,
  setStreamOn,
  barCount,
  setBarCount,
  canStream,
  liveLtp,
  className = '',
}: {
  streamOn: boolean
  setStreamOn: (v: boolean | ((prev: boolean) => boolean)) => void
  barCount: number
  setBarCount: (n: number) => void
  canStream: boolean
  liveLtp?: number | null
  className?: string
}) {
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      {canStream && (
        <Chip selected={streamOn} onClick={() => setStreamOn((v) => !v)}>
          {streamOn ? (
            <span className="inline-flex items-center gap-1">
              <Wifi size={12} /> Streaming on
            </span>
          ) : (
            'Streaming off'
          )}
        </Chip>
      )}
      <label className="inline-flex items-center gap-1.5 text-xs text-slate-400">
        Bars
        <Select
          value={String(barCount)}
          onChange={(e) => setBarCount(Number(e.target.value) || 100)}
          className="!w-auto !py-1.5 text-xs"
        >
          {BAR_COUNT_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </Select>
      </label>
      {streamOn && liveLtp != null && Number.isFinite(liveLtp) && (
        <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-emerald-300 ring-1 ring-emerald-500/30">
          LTP {fmtLtp(liveLtp)}
          <Wifi size={10} className="text-emerald-400/80" />
        </span>
      )}
    </div>
  )
}

/** Convenience: hook + apply bars in one call for chart components. */
export function useLiveChartData<T extends OhlcBar>(
  chartData: T[],
  opts: {
    ticker?: string | null
    assetClass?: string | null
    defaultBars?: number
    defaultStreamOn?: boolean
  },
) {
  const stream = useChartLiveStream(opts)
  const bars = useMemo(
    () => applyLiveBars(chartData, stream.barCount, stream.liveLtp),
    [chartData, stream.barCount, stream.liveLtp],
  )
  return { ...stream, bars }
}
