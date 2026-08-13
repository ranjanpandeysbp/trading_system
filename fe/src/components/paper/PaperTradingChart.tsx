import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Pencil, Trash2, Wifi, MoveDiagonal2 } from 'lucide-react'
import { apiErrorMessage, fetchPaperPrice, runProTradeTickerChart } from '../../api/client'
import { Chip } from '../ui/Chip'
import { Button } from '../ui/Button'
import { Input, Select } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'

type Row = Record<string, unknown>
type ChartStyle = 'candles' | 'line'
type DrawMode = 'none' | 'sr' | 'trendline'

type Candle = {
  t?: string
  label?: string
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number | null
}

type CustomSr = { id: string; price: number; label: string }
/** Fractional bar indices so endpoints can slide smoothly (TradingView-style). */
type TrendLine = {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
  extendLeft: boolean
  extendRight: boolean
}

type Selection =
  | { kind: 'sr'; id: string }
  | { kind: 'tl'; id: string }
  | null

type DragSession =
  | { type: 'create-sr'; price: number }
  | { type: 'create-tl'; x1: number; y1: number; x2: number; y2: number }
  | { type: 'move-sr'; id: string }
  | { type: 'move-tl'; id: string; ox1: number; oy1: number; ox2: number; oy2: number; startX: number; startY: number }
  | { type: 'tl-p1'; id: string }
  | { type: 'tl-p2'; id: string }

type IndicatorId =
  | 'rsi'
  | 'supertrend'
  | 'volume'
  | 'bollinger'
  | 'ema_5'
  | 'ema_9'
  | 'ema_20'
  | 'ema_50'
  | 'ema_200'

const INDICATOR_OPTIONS: { id: IndicatorId; label: string }[] = [
  { id: 'rsi', label: 'RSI' },
  { id: 'supertrend', label: 'Supertrend' },
  { id: 'volume', label: 'Volume' },
  { id: 'bollinger', label: 'Bollinger' },
  { id: 'ema_5', label: 'EMA 5' },
  { id: 'ema_9', label: 'EMA 9' },
  { id: 'ema_20', label: 'EMA 20' },
  { id: 'ema_50', label: 'EMA 50' },
  { id: 'ema_200', label: 'EMA 200' },
]

const DEFAULT_INDICATORS: IndicatorId[] = ['volume', 'ema_9', 'ema_20', 'bollinger', 'rsi']

const BAR_COUNT_OPTIONS = [40, 60, 80, 100, 120, 150, 200, 300] as const
const RIGHT_PAD_BARS = 8

const OVERLAY_COLORS: Record<string, string> = {
  ema_5: '#fbbf24',
  ema_9: '#a78bfa',
  ema_20: '#34d399',
  ema_50: '#fb923c',
  ema_200: '#f472b6',
  supertrend: '#22d3ee',
  bb_upper: '#64748b',
  bb_mid: '#94a3b8',
  bb_lower: '#64748b',
}

const BULL = '#10b981'
const BEAR = '#f43f5e'
const INTERVALS = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '1d', label: '1d' },
] as const

/** Must match ComposedChart margin + YAxis widths used below */
const PLOT_MARGIN = { top: 12, right: 72, left: 8, bottom: 28 }
const PRICE_AXIS_WIDTH = 56

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function CandlestickShape(props: {
  x?: number
  y?: number
  width?: number
  height?: number
  payload?: Record<string, unknown>
}) {
  const { x = 0, y = 0, width = 0, height = 0, payload } = props
  if (payload?.__pad) return null
  const open = Number(payload?.open)
  const high = Number(payload?.high)
  const low = Number(payload?.low)
  const close = Number(payload?.close)
  if (![open, high, low, close].every(Number.isFinite) || high === low) return null
  const isBullish = close >= open
  const color = isBullish ? BULL : BEAR
  const ratio = height / (high - low)
  const bodyTop = y + (high - Math.max(open, close)) * ratio
  const bodyHeight = Math.max(1, Math.abs(close - open) * ratio)
  const cx = x + width / 2
  const bodyW = Math.max(1, width * 0.7)
  return (
    <g>
      <line x1={cx} y1={y} x2={cx} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={x + (width - bodyW) / 2} y={bodyTop} width={bodyW} height={bodyHeight} fill={color} stroke={color} />
    </g>
  )
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n))
}

type PlotGeom = {
  left: number
  top: number
  width: number
  height: number
  yMin: number
  yMax: number
  nSlots: number
}

function plotFromClient(
  rect: DOMRect,
  clientX: number,
  clientY: number,
  yMin: number,
  yMax: number,
  nSlots: number,
): { x: number; price: number; px: number; py: number } | null {
  const left = PLOT_MARGIN.left + PRICE_AXIS_WIDTH
  const right = PLOT_MARGIN.right
  const top = PLOT_MARGIN.top
  const bottom = PLOT_MARGIN.bottom
  const plotW = rect.width - left - right
  const plotH = rect.height - top - bottom
  if (plotW <= 0 || plotH <= 0 || !(yMax > yMin) || nSlots < 1) return null
  const px = clientX - rect.left - left
  const py = clientY - rect.top - top
  const price = yMax - (py / plotH) * (yMax - yMin)
  const x = nSlots <= 1 ? 0 : (px / plotW) * (nSlots - 1)
  return { x, price, px, py }
}

function toSvg(geom: PlotGeom, xIdx: number, price: number) {
  const { left, top, width, height, yMin, yMax, nSlots } = geom
  const sx = left + (nSlots <= 1 ? 0 : (xIdx / Math.max(nSlots - 1, 1)) * width)
  const sy = top + ((yMax - price) / (yMax - yMin)) * height
  return { x: sx, y: sy }
}

