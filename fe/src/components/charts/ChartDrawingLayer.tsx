import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import {
  ArrowRightFromLine,
  Crosshair,
  Minus,
  MoveDiagonal2,
  SeparatorVertical,
  Spline,
  Square,
  Trash2,
} from 'lucide-react'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'

/* ─── Types ─────────────────────────────────────────────────────────────── */

export type DrawTool = 'select' | 'hline' | 'hray' | 'vline' | 'trend' | 'fib' | 'rect'

export type PlotInsets = {
  top: number
  right: number
  bottom: number
  left: number
}

type DrawingBase = { id: string; color?: string }

export type HLineDrawing = DrawingBase & { kind: 'hline'; price: number }
export type HRayDrawing = DrawingBase & { kind: 'hray'; x: number; price: number }
export type VLineDrawing = DrawingBase & { kind: 'vline'; x: number }
export type TrendDrawing = DrawingBase & {
  kind: 'trend'
  x1: number
  y1: number
  x2: number
  y2: number
  extendLeft: boolean
  extendRight: boolean
}
export type FibDrawing = DrawingBase & {
  kind: 'fib'
  x1: number
  y1: number
  x2: number
  y2: number
  extendLeft: boolean
  extendRight: boolean
}
export type RectDrawing = DrawingBase & {
  kind: 'rect'
  x1: number
  y1: number
  x2: number
  y2: number
}

export type ChartDrawing =
  | HLineDrawing
  | HRayDrawing
  | VLineDrawing
  | TrendDrawing
  | FibDrawing
  | RectDrawing

export const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const

const HIT_TOL = 8
const DEFAULT_COLORS: Record<ChartDrawing['kind'], string> = {
  hline: '#fbbf24',
  hray: '#38bdf8',
  vline: '#a78bfa',
  trend: '#22d3ee',
  fib: '#f472b6',
  rect: '#34d399',
}

const FIB_LEVEL_COLORS = [
  '#94a3b8', // 0
  '#f472b6', // 0.236
  '#a78bfa', // 0.382
  '#38bdf8', // 0.5
  '#fbbf24', // 0.618
  '#fb923c', // 0.786
  '#94a3b8', // 1
]

type PlotGeom = {
  left: number
  top: number
  width: number
  height: number
  yMin: number
  yMax: number
  nSlots: number
}

type DragSession =
  | { type: 'create'; tool: Exclude<DrawTool, 'select'>; x1: number; y1: number; x2: number; y2: number }
  | { type: 'move'; id: string; startX: number; startY: number; snapshot: ChartDrawing }
  | { type: 'handle'; id: string; kind: ChartDrawing['kind']; handle: 'p1' | 'p2' | 'price' | 'x' }

/* ─── Helpers ───────────────────────────────────────────────────────────── */

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n))
}

function drawingColor(d: ChartDrawing): string {
  return d.color ?? DEFAULT_COLORS[d.kind]
}

