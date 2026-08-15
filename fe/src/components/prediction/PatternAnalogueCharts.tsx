import { useMemo } from 'react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useNarrowChart } from '../charts/chartLayout'

type Candle = {
  time?: string
  open?: number
  high?: number
  low?: number
  close?: number
  i?: number
  zone?: string
}

const BULL = '#34d399'
const BEAR = '#f87171'
const FWD_BULL = '#a7f3d0'
const FWD_BEAR = '#fecaca'
const BEFORE_BULL = '#7dd3fc'
const BEFORE_BEAR = '#93c5fd'
const OVERLAY_COLORS = ['#38bdf8', '#a78bfa', '#fbbf24', '#fb7185', '#2dd4bf', '#e879f9', '#94a3b8']

function CandlestickShape(props: {
  x?: number
  y?: number
  width?: number
  height?: number
  low?: number
  high?: number
  open?: number
  close?: number
  payload?: Candle
}) {
  const payload = props.payload
  const x = props.x ?? 0
  const y = props.y ?? 0
  const width = props.width ?? 0
  const height = props.height ?? 0
  const open = props.open ?? payload?.open
  const high = props.high ?? payload?.high
  const low = props.low ?? payload?.low
  const close = props.close ?? payload?.close
  if (high == null || low == null || high === low || open == null || close == null) return null
  const zone = payload?.zone
  const isFwd = zone === 'forward'
  const isBefore = zone === 'before'
  const isBullish = close >= open
  let color = isBullish ? BULL : BEAR
  if (isFwd) color = isBullish ? FWD_BULL : FWD_BEAR
  if (isBefore) color = isBullish ? BEFORE_BULL : BEFORE_BEAR
  const ratio = height / (high - low)
  const bodyTop = y + (high - Math.max(open, close)) * ratio
  const bodyHeight = Math.max(1, Math.abs(close - open) * ratio)
  const cx = x + width / 2
  return (
    <g>
      <line x1={cx} y1={y} x2={cx} y2={y + height} stroke={color} strokeWidth={1} />
      <rect
        x={x}
        y={bodyTop}
        width={Math.max(1, width * 0.85)}
        height={bodyHeight}
        fill={color}
        stroke={color}
        opacity={isFwd || isBefore ? 0.55 : 1}
      />
    </g>
  )
}

function toChartRows(before: Candle[], candles: Candle[], forward: Candle[] = []) {
  const rows = [...before, ...candles, ...forward].filter((c) => c && c.high != null && c.low != null)
  return rows.map((c, idx) => {
    const open = Number(c.open)
    const high = Number(c.high)
    const low = Number(c.low)
    const close = Number(c.close)
    return {
      ...c,
      idx,
      open,
      high,
      low,
      close,
      range: [low, high] as [number, number],
      label: String(c.time || '').slice(5, 16) || String(idx + 1),
    }
  })
}

function CandleTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: Record<string, unknown> }> }) {
  if (!active || !payload?.length) return null
  const p = payload[0]?.payload || {}
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950/95 px-2.5 py-1.5 text-[11px] text-slate-200 shadow-lg">
      <p className="font-medium text-white">{String(p.time ?? p.label ?? '')}</p>
      <p>O {Number(p.open).toFixed(2)} · H {Number(p.high).toFixed(2)}</p>
      <p>L {Number(p.low).toFixed(2)} · C {Number(p.close).toFixed(2)}</p>
      {p.zone === 'before' ? <p className="text-sky-300/90">Before pattern</p> : null}
      {p.zone === 'forward' ? <p className="text-amber-300/90">After pattern</p> : null}
    </div>
  )
}