/** Clip infinite/extended line to plot rectangle; returns SVG endpoints. */
function clipTrendline(
  geom: PlotGeom,
  tl: TrendLine,
): { x1: number; y1: number; x2: number; y2: number } | null {
  const a = toSvg(geom, tl.x1, tl.y1)
  const b = toSvg(geom, tl.x2, tl.y2)
  const dx = b.x - a.x
  const dy = b.y - a.y
  if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) return { x1: a.x, y1: a.y, x2: b.x, y2: b.y }

  const left = geom.left
  const right = geom.left + geom.width
  const top = geom.top
  const bottom = geom.top + geom.height

  // Parametric: P = A + t*(B-A). Segment is t in [0,1]; extend expands range.
  let t0 = tl.extendLeft ? -1e6 : 0
  let t1 = tl.extendRight ? 1e6 : 1

  // Clip against plot box (Liang-Barsky style on t)
  const clipT = (p: number, q: number, tMin: number, tMax: number): [number, number] | null => {
    if (Math.abs(p) < 1e-12) {
      if (q < 0) return null
      return [tMin, tMax]
    }
    const r = q / p
    if (p < 0) {
      if (r > tMax) return null
      return [Math.max(tMin, r), tMax]
    }
    if (r < tMin) return null
    return [tMin, Math.min(tMax, r)]
  }

  let tMin = t0
  let tMax = t1
  const edges: [number, number][] = [
    [-dx, a.x - left],
    [dx, right - a.x],
    [-dy, a.y - top],
    [dy, bottom - a.y],
  ]
  for (const [p, q] of edges) {
    const next = clipT(p, q, tMin, tMax)
    if (!next) return null
    ;[tMin, tMax] = next
  }
  if (tMin > tMax) return null
  return {
    x1: a.x + tMin * dx,
    y1: a.y + tMin * dy,
    x2: a.x + tMax * dx,
    y2: a.y + tMax * dy,
  }
}