function fmtPrice(n: number): string {
  if (!Number.isFinite(n)) return '—'
  const abs = Math.abs(n)
  const digits = abs >= 1000 ? 2 : abs >= 10 ? 2 : abs >= 1 ? 3 : 4
  return n.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function toSvg(geom: PlotGeom, xIdx: number, price: number): { x: number; y: number } {
  const { left, top, width, height, yMin, yMax, nSlots } = geom
  const plotW = width
  const plotH = height
  const sx = left + (nSlots <= 1 ? 0 : (xIdx / Math.max(nSlots - 1, 1)) * plotW)
  const sy = top + ((yMax - price) / (yMax - yMin || 1)) * plotH
  return { x: sx, y: sy }
}

function fromClient(
  rect: DOMRect,
  insets: PlotInsets,
  clientX: number,
  clientY: number,
  yMin: number,
  yMax: number,
  nSlots: number,
): { x: number; price: number; px: number; py: number } | null {
  const plotW = rect.width - insets.left - insets.right
  const plotH = rect.height - insets.top - insets.bottom
  if (plotW <= 0 || plotH <= 0 || !(yMax > yMin) || nSlots < 1) return null
  const px = clientX - rect.left - insets.left
  const py = clientY - rect.top - insets.top
  const price = yMax - (py / plotH) * (yMax - yMin)
  const x = nSlots <= 1 ? 0 : (px / plotW) * (nSlots - 1)
  return { x, price, px, py }
}

function clampX(x: number, nSlots: number): number {
  return clamp(x, -0.5, Math.max(nSlots - 1, 0))
}

/** Clip infinite/extended line to plot rectangle (Liang–Barsky on t). */
function clipLineToPlot(
  geom: PlotGeom,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  extendLeft: boolean,
  extendRight: boolean,
): { x1: number; y1: number; x2: number; y2: number } | null {
  const a = toSvg(geom, x1, y1)
  const b = toSvg(geom, x2, y2)
  const dx = b.x - a.x
  const dy = b.y - a.y
  if (Math.abs(dx) < 1e-6 && Math.abs(dy) < 1e-6) {
    return { x1: a.x, y1: a.y, x2: b.x, y2: b.y }
  }

  const left = geom.left
  const right = geom.left + geom.width
  const top = geom.top
  const bottom = geom.top + geom.height

  let tMin = extendLeft ? -1e6 : 0
  let tMax = extendRight ? 1e6 : 1

  const clipT = (p: number, q: number, t0: number, t1: number): [number, number] | null => {
    if (Math.abs(p) < 1e-12) {
      if (q < 0) return null
      return [t0, t1]
    }
    const r = q / p
    if (p < 0) {
      if (r > t1) return null
      return [Math.max(t0, r), t1]
    }
    if (r < t0) return null
    return [t0, Math.min(t1, r)]
  }

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

function distPointToRayRight(
  px: number,
  py: number,
  ox: number,
  oy: number,
  xMax: number,
): number {
  if (px < ox - HIT_TOL) return Infinity
  const x2 = Math.max(ox, xMax)
  return distPointToSeg(px, py, ox, oy, x2, oy)
}

function fibPrice(y1: number, y2: number, ratio: number): number {
  return y1 + (y2 - y1) * ratio
}

function createDrawingFromDrag(
  tool: Exclude<DrawTool, 'select'>,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): ChartDrawing {
  const id = uid()
  switch (tool) {
    case 'hline':
      return { id, kind: 'hline', price: y2 }
    case 'hray':
      return { id, kind: 'hray', x: x1, price: y2 }
    case 'vline':
      return { id, kind: 'vline', x: x2 }
    case 'trend':
      return {
        id,
        kind: 'trend',
        x1,
        y1,
        x2,
        y2,
        extendLeft: false,
        extendRight: false,
      }
    case 'fib':
      return {
        id,
        kind: 'fib',
        x1,
        y1,
        x2,
        y2,
        extendLeft: false,
        extendRight: true,
      }
    case 'rect':
      return { id, kind: 'rect', x1, y1, x2, y2 }
  }
}

function significantMove(
  tool: Exclude<DrawTool, 'select'>,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  yMin: number,
  yMax: number,
): boolean {
  const priceEps = Math.abs(yMax - yMin) * 0.002
  if (tool === 'hline' || tool === 'hray') return true
  if (tool === 'vline') return Math.abs(x2 - x1) > 0.02
  return Math.hypot(x2 - x1, y2 - y1) > 0.15 || Math.abs(y2 - y1) > priceEps
}

/* ─── Hook ──────────────────────────────────────────────────────────────── */

export function useChartDrawings() {
  const [tool, setTool] = useState<DrawTool>('select')
  const [drawings, setDrawings] = useState<ChartDrawing[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const clear = useCallback(() => {
    setDrawings([])
    setSelectedId(null)
  }, [])

  const removeSelected = useCallback(() => {
    if (!selectedId) return
    setDrawings((prev) => prev.filter((d) => d.id !== selectedId))
    setSelectedId(null)
  }, [selectedId])

  const patch = useCallback((id: string, partial: Partial<ChartDrawing>) => {
    setDrawings((prev) =>
      prev.map((d) => {
        if (d.id !== id) return d
        return { ...d, ...partial } as ChartDrawing
      }),
    )
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return

      if (e.key === 'Escape') {
        setSelectedId(null)
        setTool('select')
        return
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) {
        e.preventDefault()
        setDrawings((prev) => prev.filter((d) => d.id !== selectedId))
        setSelectedId(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId])

  return {
    tool,
    drawings,
    selectedId,
    clear,
    removeSelected,
    patch,
    setTool,
    setSelectedId,
    setDrawings,
  }
}

/* ─── Toolbar ───────────────────────────────────────────────────────────── */

const TOOL_BUTTONS: {
  id: DrawTool
  label: string
  icon: typeof Crosshair
  title: string
}[] = [
  { id: 'select', label: 'Select', icon: Crosshair, title: 'Select / move' },
  { id: 'hline', label: 'H-Line', icon: Minus, title: 'Horizontal line' },
  { id: 'hray', label: 'H-Ray', icon: ArrowRightFromLine, title: 'Horizontal ray' },
  { id: 'vline', label: 'V-Line', icon: SeparatorVertical, title: 'Vertical line' },
  { id: 'trend', label: 'Trend', icon: MoveDiagonal2, title: 'Trend line' },
  { id: 'fib', label: 'Fib', icon: Spline, title: 'Fibonacci retracement' },
  { id: 'rect', label: 'Rect', icon: Square, title: 'Rectangle zone' },
]

export function ChartDrawingToolbar({
  tool,
  setTool,
  selectedId,
  drawings,
  patch,
  removeSelected,
  clear,
  orientation = 'horizontal',
}: {
  tool: DrawTool
  setTool: (t: DrawTool) => void
  selectedId: string | null
  drawings: ChartDrawing[]
  patch: (id: string, partial: Partial<ChartDrawing>) => void
  removeSelected: () => void
  clear: () => void
  orientation?: 'horizontal' | 'vertical'
}) {
  const selected = selectedId ? drawings.find((d) => d.id === selectedId) : null
  const canExtend =
    selected != null && (selected.kind === 'trend' || selected.kind === 'fib')
  const vertical = orientation === 'vertical'

  return (
    <div className={vertical ? 'flex flex-col items-stretch gap-1' : 'flex flex-wrap items-center gap-1.5'}>
      {TOOL_BUTTONS.map((t) => {
        const Icon = t.icon
        return (
          <Chip
            key={t.id}
            selected={tool === t.id}
            onClick={() => setTool(t.id)}
            title={t.title}
          >
            <span className={`inline-flex items-center ${vertical ? 'justify-center' : 'gap-1'}`}>
              <Icon size={13} />
              {!vertical && t.label}
            </span>
          </Chip>
        )
      })}

      {canExtend && selected && (selected.kind === 'trend' || selected.kind === 'fib') && (
        <>
          <Chip
            selected={selected.extendLeft}
            onClick={() => patch(selected.id, { extendLeft: !selected.extendLeft })}
            title="Extend left"
          >
            {vertical ? '←' : 'Extend←'}
          </Chip>
          <Chip
            selected={selected.extendRight}
            onClick={() => patch(selected.id, { extendRight: !selected.extendRight })}
            title="Extend right"
          >
            {vertical ? '→' : 'Extend→'}
          </Chip>
        </>
      )}

      <Button
        size="sm"
        variant="ghost"
        disabled={!selectedId}
        onClick={removeSelected}
        title="Delete selected"
        className={vertical ? '!px-2' : undefined}
      >
        <Trash2 size={14} />
        {!vertical && 'Delete'}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={drawings.length === 0}
        onClick={clear}
        title="Clear all drawings"
        className={vertical ? '!px-2' : undefined}
      >
        {!vertical && 'Clear'}
        {vertical && <span className="text-[10px]">Clr</span>}
      </Button>

      {!vertical && (
        <span className="ml-1 text-[11px] text-slate-500">
          {tool === 'select'
            ? 'Click to select · drag handles · Esc deselect · Del remove'
            : tool === 'fib'
              ? 'Click-drag from swing high → low (or reverse)'
              : tool === 'trend' || tool === 'rect'
                ? 'Click-drag to place'
                : tool === 'hline' || tool === 'hray'
                  ? 'Click (or drag) at price level'
                  : 'Click (or drag) to place'}
        </span>
      )}
    </div>
  )
}

/* ─── Layer ─────────────────────────────────────────────────────────────── */

export function ChartDrawingLayer({
  insets,
  yMin,
  yMax,
  nSlots,
  drawings,
  selectedId,
  tool,
  onSelect,
  onChange,
  setTool,
}: {
  insets: PlotInsets
  yMin: number
  yMax: number
  nSlots: number
  drawings: ChartDrawing[]
  selectedId: string | null
  tool: DrawTool
  onSelect: (id: string | null) => void
  onChange: (next: ChartDrawing[] | ((prev: ChartDrawing[]) => ChartDrawing[])) => void
  setTool: (t: DrawTool) => void
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
    if (size.w < 40 || size.h < 40 || !(yMax > yMin) || nSlots < 1) return null
    const width = size.w - insets.left - insets.right
    const height = size.h - insets.top - insets.bottom
    if (width <= 0 || height <= 0) return null
    return {
      left: insets.left,
      top: insets.top,
      width,
      height,
      yMin,
      yMax,
      nSlots,
    }
  }, [size, yMin, yMax, nSlots, insets.left, insets.right, insets.top, insets.bottom])

  const readPlot = useCallback(
    (clientX: number, clientY: number) => {
      const el = rootRef.current
      if (!el || !geom) return null
      return fromClient(el.getBoundingClientRect(), insets, clientX, clientY, yMin, yMax, nSlots)
    },
    [geom, insets, yMin, yMax, nSlots],
  )

  const updateDrawing = useCallback(
    (id: string, updater: (d: ChartDrawing) => ChartDrawing) => {
      onChange((prev) => prev.map((d) => (d.id === id ? updater(d) : d)))
    },
    [onChange],
  )

  const hitTest = useCallback(
    (clientX: number, clientY: number): { id: string; handle?: 'p1' | 'p2' | 'price' | 'x' } | null => {
      if (!geom) return null
      const el = rootRef.current
      if (!el) return null
      const rect = el.getBoundingClientRect()
      const px = clientX - rect.left
      const py = clientY - rect.top

      const selected = selectedId ? drawings.find((d) => d.id === selectedId) : null
      if (selected) {
        if (selected.kind === 'trend' || selected.kind === 'fib' || selected.kind === 'rect') {
          const p1 = toSvg(geom, selected.x1, selected.y1)
          const p2 = toSvg(geom, selected.x2, selected.y2)
          if (Math.hypot(px - p1.x, py - p1.y) <= HIT_TOL + 2) return { id: selected.id, handle: 'p1' }
          if (Math.hypot(px - p2.x, py - p2.y) <= HIT_TOL + 2) return { id: selected.id, handle: 'p2' }
        }
        if (selected.kind === 'hline' || selected.kind === 'hray') {
          const midX =
            selected.kind === 'hray'
              ? toSvg(geom, selected.x, selected.price).x
              : geom.left + geom.width / 2
          const y = toSvg(geom, 0, selected.price).y
          if (Math.hypot(px - midX, py - y) <= HIT_TOL + 2) return { id: selected.id, handle: 'price' }
        }
        if (selected.kind === 'vline') {
          const x = toSvg(geom, selected.x, (yMin + yMax) / 2).x
          const midY = geom.top + geom.height / 2
          if (Math.hypot(px - x, py - midY) <= HIT_TOL + 2) return { id: selected.id, handle: 'x' }
        }
      }

      for (const d of [...drawings].reverse()) {
        if (d.kind === 'hline') {
          const y = toSvg(geom, 0, d.price).y
          if (
            Math.abs(py - y) <= HIT_TOL &&
            px >= geom.left &&
            px <= geom.left + geom.width
          ) {
            return { id: d.id }
          }
        } else if (d.kind === 'hray') {
          const p = toSvg(geom, d.x, d.price)
          if (distPointToRayRight(px, py, p.x, p.y, geom.left + geom.width) <= HIT_TOL) {
            return { id: d.id }
          }
        } else if (d.kind === 'vline') {
          const x = toSvg(geom, d.x, (yMin + yMax) / 2).x
          if (
            Math.abs(px - x) <= HIT_TOL &&
            py >= geom.top &&
            py <= geom.top + geom.height
          ) {
            return { id: d.id }
          }
        } else if (d.kind === 'trend') {
          const clipped = clipLineToPlot(geom, d.x1, d.y1, d.x2, d.y2, d.extendLeft, d.extendRight)
          if (clipped && distPointToSeg(px, py, clipped.x1, clipped.y1, clipped.x2, clipped.y2) <= HIT_TOL) {
            return { id: d.id }
          }
        } else if (d.kind === 'fib') {
          const xL = Math.min(toSvg(geom, d.x1, d.y1).x, toSvg(geom, d.x2, d.y2).x)
          const xR = Math.max(toSvg(geom, d.x1, d.y1).x, toSvg(geom, d.x2, d.y2).x)
          const left = d.extendLeft ? geom.left : xL
          const right = d.extendRight ? geom.left + geom.width : xR
          for (const ratio of FIB_RATIOS) {
            const price = fibPrice(d.y1, d.y2, ratio)
            const y = toSvg(geom, 0, price).y
            if (Math.abs(py - y) <= HIT_TOL && px >= left - 2 && px <= right + 2) {
              return { id: d.id }
            }
          }
          const p1 = toSvg(geom, d.x1, d.y1)
          const p2 = toSvg(geom, d.x2, d.y2)
          if (distPointToSeg(px, py, p1.x, p1.y, p2.x, p2.y) <= HIT_TOL) return { id: d.id }
        } else if (d.kind === 'rect') {
          const a = toSvg(geom, d.x1, d.y1)
          const b = toSvg(geom, d.x2, d.y2)
          const minX = Math.min(a.x, b.x)
          const maxX = Math.max(a.x, b.x)
          const minY = Math.min(a.y, b.y)
          const maxY = Math.max(a.y, b.y)
          const inside = px >= minX && px <= maxX && py >= minY && py <= maxY
          const nearEdge =
            (Math.abs(px - minX) <= HIT_TOL || Math.abs(px - maxX) <= HIT_TOL) &&
            py >= minY - HIT_TOL &&
            py <= maxY + HIT_TOL
          const nearHoriz =
            (Math.abs(py - minY) <= HIT_TOL || Math.abs(py - maxY) <= HIT_TOL) &&
            px >= minX - HIT_TOL &&
            px <= maxX + HIT_TOL
          if (inside || nearEdge || nearHoriz) return { id: d.id }
        }
      }
      return null
    },
    [geom, drawings, selectedId, yMin, yMax],
  )

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) {
        if (tool === 'select') {
          const hit = hitTest(e.clientX, e.clientY)
          setHoverId(hit?.id ?? null)
        }
        return
      }
      const pt = readPlot(e.clientX, e.clientY)
      if (!pt) return
      const xClamped = clampX(pt.x, nSlots)

      if (d.type === 'create') {
        setDrag({ ...d, x2: xClamped, y2: pt.price })
        return
      }

      if (d.type === 'handle') {
        updateDrawing(d.id, (cur) => {
          if (cur.kind === 'hline' && d.handle === 'price') {
            return { ...cur, price: pt.price }
          }
          if (cur.kind === 'hray') {
            if (d.handle === 'price') return { ...cur, price: pt.price, x: xClamped }
            return cur
          }
          if (cur.kind === 'vline' && d.handle === 'x') {
            return { ...cur, x: xClamped }
          }
          if (
            (cur.kind === 'trend' || cur.kind === 'fib' || cur.kind === 'rect') &&
            (d.handle === 'p1' || d.handle === 'p2')
          ) {
            if (d.handle === 'p1') return { ...cur, x1: xClamped, y1: pt.price }
            return { ...cur, x2: xClamped, y2: pt.price }
          }
          return cur
        })
        return
      }

      if (d.type === 'move') {
        const dx = xClamped - d.startX
        const dy = pt.price - d.startY
        const snap = d.snapshot
        updateDrawing(d.id, () => {
          if (snap.kind === 'hline') {
            return { ...snap, price: snap.price + dy }
          }
          if (snap.kind === 'hray') {
            return { ...snap, x: clampX(snap.x + dx, nSlots), price: snap.price + dy }
          }
          if (snap.kind === 'vline') {
            return { ...snap, x: clampX(snap.x + dx, nSlots) }
          }
          if (snap.kind === 'trend' || snap.kind === 'fib' || snap.kind === 'rect') {
            return {
              ...snap,
              x1: clampX(snap.x1 + dx, nSlots),
              y1: snap.y1 + dy,
              x2: clampX(snap.x2 + dx, nSlots),
              y2: snap.y2 + dy,
            }
          }
          return snap
        })
      }
    }

    const onUp = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) return
      const pt = readPlot(e.clientX, e.clientY)

      if (d.type === 'create') {
        const x2 = pt ? clampX(pt.x, nSlots) : d.x2
        const y2 = pt?.price ?? d.y2
        if (significantMove(d.tool, d.x1, d.y1, x2, y2, yMin, yMax)) {
          const created = createDrawingFromDrag(d.tool, d.x1, d.y1, x2, y2)
          onChange((prev) => [...prev, created])
          onSelect(created.id)
          setTool('select')
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
  }, [tool, hitTest, readPlot, nSlots, yMin, yMax, onChange, onSelect, setTool, updateDrawing])

  const onPointerDown = (e: ReactPointerEvent) => {
    if (!geom) return
    const pt = readPlot(e.clientX, e.clientY)
    if (!pt) return
    if (pt.px < -4 || pt.py < -4 || pt.px > geom.width + 4 || pt.py > geom.height + 4) {
      if (tool === 'select') onSelect(null)
      return
    }
    e.preventDefault()
    e.stopPropagation()

    if (tool !== 'select') {
      onSelect(null)
      const x = clampX(pt.x, nSlots)
      setDrag({
        type: 'create',
        tool,
        x1: x,
        y1: pt.price,
        x2: x,
        y2: pt.price,
      })
      return
    }

    const hit = hitTest(e.clientX, e.clientY)
    if (!hit) {
      onSelect(null)
      return
    }
    onSelect(hit.id)
    const drawing = drawings.find((d) => d.id === hit.id)
    if (!drawing) return

    if (hit.handle) {
      setDrag({ type: 'handle', id: drawing.id, kind: drawing.kind, handle: hit.handle })
      return
    }

    // Detect handle near endpoints even if hitTest didn't tag it (fresh select)
    const el = rootRef.current
    if (el && (drawing.kind === 'trend' || drawing.kind === 'fib' || drawing.kind === 'rect')) {
      const rect = el.getBoundingClientRect()
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top
      const p1 = toSvg(geom, drawing.x1, drawing.y1)
      const p2 = toSvg(geom, drawing.x2, drawing.y2)
      if (Math.hypot(px - p1.x, py - p1.y) <= 10) {
        setDrag({ type: 'handle', id: drawing.id, kind: drawing.kind, handle: 'p1' })
        return
      }
      if (Math.hypot(px - p2.x, py - p2.y) <= 10) {
        setDrag({ type: 'handle', id: drawing.id, kind: drawing.kind, handle: 'p2' })
        return
      }
    }

    setDrag({
      type: 'move',
      id: drawing.id,
      startX: clampX(pt.x, nSlots),
      startY: pt.price,
      snapshot: { ...drawing },
    })
  }

  if (!(yMax > yMin) || nSlots < 1 || !geom) {
    return <div ref={rootRef} className="absolute inset-0 z-20 pointer-events-none" />
  }

  const creating = tool !== 'select'
  const cursor = creating ? 'crosshair' : hoverId ? 'move' : 'default'
  const captureAll = creating || !!drag
  const preview = drag?.type === 'create' ? drag : null

  return (
    <div
      ref={rootRef}
      className="absolute inset-0 z-20"
      style={{ cursor, pointerEvents: captureAll ? 'auto' : 'none' }}
      onPointerDown={captureAll ? onPointerDown : undefined}
      onPointerLeave={() => setHoverId(null)}
    >
      {/* Wide transparent hit targets when not creating so chart tooltips still work */}
      {!captureAll && drawings.length > 0 && (
        <svg
          width={size.w}
          height={size.h}
          className="absolute inset-0 overflow-visible"
          style={{ pointerEvents: 'none' }}
        >
          {drawings.map((d) => (
            <HitShape
              key={`hit-${d.id}`}
              d={d}
              geom={geom}
              selected={selectedId === d.id}
              onPointerDown={onPointerDown}
            />
          ))}
        </svg>
      )}

      <svg
        width={size.w}
        height={size.h}
        className="absolute inset-0 overflow-visible"
        style={{ pointerEvents: 'none' }}
      >
        {drawings.map((d) => (
          <DrawingShape
            key={d.id}
            d={d}
            geom={geom}
            selected={selectedId === d.id}
            hot={hoverId === d.id || selectedId === d.id}
          />
        ))}

        {preview && (
          <PreviewShape preview={preview} geom={geom} />
        )}
      </svg>
    </div>
  )
}

/* ─── Render helpers ────────────────────────────────────────────────────── */

function Handle({
  x,
  y,
  color,
}: {
  x: number
  y: number
  color: string
}) {
  return (
    <circle
      cx={x}
      cy={y}
      r={5}
      fill="#0f172a"
      stroke={color}
      strokeWidth={2}
    />
  )
}

function HitShape({
  d,
  geom,
  selected,
  onPointerDown,
}: {
  d: ChartDrawing
  geom: PlotGeom
  selected: boolean
  onPointerDown: (e: ReactPointerEvent) => void
}) {
  const color = 'transparent'
  if (d.kind === 'hline') {
    const y = toSvg(geom, 0, d.price).y
    return (
      <g>
        <line
          x1={geom.left}
          y1={y}
          x2={geom.left + geom.width}
          y2={y}
          stroke={color}
          strokeWidth={14}
          style={{ pointerEvents: 'stroke', cursor: 'ns-resize' }}
          onPointerDown={onPointerDown}
        />
        {selected && (
          <circle
            cx={geom.left + geom.width / 2}
            cy={y}
            r={10}
            fill="transparent"
            style={{ pointerEvents: 'all', cursor: 'ns-resize' }}
            onPointerDown={onPointerDown}
          />
        )}
      </g>
    )
  }
  if (d.kind === 'hray') {
    const p = toSvg(geom, d.x, d.price)
    return (
      <g>
        <line
          x1={p.x}
          y1={p.y}
          x2={geom.left + geom.width}
          y2={p.y}
          stroke={color}
          strokeWidth={14}
          style={{ pointerEvents: 'stroke', cursor: 'move' }}
          onPointerDown={onPointerDown}
        />
        {selected && (
          <circle
            cx={p.x}
            cy={p.y}
            r={10}
            fill="transparent"
            style={{ pointerEvents: 'all', cursor: 'grab' }}
            onPointerDown={onPointerDown}
          />
        )}
      </g>
    )
  }
  if (d.kind === 'vline') {
    const x = toSvg(geom, d.x, (geom.yMin + geom.yMax) / 2).x
    return (
      <g>
        <line
          x1={x}
          y1={geom.top}
          x2={x}
          y2={geom.top + geom.height}
          stroke={color}
          strokeWidth={14}
          style={{ pointerEvents: 'stroke', cursor: 'ew-resize' }}
          onPointerDown={onPointerDown}
        />
        {selected && (
          <circle
            cx={x}
            cy={geom.top + geom.height / 2}
            r={10}
            fill="transparent"
            style={{ pointerEvents: 'all', cursor: 'ew-resize' }}
            onPointerDown={onPointerDown}
          />
        )}
      </g>
    )
  }
  if (d.kind === 'trend') {
    const clipped = clipLineToPlot(geom, d.x1, d.y1, d.x2, d.y2, d.extendLeft, d.extendRight)
    if (!clipped) return null
    const p1 = toSvg(geom, d.x1, d.y1)
    const p2 = toSvg(geom, d.x2, d.y2)
    return (
      <g>
        <line
          x1={clipped.x1}
          y1={clipped.y1}
          x2={clipped.x2}
          y2={clipped.y2}
          stroke={color}
          strokeWidth={14}
          style={{ pointerEvents: 'stroke', cursor: 'move' }}
          onPointerDown={onPointerDown}
        />
        {selected && (
          <>
            <circle cx={p1.x} cy={p1.y} r={10} fill="transparent" style={{ pointerEvents: 'all', cursor: 'grab' }} onPointerDown={onPointerDown} />
            <circle cx={p2.x} cy={p2.y} r={10} fill="transparent" style={{ pointerEvents: 'all', cursor: 'grab' }} onPointerDown={onPointerDown} />
          </>
        )}
      </g>
    )
  }
  if (d.kind === 'fib') {
    const p1 = toSvg(geom, d.x1, d.y1)
    const p2 = toSvg(geom, d.x2, d.y2)
    const xL = Math.min(p1.x, p2.x)
    const xR = Math.max(p1.x, p2.x)
    const left = d.extendLeft ? geom.left : xL
    const right = d.extendRight ? geom.left + geom.width : xR
    return (
      <g>
        {FIB_RATIOS.map((ratio) => {
          const y = toSvg(geom, 0, fibPrice(d.y1, d.y2, ratio)).y
          return (
            <line
              key={ratio}
              x1={left}
              y1={y}
              x2={right}
              y2={y}
              stroke={color}
              strokeWidth={14}
              style={{ pointerEvents: 'stroke', cursor: 'move' }}
              onPointerDown={onPointerDown}
            />
          )
        })}
        {selected && (
          <>
            <circle cx={p1.x} cy={p1.y} r={10} fill="transparent" style={{ pointerEvents: 'all', cursor: 'grab' }} onPointerDown={onPointerDown} />
            <circle cx={p2.x} cy={p2.y} r={10} fill="transparent" style={{ pointerEvents: 'all', cursor: 'grab' }} onPointerDown={onPointerDown} />
          </>
        )}
      </g>
    )
  }
  // rect
  const a = toSvg(geom, d.x1, d.y1)
  const b = toSvg(geom, d.x2, d.y2)
  const x = Math.min(a.x, b.x)
  const y = Math.min(a.y, b.y)
  const w = Math.abs(b.x - a.x)
  const h = Math.abs(b.y - a.y)
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={Math.max(w, 1)}
        height={Math.max(h, 1)}
        fill="transparent"
        stroke={color}
        strokeWidth={14}
        style={{ pointerEvents: 'all', cursor: 'move' }}
        onPointerDown={onPointerDown}
      />
      {selected && (
        <>
          <circle cx={a.x} cy={a.y} r={10} fill="transparent" style={{ pointerEvents: 'all', cursor: 'grab' }} onPointerDown={onPointerDown} />
          <circle cx={b.x} cy={b.y} r={10} fill="transparent" style={{ pointerEvents: 'all', cursor: 'grab' }} onPointerDown={onPointerDown} />
        </>
      )}
    </g>
  )
}