export function PatternCandleChart({
  candles,
  forwardCandles = [],
  beforeCandles = [],
  height = 160,
  title,
  subtitle,
  compact = false,
}: {
  candles: Candle[]
  forwardCandles?: Candle[]
  beforeCandles?: Candle[]
  height?: number
  title?: string
  subtitle?: string
  compact?: boolean
}) {
  const data = useMemo(
    () => toChartRows(beforeCandles, candles, forwardCandles),
    [beforeCandles, candles, forwardCandles],
  )
  const narrow = useNarrowChart()
  if (!data.length) {
    return <p className="text-xs text-slate-600">No candle data</p>
  }

  const tickEvery = Math.max(1, Math.ceil(data.length / (compact || narrow ? 4 : 6)))
  const axisW = compact || narrow ? 24 : 48
  const tickFs = compact || narrow ? 8 : 9
  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-950/50 p-2">
      {(title || subtitle) && (
        <div className="mb-1.5 px-0.5">
          {title ? <p className="text-xs font-medium text-slate-200">{title}</p> : null}
          {subtitle ? <p className="text-[10px] text-slate-500">{subtitle}</p> : null}
        </div>
      )}
      <div style={{ width: '100%', height }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 4, right: narrow ? 0 : 4, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: '#64748b', fontSize: tickFs }}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
              interval={0}
              tickFormatter={(v, i) => (i % tickEvery === 0 ? String(v) : '')}
              height={narrow ? 14 : 24}
            />
            <YAxis
              domain={['dataMin', 'dataMax']}
              width={axisW}
              tick={{ fill: '#64748b', fontSize: tickFs }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => Number(v).toFixed(narrow || compact ? 0 : 1)}
              tickCount={narrow ? 4 : undefined}
            />
            <Tooltip content={<CandleTooltip />} />
            <Bar dataKey="range" shape={CandlestickShape} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {(beforeCandles.length > 0 || forwardCandles.length > 0) ? (
        <p className="mt-1 text-[10px] text-slate-600">
          {beforeCandles.length > 0 ? 'Blue dim = before · ' : ''}
          {forwardCandles.length > 0 ? 'Pale dim = after' : ''}
        </p>
      ) : null}
    </div>
  )
}

type OverlaySeries = { id: string; label: string; shape_pct: number[]; accent?: boolean }

export function PatternShapeOverlay({
  base,
  matches,
  height = 180,
}: {
  base: { shape_pct?: number[]; label?: string }
  matches: OverlaySeries[]
  height?: number
}) {
  const data = useMemo(() => {
    const baseShape = Array.isArray(base.shape_pct) ? base.shape_pct.map(Number) : []
    const maxLen = Math.max(baseShape.length, ...matches.map((m) => (m.shape_pct || []).length), 0)
    if (!maxLen) return []
    const rows: Record<string, number | string>[] = []
    for (let i = 0; i < maxLen; i += 1) {
      const row: Record<string, number | string> = { i: i + 1, label: String(i + 1) }
      if (i < baseShape.length && Number.isFinite(baseShape[i])) row.base = baseShape[i]
      matches.forEach((m) => {
        const v = Number((m.shape_pct || [])[i])
        if (Number.isFinite(v)) row[m.id] = v
      })
      rows.push(row)
    }
    return rows
  }, [base, matches])

  const narrow = useNarrowChart()
  if (!data.length) return null

  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-950/50 p-2">
      <p className="mb-1 text-xs font-medium text-slate-200">Shape overlay (% from first close)</p>
      <p className="mb-2 text-[10px] text-slate-500">
        Base pattern in white · historical matches as colored lines (same bar index)
      </p>
      <div style={{ width: '100%', height }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 4, right: narrow ? 0 : 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: narrow ? 8 : 9 }} tickLine={false} axisLine={{ stroke: '#334155' }} height={narrow ? 14 : 24} />
            <YAxis
              width={narrow ? 24 : 40}
              tick={{ fill: '#64748b', fontSize: narrow ? 8 : 9 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `${Number(v).toFixed(1)}%`}
              tickCount={narrow ? 4 : undefined}
            />
            <Tooltip
              contentStyle={{ background: '#020617', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
              labelFormatter={(l) => `Bar ${l}`}
            />
            <Line
              type="monotone"
              dataKey="base"
              name={base.label || 'Base'}
              stroke="#f8fafc"
              strokeWidth={2.25}
              dot={false}
              isAnimationActive={false}
            />
            {matches.map((m, idx) => (
              <Line
                key={m.id}
                type="monotone"
                dataKey={m.id}
                name={m.label}
                stroke={OVERLAY_COLORS[idx % OVERLAY_COLORS.length]}
                strokeWidth={m.accent ? 1.75 : 1.25}
                strokeOpacity={0.85}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] text-slate-300">
          <span className="inline-block h-0.5 w-3 bg-slate-100" /> Base
        </span>
        {matches.map((m, idx) => (
          <span key={m.id} className="inline-flex items-center gap-1 text-[10px] text-slate-400">
            <span
              className="inline-block h-0.5 w-3"
              style={{ background: OVERLAY_COLORS[idx % OVERLAY_COLORS.length] }}
            />
            {m.label}
          </span>
        ))}
      </div>
    </div>
  )
}