function distPointToSeg(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const len2 = dx * dx + dy * dy
  if (len2 < 1e-8) return Math.hypot(px - x1, py - y1)
  let t = ((px - x1) * dx + (py - y1) * dy) / len2
  t = clamp(t, 0, 1)
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

function DrawingCanvas({
  drawMode,
  yMin,
  yMax,
  realBarCount,
  totalSlots,
  customSr,
  trendLines,
  selection,
  onSelect,
  onChangeSr,
  onChangeTl,
  onCreateSr,
  onCreateTl,
}: {
  drawMode: DrawMode
  yMin: number
  yMax: number
  realBarCount: number
  totalSlots: number
  customSr: CustomSr[]
  trendLines: TrendLine[]
  selection: Selection
  onSelect: (s: Selection) => void
  onChangeSr: (id: string, price: number) => void
  onChangeTl: (id: string, patch: Partial<TrendLine>) => void
  onCreateSr: (price: number) => void
  onCreateTl: (tl: Omit<TrendLine, 'id'>) => void
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [drag, setDrag] = useState<DragSession | null>(null)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const dragRef = useRef<DragSession | null>(null)
  dragRef.current = drag

  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect()
      setSize({ w: r.width, h: r.height })
    })
    ro.observe(el)
    const r = el.getBoundingClientRect()
    setSize({ w: r.width, h: r.height })
    return () => ro.disconnect()
  }, [])

  const geom: PlotGeom | null = useMemo(() => {
    if (size.w < 40 || size.h < 40 || !(yMax > yMin) || totalSlots < 1) return null
    return {
      left: PLOT_MARGIN.left + PRICE_AXIS_WIDTH,
      top: PLOT_MARGIN.top,
      width: size.w - PLOT_MARGIN.left - PRICE_AXIS_WIDTH - PLOT_MARGIN.right,
      height: size.h - PLOT_MARGIN.top - PLOT_MARGIN.bottom,
      yMin,
      yMax,
      nSlots: totalSlots,
    }
  }, [size, yMin, yMax, totalSlots])

  const readPlot = useCallback(
    (clientX: number, clientY: number) => {
      const el = rootRef.current
      if (!el || !geom) return null
      return plotFromClient(el.getBoundingClientRect(), clientX, clientY, yMin, yMax, totalSlots)
    },
    [geom, yMin, yMax, totalSlots],
  )

  const hitTest = useCallback(
    (clientX: number, clientY: number): Selection => {
      if (!geom) return null
      const el = rootRef.current
      if (!el) return null
      const rect = el.getBoundingClientRect()
      const px = clientX - rect.left
      const py = clientY - rect.top
      const HIT = 8

      // Prefer handles of selected item
      if (selection?.kind === 'tl') {
        const tl = trendLines.find((t) => t.id === selection.id)
        if (tl) {
          const p1 = toSvg(geom, tl.x1, tl.y1)
          const p2 = toSvg(geom, tl.x2, tl.y2)
          if (Math.hypot(px - p1.x, py - p1.y) <= HIT + 2) return selection
          if (Math.hypot(px - p2.x, py - p2.y) <= HIT + 2) return selection
        }
      }
      if (selection?.kind === 'sr') {
        const sr = customSr.find((s) => s.id === selection.id)
        if (sr) {
          const mid = toSvg(geom, (totalSlots - 1) / 2, sr.price)
          if (Math.abs(py - mid.y) <= HIT) return selection
        }
      }

      for (const tl of [...trendLines].reverse()) {
        const clipped = clipTrendline(geom, { ...tl, extendLeft: tl.extendLeft, extendRight: tl.extendRight })
        if (!clipped) continue
        if (distPointToSeg(px, py, clipped.x1, clipped.y1, clipped.x2, clipped.y2) <= HIT) {
          return { kind: 'tl', id: tl.id }
        }
      }
      for (const sr of [...customSr].reverse()) {
        const y = toSvg(geom, 0, sr.price).y
        if (Math.abs(py - y) <= HIT && px >= geom.left && px <= geom.left + geom.width) {
          return { kind: 'sr', id: sr.id }
        }
      }
      return null
    },
    [geom, trendLines, customSr, selection, totalSlots],
  )

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) {
        if (drawMode === 'none') {
          const hit = hitTest(e.clientX, e.clientY)
          setHoverId(hit ? hit.id : null)
        }
        return
      }
      const pt = readPlot(e.clientX, e.clientY)
      if (!pt) return
      const xClamped = clamp(pt.x, -0.5, Math.max(totalSlots - 1, 0))
      if (d.type === 'create-sr') {
        setDrag({ type: 'create-sr', price: pt.price })
      } else if (d.type === 'create-tl') {
        setDrag({ ...d, x2: xClamped, y2: pt.price })
      } else if (d.type === 'move-sr') {
        onChangeSr(d.id, pt.price)
      } else if (d.type === 'tl-p1') {
        onChangeTl(d.id, { x1: xClamped, y1: pt.price })
      } else if (d.type === 'tl-p2') {
        onChangeTl(d.id, { x2: xClamped, y2: pt.price })
      } else if (d.type === 'move-tl') {
        const dx = xClamped - d.startX
        const dy = pt.price - d.startY
        onChangeTl(d.id, {
          x1: clamp(d.ox1 + dx, -0.5, Math.max(totalSlots - 1, 0)),
          y1: d.oy1 + dy,
          x2: clamp(d.ox2 + dx, -0.5, Math.max(totalSlots - 1, 0)),
          y2: d.oy2 + dy,
        })
      }
    }
    const onUp = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) return
      const pt = readPlot(e.clientX, e.clientY)
      if (d.type === 'create-sr') {
        const price = pt?.price ?? d.price
        if (Number.isFinite(price)) onCreateSr(price)
      } else if (d.type === 'create-tl') {
        const x2 = pt ? clamp(pt.x, -0.5, Math.max(totalSlots - 1, 0)) : d.x2
        const y2 = pt?.price ?? d.y2
        const moved = Math.hypot(x2 - d.x1, y2 - d.y1) > 0.15 || Math.abs(y2 - d.y1) > Math.abs(yMax - yMin) * 0.002
        if (moved) {
          onCreateTl({
            x1: d.x1,
            y1: d.y1,
            x2,
            y2,
            extendLeft: false,
            extendRight: false,
          })
        }
      }
      setDrag(null)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [drawMode, hitTest, readPlot, onChangeSr, onChangeTl, onCreateSr, onCreateTl, totalSlots, yMin, yMax])

  const onPointerDown = (e: ReactPointerEvent) => {
    if (!geom) return
    const pt = readPlot(e.clientX, e.clientY)
    if (!pt) return
    // Only interact inside plot (with small pad)
    if (pt.px < -4 || pt.py < -4 || pt.px > geom.width + 4 || pt.py > geom.height + 4) {
      if (drawMode === 'none') onSelect(null)
      return
    }
    e.preventDefault()
    e.stopPropagation()

    if (drawMode === 'sr') {
      onSelect(null)
      setDrag({ type: 'create-sr', price: pt.price })
      return
    }
    if (drawMode === 'trendline') {
      onSelect(null)
      const x = clamp(pt.x, -0.5, Math.max(totalSlots - 1, 0))
      setDrag({ type: 'create-tl', x1: x, y1: pt.price, x2: x, y2: pt.price })
      return
    }

    // Edit mode
    const hit = hitTest(e.clientX, e.clientY)
    if (!hit) {
      onSelect(null)
      return
    }
    onSelect(hit)
    const el = rootRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top

    if (hit.kind === 'sr') {
      setDrag({ type: 'move-sr', id: hit.id })
      return
    }
    const tl = trendLines.find((t) => t.id === hit.id)
    if (!tl) return
    const p1 = toSvg(geom, tl.x1, tl.y1)
    const p2 = toSvg(geom, tl.x2, tl.y2)
    if (Math.hypot(px - p1.x, py - p1.y) <= 10) {
      setDrag({ type: 'tl-p1', id: tl.id })
    } else if (Math.hypot(px - p2.x, py - p2.y) <= 10) {
      setDrag({ type: 'tl-p2', id: tl.id })
    } else {
      const x = clamp(pt.x, -0.5, Math.max(totalSlots - 1, 0))
      setDrag({
        type: 'move-tl',
        id: tl.id,
        ox1: tl.x1,
        oy1: tl.y1,
        ox2: tl.x2,
        oy2: tl.y2,
        startX: x,
        startY: pt.price,
      })
    }
  }

  if (!(yMax > yMin) || realBarCount <= 0 || !geom) {
    return <div ref={rootRef} className="absolute inset-0 z-20 pointer-events-none" />
  }

  const creating = drawMode !== 'none'
  const cursor = creating ? 'crosshair' : hoverId ? 'move' : 'default'

  const previewSr = drag?.type === 'create-sr' ? drag.price : null
  const previewTl = drag?.type === 'create-tl' ? drag : null
  const captureAll = creating || !!drag

  return (
    <div
      ref={rootRef}
      className="absolute inset-0 z-20"
      style={{ cursor, pointerEvents: captureAll ? 'auto' : 'none' }}
      onPointerDown={captureAll ? onPointerDown : undefined}
      onPointerLeave={() => setHoverId(null)}
    >
      {/* Hit targets when editing (pass-through elsewhere so chart tooltip still works) */}
      {!captureAll && (customSr.length > 0 || trendLines.length > 0) && (
        <svg
          width={size.w}
          height={size.h}
          className="absolute inset-0 overflow-visible"
          style={{ pointerEvents: 'none' }}
          onPointerMove={(e) => {
            const hit = hitTest(e.clientX, e.clientY)
            setHoverId(hit ? hit.id : null)
          }}
        >
          {customSr.map((sr) => {
            const y = toSvg(geom, 0, sr.price).y
            return (
              <line
                key={`hit-sr-${sr.id}`}
                x1={geom.left}
                y1={y}
                x2={geom.left + geom.width}
                y2={y}
                stroke="transparent"
                strokeWidth={14}
                style={{ pointerEvents: 'stroke', cursor: 'ns-resize' }}
                onPointerDown={onPointerDown}
              />
            )
          })}
          {trendLines.map((tl) => {
            const clipped = clipTrendline(geom, tl)
            if (!clipped) return null
            return (
              <g key={`hit-tl-${tl.id}`}>
                <line
                  x1={clipped.x1}
                  y1={clipped.y1}
                  x2={clipped.x2}
                  y2={clipped.y2}
                  stroke="transparent"
                  strokeWidth={14}
                  style={{ pointerEvents: 'stroke', cursor: 'move' }}
                  onPointerDown={onPointerDown}
                />
                {selection?.kind === 'tl' && selection.id === tl.id && (
                  <>
                    <circle
                      cx={toSvg(geom, tl.x1, tl.y1).x}
                      cy={toSvg(geom, tl.x1, tl.y1).y}
                      r={10}
                      fill="transparent"
                      style={{ pointerEvents: 'all', cursor: 'grab' }}
                      onPointerDown={onPointerDown}
                    />
                    <circle
                      cx={toSvg(geom, tl.x2, tl.y2).x}
                      cy={toSvg(geom, tl.x2, tl.y2).y}
                      r={10}
                      fill="transparent"
                      style={{ pointerEvents: 'all', cursor: 'grab' }}
                      onPointerDown={onPointerDown}
                    />
                  </>
                )}
              </g>
            )
          })}
          {selection?.kind === 'sr' && (() => {
            const sr = customSr.find((s) => s.id === selection.id)
            if (!sr) return null
            const y = toSvg(geom, 0, sr.price).y
            return (
              <circle
                cx={geom.left + geom.width / 2}
                cy={y}
                r={10}
                fill="transparent"
                style={{ pointerEvents: 'all', cursor: 'ns-resize' }}
                onPointerDown={onPointerDown}
              />
            )
          })()}
        </svg>
      )}
      <svg
        width={size.w}
        height={size.h}
        className="absolute inset-0 overflow-visible"
        style={{ pointerEvents: 'none' }}
      >
        {/* S/R levels */}
        {customSr.map((sr) => {
          const y = toSvg(geom, 0, sr.price).y
          const selected = selection?.kind === 'sr' && selection.id === sr.id
          const hot = hoverId === sr.id || selected
          return (
            <g key={sr.id}>
              <line
                x1={geom.left}
                y1={y}
                x2={geom.left + geom.width}
                y2={y}
                stroke="#fbbf24"
                strokeWidth={hot ? 2 : 1.5}
                strokeDasharray="6 3"
              />
              <text
                x={geom.left + geom.width - 4}
                y={y - 4}
                fill="#fbbf24"
                fontSize={10}
                textAnchor="end"
                style={{ userSelect: 'none' }}
              >
                {sr.label}
              </text>
              {selected && (
                <circle
                  cx={geom.left + geom.width / 2}
                  cy={y}
                  r={5}
                  fill="#0f172a"
                  stroke="#fbbf24"
                  strokeWidth={2}
                />
              )}
            </g>
          )
        })}

        {/* Trendlines */}
        {trendLines.map((tl) => {
          const clipped = clipTrendline(geom, tl)
          if (!clipped) return null
          const selected = selection?.kind === 'tl' && selection.id === tl.id
          const hot = hoverId === tl.id || selected
          const p1 = toSvg(geom, tl.x1, tl.y1)
          const p2 = toSvg(geom, tl.x2, tl.y2)
          return (
            <g key={tl.id}>
              <line
                x1={clipped.x1}
                y1={clipped.y1}
                x2={clipped.x2}
                y2={clipped.y2}
                stroke="#38bdf8"
                strokeWidth={hot ? 2.5 : 2}
              />
              {selected && (
                <>
                  <circle
                    cx={(p1.x + p2.x) / 2}
                    cy={(p1.y + p2.y) / 2}
                    r={4}
                    fill="#0f172a"
                    stroke="#7dd3fc"
                    strokeWidth={1.5}
                  />
                  <circle
                    cx={p1.x}
                    cy={p1.y}
                    r={6}
                    fill="#0f172a"
                    stroke="#38bdf8"
                    strokeWidth={2}
                  />
                  <circle
                    cx={p2.x}
                    cy={p2.y}
                    r={6}
                    fill="#0f172a"
                    stroke="#38bdf8"
                    strokeWidth={2}
                  />
                </>
              )}
            </g>
          )
        })}

        {/* Create preview */}
        {previewSr != null && (
          <g>
            <line
              x1={geom.left}
              y1={toSvg(geom, 0, previewSr).y}
              x2={geom.left + geom.width}
              y2={toSvg(geom, 0, previewSr).y}
              stroke="#fbbf24"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              opacity={0.9}
            />
            <text
              x={geom.left + 6}
              y={toSvg(geom, 0, previewSr).y - 6}
              fill="#fbbf24"
              fontSize={11}
            >
              {fmtNum(previewSr, previewSr >= 100 ? 1 : 3)}
            </text>
          </g>
        )}
        {previewTl && (
          <g>
            {(() => {
              const clip = clipTrendline(geom, {
                id: 'preview',
                x1: previewTl.x1,
                y1: previewTl.y1,
                x2: previewTl.x2,
                y2: previewTl.y2,
                extendLeft: false,
                extendRight: false,
              })
              if (!clip) return null
              const a = toSvg(geom, previewTl.x1, previewTl.y1)
              const b = toSvg(geom, previewTl.x2, previewTl.y2)
              return (
                <>
                  <line
                    x1={clip.x1}
                    y1={clip.y1}
                    x2={clip.x2}
                    y2={clip.y2}
                    stroke="#38bdf8"
                    strokeWidth={2}
                    strokeDasharray="5 3"
                  />
                  <circle cx={a.x} cy={a.y} r={4} fill="#38bdf8" />
                  <circle cx={b.x} cy={b.y} r={4} fill="#38bdf8" />
                </>
              )
            })()}
          </g>
        )}
      </svg>
    </div>
  )
}