function DrawingShape({
  d,
  geom,
  selected,
  hot,
}: {
  d: ChartDrawing
  geom: PlotGeom
  selected: boolean
  hot: boolean
}) {
  const color = drawingColor(d)
  const sw = hot ? 2 : 1.5

  if (d.kind === 'hline') {
    const y = toSvg(geom, 0, d.price).y
    return (
      <g>
        <line
          x1={geom.left}
          y1={y}
          x2={geom.left + geom.width}
          y2={y}
          stroke={color}
          strokeWidth={sw}
          strokeDasharray="6 3"
        />
        <text
          x={geom.left + geom.width - 4}
          y={y - 4}
          fill={color}
          fontSize={10}
          textAnchor="end"
          style={{ userSelect: 'none' }}
        >
          {fmtPrice(d.price)}
        </text>
        {selected && <Handle x={geom.left + geom.width / 2} y={y} color={color} />}
      </g>
    )
  }

  if (d.kind === 'hray') {
    const p = toSvg(geom, d.x, d.price)
    return (
      <g>
        <line
          x1={p.x}
          y1={p.y}
          x2={geom.left + geom.width}
          y2={p.y}
          stroke={color}
          strokeWidth={sw}
        />
        <text
          x={geom.left + geom.width - 4}
          y={p.y - 4}
          fill={color}
          fontSize={10}
          textAnchor="end"
          style={{ userSelect: 'none' }}
        >
          {fmtPrice(d.price)}
        </text>
        {selected && <Handle x={p.x} y={p.y} color={color} />}
      </g>
    )
  }

  if (d.kind === 'vline') {
    const x = toSvg(geom, d.x, (geom.yMin + geom.yMax) / 2).x
    return (
      <g>
        <line
          x1={x}
          y1={geom.top}
          x2={x}
          y2={geom.top + geom.height}
          stroke={color}
          strokeWidth={sw}
          strokeDasharray="4 3"
        />
        {selected && <Handle x={x} y={geom.top + geom.height / 2} color={color} />}
      </g>
    )
  }

  if (d.kind === 'trend') {
    const clipped = clipLineToPlot(geom, d.x1, d.y1, d.x2, d.y2, d.extendLeft, d.extendRight)
    if (!clipped) return null
    const p1 = toSvg(geom, d.x1, d.y1)
    const p2 = toSvg(geom, d.x2, d.y2)
    return (
      <g>
        <line
          x1={clipped.x1}
          y1={clipped.y1}
          x2={clipped.x2}
          y2={clipped.y2}
          stroke={color}
          strokeWidth={sw}
        />
        {selected && (
          <>
            <Handle x={p1.x} y={p1.y} color={color} />
            <Handle x={p2.x} y={p2.y} color={color} />
          </>
        )}
      </g>
    )
  }

  if (d.kind === 'fib') {
    const p1 = toSvg(geom, d.x1, d.y1)
    const p2 = toSvg(geom, d.x2, d.y2)
    const xL = Math.min(p1.x, p2.x)
    const xR = Math.max(p1.x, p2.x)
    const left = d.extendLeft ? geom.left : xL
    const right = d.extendRight ? geom.left + geom.width : xR
    return (
      <g>
        <line
          x1={p1.x}
          y1={p1.y}
          x2={p2.x}
          y2={p2.y}
          stroke={color}
          strokeWidth={1}
          strokeOpacity={0.5}
          strokeDasharray="3 3"
        />
        {FIB_RATIOS.map((ratio, i) => {
          const price = fibPrice(d.y1, d.y2, ratio)
          const y = toSvg(geom, 0, price).y
          const lvlColor = FIB_LEVEL_COLORS[i] ?? color
          const pct = `${(ratio * 100).toFixed(ratio === 0 || ratio === 1 || ratio === 0.5 ? 0 : 1)}%`
          // soft fill between consecutive levels
          const next = FIB_RATIOS[i + 1]
          let band: ReactNode = null
          if (next != null) {
            const y2 = toSvg(geom, 0, fibPrice(d.y1, d.y2, next)).y
            const top = Math.min(y, y2)
            const h = Math.abs(y2 - y)
            band = (
              <rect
                x={left}
                y={top}
                width={Math.max(right - left, 0)}
                height={h}
                fill={lvlColor}
                fillOpacity={0.06}
              />
            )
          }
          return (
            <g key={ratio}>
              {band}
              <line
                x1={left}
                y1={y}
                x2={right}
                y2={y}
                stroke={lvlColor}
                strokeWidth={hot && (ratio === 0 || ratio === 1 || ratio === 0.618) ? 1.75 : 1.25}
              />
              <text
                x={right - 4}
                y={y - 3}
                fill={lvlColor}
                fontSize={10}
                textAnchor="end"
                style={{ userSelect: 'none' }}
              >
                {pct} ({fmtPrice(price)})
              </text>
            </g>
          )
        })}
        {selected && (
          <>
            <Handle x={p1.x} y={p1.y} color={color} />
            <Handle x={p2.x} y={p2.y} color={color} />
          </>
        )}
      </g>
    )
  }

  // rect
  const a = toSvg(geom, d.x1, d.y1)
  const b = toSvg(geom, d.x2, d.y2)
  const x = Math.min(a.x, b.x)
  const y = Math.min(a.y, b.y)
  const w = Math.abs(b.x - a.x)
  const h = Math.abs(b.y - a.y)
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={Math.max(w, 1)}
        height={Math.max(h, 1)}
        fill={color}
        fillOpacity={0.12}
        stroke={color}
        strokeWidth={sw}
      />
      {selected && (
        <>
          <Handle x={a.x} y={a.y} color={color} />
          <Handle x={b.x} y={b.y} color={color} />
        </>
      )}
    </g>
  )
}

function PreviewShape({
  preview,
  geom,
}: {
  preview: Extract<DragSession, { type: 'create' }>
  geom: PlotGeom
}) {
  const draft = createDrawingFromDrag(preview.tool, preview.x1, preview.y1, preview.x2, preview.y2)
  return <DrawingShape d={draft} geom={geom} selected={false} hot />
}