export function PaperTradingChart({
  ticker,
  assetClass,
  liveLtp,
}: {
  ticker: string
  assetClass: string
  liveLtp?: number | null
}) {
  const [interval, setIntervalTf] = useState('15m')
  const [barCount, setBarCount] = useState(80)
  const [chartStyle, setChartStyle] = useState<ChartStyle>('candles')
  const [selected, setSelected] = useState<IndicatorId[]>(DEFAULT_INDICATORS)
  const [drawMode, setDrawMode] = useState<DrawMode>('none')
  const [customSr, setCustomSr] = useState<CustomSr[]>([])
  const [trendLines, setTrendLines] = useState<TrendLine[]>([])
  const [selection, setSelection] = useState<Selection>(null)
  const [manualSr, setManualSr] = useState<number | ''>('')
  const [streamOn, setStreamOn] = useState(true)
  const lastTicker = useRef(ticker)

  const isDaily = interval === '1d'
  const mode = isDaily ? 'daily' : 'intraday'

  const clearDrawings = useCallback(() => {
    setCustomSr([])
    setTrendLines([])
    setSelection(null)
    setDrawMode('none')
  }, [])

  useEffect(() => {
    if (lastTicker.current !== ticker) {
      lastTicker.current = ticker
      clearDrawings()
    }
  }, [ticker, clearDrawings])

  useEffect(() => {
    // Indices are relative to the visible window — reset drawings when window changes
    clearDrawings()
  }, [barCount, interval, clearDrawings])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSelection(null)
        setDrawMode('none')
        return
      }
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (!selection) return
      e.preventDefault()
      if (selection.kind === 'sr') {
        setCustomSr((prev) => prev.filter((x) => x.id !== selection.id))
      } else {
        setTrendLines((prev) => prev.filter((x) => x.id !== selection.id))
      }
      setSelection(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selection])

  const chartQuery = useQuery({
    queryKey: ['paper-chart', assetClass, ticker, interval, selected.join(',')],
    queryFn: () =>
      runProTradeTickerChart({
        ticker: ticker.trim(),
        asset_class: assetClass,
        mode,
        from_date: isDaily ? isoDaysAgo(180) : undefined,
        to_date: isDaily ? todayIso() : undefined,
        session_date: isDaily ? undefined : todayIso(),
        interval: isDaily ? '1d' : interval,
        indicators: selected,
        use_ai: false,
      }),
    enabled: ticker.trim().length > 0,
    refetchInterval: streamOn ? (interval === '1m' ? 8_000 : interval === '5m' ? 12_000 : 20_000) : false,
    staleTime: 5_000,
    retry: 1,
  })

  const priceQuery = useQuery({
    queryKey: ['paper-price-stream', assetClass, ticker],
    queryFn: () => fetchPaperPrice(ticker, assetClass),
    enabled: ticker.trim().length > 0 && streamOn,
    refetchInterval: streamOn ? 2_500 : false,
    staleTime: 1_000,
    retry: false,
  })

  const ltp = liveLtp ?? priceQuery.data?.price ?? null
  const data = chartQuery.data as Row | undefined
  const points = (data?.points as Row[] | undefined) ?? []
  const candles = (data?.candles as Candle[] | undefined) ?? []
  const error = chartQuery.isError
    ? apiErrorMessage(chartQuery.error)
    : data?.error
      ? String(data.error)
      : ''

  const fullRows = useMemo(() => {
    const byT = new Map<string, Candle>()
    for (const c of candles) {
      if (c?.t) byT.set(String(c.t), c)
      if (c?.label) byT.set(String(c.label), c)
    }
    return points.map((p) => {
      const t = String(p.t ?? '')
      const label = String(p.label ?? '')
      const c = byT.get(t) || byT.get(label)
      let close = Number(c?.close ?? p.value)
      let open = Number(c?.open ?? close)
      let high = Number(c?.high ?? Math.max(open, close))
      let low = Number(c?.low ?? Math.min(open, close))
      return {
        ...p,
        open,
        high,
        low,
        close,
        value: close,
        range: [low, high] as [number, number],
        __pad: false,
      } as Row
    })
  }, [points, candles])

  const chartRows = useMemo(() => {
    const sliced = fullRows.slice(-Math.max(10, barCount))
    // Stream: update forming (last real) candle with live LTP
    const rows = sliced.map((p, idx) => {
      let close = Number(p.close)
      let open = Number(p.open)
      let high = Number(p.high)
      let low = Number(p.low)
      if (idx === sliced.length - 1 && ltp != null && Number.isFinite(ltp)) {
        close = Number(ltp)
        high = Math.max(high, close, open)
        low = Math.min(low, close, open)
      }
      return {
        ...p,
        idx,
        open,
        high,
        low,
        close,
        value: close,
        range: [low, high] as [number, number],
        __pad: false,
      } as Row
    })

    // Empty slots on the right so candles aren't glued to the edge
    for (let i = 0; i < RIGHT_PAD_BARS; i++) {
      rows.push({
        label: '',
        idx: rows.length + i,
        open: null,
        high: null,
        low: null,
        close: null,
        value: null,
        volume: null,
        range: null,
        __pad: true,
      })
    }
    return rows
  }, [fullRows, barCount, ltp])

  const realBarCount = Math.max(0, chartRows.length - RIGHT_PAD_BARS)

  const overlayKeys = useMemo(() => {
    const keys: { key: string; color: string; label: string; dash?: string }[] = []
    for (const id of ['ema_5', 'ema_9', 'ema_20', 'ema_50', 'ema_200'] as IndicatorId[]) {
      if (selected.includes(id)) {
        keys.push({ key: id, color: OVERLAY_COLORS[id], label: id.replace('_', ' ').toUpperCase() })
      }
    }
    if (selected.includes('supertrend')) {
      keys.push({ key: 'supertrend', color: OVERLAY_COLORS.supertrend, label: 'Supertrend', dash: '4 2' })
    }
    if (selected.includes('bollinger')) {
      keys.push(
        { key: 'bb_upper', color: OVERLAY_COLORS.bb_upper, label: 'BB Upper', dash: '3 3' },
        { key: 'bb_mid', color: OVERLAY_COLORS.bb_mid, label: 'BB Mid', dash: '2 2' },
        { key: 'bb_lower', color: OVERLAY_COLORS.bb_lower, label: 'BB Lower', dash: '3 3' },
      )
    }
    return keys
  }, [selected])

  const showVolume = selected.includes('volume')
  const showRsi = selected.includes('rsi')
  const hasVolumeData = useMemo(
    () => chartRows.some((p) => !p.__pad && p.volume != null && Number.isFinite(Number(p.volume)) && Number(p.volume) > 0),
    [chartRows],
  )
  const hasCandles = useMemo(
    () => chartRows.some((r) => !r.__pad && Number(r.high) !== Number(r.low) && Number.isFinite(Number(r.open))),
    [chartRows],
  )
  const effectiveStyle: ChartStyle = chartStyle === 'candles' && hasCandles ? 'candles' : 'line'

  const yDomainNums = useMemo((): [number, number] | null => {
    if (!realBarCount) return null
    const vals: number[] = []
    for (const p of chartRows) {
      if (p.__pad) continue
      if (effectiveStyle === 'candles') {
        if (Number.isFinite(Number(p.high))) vals.push(Number(p.high))
        if (Number.isFinite(Number(p.low))) vals.push(Number(p.low))
      } else if (Number.isFinite(Number(p.close))) {
        vals.push(Number(p.close))
      }
    }
    for (const sr of customSr) vals.push(sr.price)
    for (const tl of trendLines) {
      vals.push(tl.y1, tl.y2)
    }
    for (const ov of overlayKeys) {
      for (const p of chartRows) {
        if (p.__pad) continue
        const n = Number(p[ov.key])
        if (Number.isFinite(n)) vals.push(n)
      }
    }
    if (!vals.length) return null
    const lo = Math.min(...vals)
    const hi = Math.max(...vals)
    const pad = Math.max((hi - lo) * 0.06, Math.abs(hi) * 0.001, 1e-6)
    return [lo - pad, hi + pad]
  }, [chartRows, customSr, trendLines, overlayKeys, effectiveStyle, realBarCount])

  const yDomain = (yDomainNums ?? ['auto', 'auto']) as [number | string, number | string]

  const toggleIndicator = (id: IndicatorId) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const handleCreateSr = useCallback((price: number) => {
    const id = uid()
    setCustomSr((prev) => [
      ...prev,
      { id, price, label: `S/R ${fmtNum(price, price >= 100 ? 1 : 3)}` },
    ])
    setSelection({ kind: 'sr', id })
    setDrawMode('none')
  }, [])

  const handleCreateTl = useCallback((tl: Omit<TrendLine, 'id'>) => {
    const id = uid()
    setTrendLines((prev) => [...prev, { ...tl, id }])
    setSelection({ kind: 'tl', id })
    setDrawMode('none')
  }, [])

  const handleChangeSr = useCallback((id: string, price: number) => {
    setCustomSr((prev) =>
      prev.map((s) =>
        s.id === id
          ? { ...s, price, label: `S/R ${fmtNum(price, price >= 100 ? 1 : 3)}` }
          : s,
      ),
    )
  }, [])

  const handleChangeTl = useCallback((id: string, patch: Partial<TrendLine>) => {
    setTrendLines((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  }, [])

  const selectedTl = selection?.kind === 'tl' ? trendLines.find((t) => t.id === selection.id) : null

  const addManualSr = () => {
    if (manualSr === '' || !Number.isFinite(Number(manualSr))) return
    const price = Number(manualSr)
    const id = uid()
    setCustomSr((prev) => [...prev, { id, price, label: `S/R ${fmtNum(price, price >= 100 ? 1 : 3)}` }])
    setSelection({ kind: 'sr', id })
    setManualSr('')
  }

  const deleteSelected = () => {
    if (!selection) return
    if (selection.kind === 'sr') setCustomSr((prev) => prev.filter((x) => x.id !== selection.id))
    else setTrendLines((prev) => prev.filter((x) => x.id !== selection.id))
    setSelection(null)
  }

  if (!ticker.trim()) {
    return (
      <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-8 text-center text-sm text-slate-500">
        Select a ticker to load the live chart
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold text-white">{ticker}</h3>
          {ltp != null && (
            <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-sm font-medium text-emerald-300">
              LTP {fmtNum(ltp)}
              {streamOn && (
                <span className="ml-1.5 inline-flex items-center gap-1 text-[10px] text-emerald-400/80">
                  <Wifi size={10} /> live
                </span>
              )}
            </span>
          )}
          {data?.change_pct != null && (
            <span className={`text-xs ${Number(data.change_pct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {Number(data.change_pct) >= 0 ? '+' : ''}
              {fmtNum(data.change_pct, 2)}%
            </span>
          )}
          <span className="text-[11px] text-slate-500">
            showing {realBarCount} / {fullRows.length || 0} bars
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip selected={streamOn} onClick={() => setStreamOn((v) => !v)}>
            {streamOn ? 'Streaming on' : 'Streaming off'}
          </Chip>
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            Bars
            <Select
              value={String(barCount)}
              onChange={(e) => setBarCount(Number(e.target.value) || 80)}
              className="!w-auto !py-1.5 text-xs"
            >
              {BAR_COUNT_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          </label>
          <Select
            value={interval}
            onChange={(e) => setIntervalTf(e.target.value)}
            className="!w-auto !py-1.5 text-xs"
          >
            {INTERVALS.map((iv) => (
              <option key={iv.value} value={iv.value}>{iv.label}</option>
            ))}
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Chip selected={effectiveStyle === 'candles'} onClick={() => setChartStyle('candles')}>Candles</Chip>
        <Chip selected={effectiveStyle === 'line'} onClick={() => setChartStyle('line')}>Line</Chip>
        {INDICATOR_OPTIONS.map((opt) => (
          <Chip key={opt.id} selected={selected.includes(opt.id)} onClick={() => toggleIndicator(opt.id)}>
            {opt.label}
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-800/60 bg-slate-950/40 p-2.5">
        <Button
          size="sm"
          variant={drawMode === 'sr' ? 'primary' : 'secondary'}
          onClick={() => {
            setDrawMode((m) => (m === 'sr' ? 'none' : 'sr'))
            setSelection(null)
          }}
        >
          <Pencil size={14} /> Draw S/R
        </Button>
        <Button
          size="sm"
          variant={drawMode === 'trendline' ? 'primary' : 'secondary'}
          onClick={() => {
            setDrawMode((m) => (m === 'trendline' ? 'none' : 'trendline'))
            setSelection(null)
          }}
        >
          <MoveDiagonal2 size={14} /> Trendline
        </Button>
        <div className="flex items-end gap-1.5">
          <div>
            <label className="mb-1 block text-[11px] text-slate-500">S/R price</label>
            <Input
              type="number"
              className="!w-28 !py-1.5"
              value={manualSr}
              onChange={(e) => setManualSr(e.target.value === '' ? '' : parseFloat(e.target.value))}
              placeholder="Price"
            />
          </div>
          <Button size="sm" variant="secondary" onClick={addManualSr}>Add</Button>
        </div>
        {selectedTl && (
          <>
            <Chip
              selected={selectedTl.extendLeft}
              onClick={() => handleChangeTl(selectedTl.id, { extendLeft: !selectedTl.extendLeft })}
            >
              Extend ←
            </Chip>
            <Chip
              selected={selectedTl.extendRight}
              onClick={() => handleChangeTl(selectedTl.id, { extendRight: !selectedTl.extendRight })}
            >
              Extend →
            </Chip>
          </>
        )}
        {selection && (
          <Button size="sm" variant="ghost" onClick={deleteSelected}>
            <Trash2 size={14} /> Delete selected
          </Button>
        )}
        {(customSr.length > 0 || trendLines.length > 0) && (
          <Button size="sm" variant="ghost" onClick={clearDrawings}>
            <Trash2 size={14} /> Clear all
          </Button>
        )}
        {drawMode === 'sr' && (
          <span className="text-xs text-amber-300">Drag on chart to place S/R — release to lock</span>
        )}
        {drawMode === 'trendline' && (
          <span className="text-xs text-amber-300">Click-drag to draw — then drag ends to rotate / extend</span>
        )}
        {drawMode === 'none' && !selection && (customSr.length > 0 || trendLines.length > 0) && (
          <span className="text-xs text-slate-500">Click a line to select · drag body/ends · Del to remove</span>
        )}
        {selection?.kind === 'sr' && (
          <span className="text-xs text-amber-300">Drag handle / line up-down to move S/R</span>
        )}
        {selection?.kind === 'tl' && (
          <span className="text-xs text-sky-300">Drag ends to rotate/skew · middle to move · Extend ←/→</span>
        )}
      </div>

      {error && <Alert type="error">{error}</Alert>}
      {chartQuery.isLoading && !data && <Loading message="Loading chart…" />}

      {chartRows.length > 0 && (
        <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
          <div className="relative h-[380px] w-full">
            {yDomainNums && (
              <DrawingCanvas
                drawMode={drawMode}
                yMin={yDomainNums[0]}
                yMax={yDomainNums[1]}
                realBarCount={realBarCount}
                totalSlots={chartRows.length}
                customSr={customSr}
                trendLines={trendLines}
                selection={selection}
                onSelect={setSelection}
                onChangeSr={handleChangeSr}
                onChangeTl={handleChangeTl}
                onCreateSr={handleCreateSr}
                onCreateTl={handleCreateTl}
              />
            )}
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={chartRows}
                margin={{
                  top: PLOT_MARGIN.top,
                  right: PLOT_MARGIN.right,
                  left: PLOT_MARGIN.left,
                  bottom: PLOT_MARGIN.bottom,
                }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={28} />
                <YAxis
                  yAxisId="price"
                  domain={yDomain}
                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                  width={PRICE_AXIS_WIDTH}
                  tickFormatter={(v) => Number(v).toFixed(v >= 100 ? 0 : 2)}
                />
                {showVolume && hasVolumeData && (
                  <YAxis
                    yAxisId="vol"
                    orientation="right"
                    tick={{ fill: '#64748b', fontSize: 9 }}
                    width={44}
                    tickFormatter={(v) => {
                      const n = Number(v)
                      if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
                      if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`
                      return String(Math.round(n))
                    }}
                  />
                )}
                {drawMode === 'none' && !selection && (
                  <Tooltip
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    content={({ active, payload, label }: any) => {
                      if (!active || !payload?.length) return null
                      const row = payload[0]?.payload
                      if (!row || row.__pad) return null
                      return (
                        <div style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11, padding: '8px 10px' }}>
                          <p style={{ color: '#e2e8f0', marginBottom: 4 }}>{String(label)}</p>
                          {effectiveStyle === 'candles' ? (
                            <>
                              <p style={{ color: '#94a3b8' }}>O: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.open)}</span></p>
                              <p style={{ color: '#94a3b8' }}>H: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.high)}</span></p>
                              <p style={{ color: '#94a3b8' }}>L: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.low)}</span></p>
                              <p style={{ color: '#94a3b8' }}>C: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.close)}</span></p>
                            </>
                          ) : (
                            <p style={{ color: '#94a3b8' }}>Close: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.close)}</span></p>
                          )}
                          {row.volume != null && (
                            <p style={{ color: '#94a3b8' }}>Vol: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.volume, 0)}</span></p>
                          )}
                        </div>
                      )
                    }}
                  />
                )}
                {showVolume && hasVolumeData && (
                  <Bar yAxisId="vol" dataKey="volume" fill="#334155" opacity={0.55} name="volume" isAnimationActive={false} />
                )}
                {effectiveStyle === 'candles' ? (
                  <Bar yAxisId="price" dataKey="range" name="Price" shape={CandlestickShape} isAnimationActive={false} />
                ) : (
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="close"
                    stroke="#38bdf8"
                    strokeWidth={2}
                    dot={false}
                    name="Close"
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                )}
                {overlayKeys.map((ov) => (
                  <Line
                    key={ov.key}
                    yAxisId="price"
                    type="monotone"
                    dataKey={ov.key}
                    stroke={ov.color}
                    strokeWidth={ov.key.startsWith('bb_') ? 1 : 1.5}
                    strokeDasharray={ov.dash}
                    dot={false}
                    name={ov.label}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {(customSr.length > 0 || trendLines.length > 0 || overlayKeys.length > 0) && (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-800/50 pt-2 text-[11px]">
              {customSr.map((sr) => (
                <button
                  key={sr.id}
                  type="button"
                  className={`hover:text-amber-200 ${selection?.kind === 'sr' && selection.id === sr.id ? 'text-amber-200 underline' : 'text-amber-300'}`}
                  onClick={() => setSelection({ kind: 'sr', id: sr.id })}
                  onDoubleClick={() => {
                    setCustomSr((prev) => prev.filter((x) => x.id !== sr.id))
                    setSelection(null)
                  }}
                  title="Click to select · double-click to remove"
                >
                  {sr.label}
                </button>
              ))}
              {trendLines.map((tl) => (
                <button
                  key={tl.id}
                  type="button"
                  className={`hover:text-sky-200 ${selection?.kind === 'tl' && selection.id === tl.id ? 'text-sky-200 underline' : 'text-sky-300'}`}
                  onClick={() => setSelection({ kind: 'tl', id: tl.id })}
                  onDoubleClick={() => {
                    setTrendLines((prev) => prev.filter((x) => x.id !== tl.id))
                    setSelection(null)
                  }}
                  title="Click to select · double-click to remove"
                >
                  TL {fmtNum(tl.y1)}→{fmtNum(tl.y2)}
                  {(tl.extendLeft || tl.extendRight) && ' ∞'}
                </button>
              ))}
              {overlayKeys.map((ov) => (
                <span key={ov.key} style={{ color: ov.color }}>{ov.label}</span>
              ))}
            </div>
          )}

          {showRsi && (
            <div className="mt-3 rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
              <p className="mb-2 text-xs font-medium text-slate-300">RSI (14)</p>
              <div className="h-28 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartRows} margin={{ top: 8, right: 72, left: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 9 }} minTickGap={40} />
                    <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 9 }} width={36} />
                    <ReferenceLine y={70} stroke="#f87171" strokeDasharray="4 3" />
                    <ReferenceLine y={30} stroke="#34d399" strokeDasharray="4 3" />
                    <Line type="monotone" dataKey="rsi" stroke="#c084fc" strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}

      {!chartQuery.isLoading && chartRows.length === 0 && !error && (
        <p className="py-6 text-center text-sm text-slate-500">No bars available for this ticker / interval</p>
      )}
    </div>
  )
}
