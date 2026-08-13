import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from 'react'
import { Copy, HandGrab, Maximize2, Minimize2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'
import { Chip } from '../ui/Chip'

const MIN_BARS = 12

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n))
}

/** Index-window zoom for OHLC series (TradingView-like zoom in/out + pan). */
export function useIndexZoom(totalLength: number, minBars = MIN_BARS) {
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null)
  const panFracRef = useRef(0)

  // Keep range valid when data length changes
  useEffect(() => {
    if (!zoomRange) return
    if (totalLength <= minBars) {
      setZoomRange(null)
      return
    }
    const [a, b] = zoomRange
    if (a >= totalLength || b >= totalLength) {
      setZoomRange(null)
    }
  }, [totalLength, zoomRange, minBars])

  const zoomIn = useCallback(() => {
    const len = totalLength
    if (len <= minBars) return
    panFracRef.current = 0
    if (!zoomRange) {
      const span = Math.max(minBars, Math.floor(len * 0.55))
      const start = Math.max(0, len - span)
      setZoomRange([start, len - 1])
      return
    }
    const [a, b] = zoomRange
    const span = b - a + 1
    if (span <= minBars) return
    const next = Math.max(minBars, Math.floor(span * 0.65))
    const mid = (a + b) / 2
    const start = clamp(Math.round(mid - next / 2), 0, len - next)
    setZoomRange([start, start + next - 1])
  }, [totalLength, zoomRange, minBars])

  const zoomOut = useCallback(() => {
    if (!zoomRange) return
    const len = totalLength
    const [a, b] = zoomRange
    const span = b - a + 1
    const next = Math.min(len, Math.ceil(span * 1.55))
    panFracRef.current = 0
    if (next >= len - 1) {
      setZoomRange(null)
      return
    }
    const mid = (a + b) / 2
    const start = clamp(Math.round(mid - next / 2), 0, len - next)
    setZoomRange([start, start + next - 1])
  }, [totalLength, zoomRange])

  const resetZoom = useCallback(() => {
    panFracRef.current = 0
    setZoomRange(null)
  }, [])

  /** Drag right → older bars (indices decrease). Accepts fractional bar deltas. */
  const panBy = useCallback(
    (deltaBars: number) => {
      const len = totalLength
      if (len <= minBars || !Number.isFinite(deltaBars) || deltaBars === 0) return

      panFracRef.current += deltaBars
      const shift = Math.trunc(panFracRef.current)
      if (shift === 0) return
      panFracRef.current -= shift

      let a: number
      let b: number
      if (!zoomRange) {
        const span = Math.max(minBars, Math.floor(len * 0.55))
        a = Math.max(0, len - span)
        b = len - 1
      } else {
        ;[a, b] = zoomRange
      }
      const span = b - a + 1
      const start = clamp(a - shift, 0, Math.max(0, len - span))
      setZoomRange([start, start + span - 1])
    },
    [totalLength, zoomRange, minBars],
  )

  return {
    zoomRange,
    setZoomRange,
    zoomIn,
    zoomOut,
    resetZoom,
    panBy,
    isZoomed: zoomRange != null,
  }
}

export function ChartZoomControls({
  onZoomIn,
  onZoomOut,
  onReset,
  isZoomed,
}: {
  onZoomIn: () => void
  onZoomOut: () => void
  onReset: () => void
  isZoomed?: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Chip selected={false} title="Zoom in" onClick={onZoomIn}>
        <span className="inline-flex items-center gap-1">
          <ZoomIn size={12} /> In
        </span>
      </Chip>
      <Chip selected={false} title="Zoom out" onClick={onZoomOut}>
        <span className="inline-flex items-center gap-1">
          <ZoomOut size={12} /> Out
        </span>
      </Chip>
      <Chip
        selected={Boolean(isZoomed)}
        title="Reset zoom to full range"
        onClick={onReset}
      >
        <span className="inline-flex items-center gap-1">
          <RotateCcw size={12} /> Reset zoom
        </span>
      </Chip>
      <span
        className="inline-flex items-center gap-1 rounded-full border border-slate-800/80 px-2 py-0.5 text-[10px] text-slate-500"
        title="Hold and drag the chart left/right to pan. Shift+drag also pans."
      >
        <HandGrab size={11} /> Drag to pan
      </span>
    </div>
  )
}

/**
 * Hold + drag horizontally to pan the visible bar window.
 * - primaryPan: left-drag always pans (auto-zooms into a window if needed)
 * - otherwise: pans when already zoomed, or with Shift / middle mouse
 */
export function useChartPanDrag(
  chartRef: RefObject<HTMLElement | null>,
  opts: {
    enabled?: boolean
    totalLength: number
    zoomRange: [number, number] | null
    panBy: (deltaBars: number) => void
    /** When true, plain left-drag pans (Price / Paper / Oil charts). */
    primaryPan?: boolean
  },
) {
  const { enabled = true, totalLength, zoomRange, panBy, primaryPan = false } = opts
  const panByRef = useRef(panBy)
  panByRef.current = panBy
  const zoomRangeRef = useRef(zoomRange)
  zoomRangeRef.current = zoomRange
  const primaryPanRef = useRef(primaryPan)
  primaryPanRef.current = primaryPan
  const totalLengthRef = useRef(totalLength)
  totalLengthRef.current = totalLength

  useEffect(() => {
    const el = chartRef.current
    if (!el || !enabled) return

    let active = false
    let panning = false
    let startX = 0
    let lastX = 0
    let pointerId: number | null = null
    const prevCursor = el.style.cursor

    const visibleBars = () => {
      const zr = zoomRangeRef.current
      const len = totalLengthRef.current
      if (zr) return Math.max(1, zr[1] - zr[0] + 1)
      return Math.max(1, Math.floor(len * 0.55))
    }

    const canStartPan = (e: PointerEvent) => {
      if (e.button === 1) return true // middle mouse
      if (e.button !== 0) return false
      if (e.shiftKey) return true
      if (primaryPanRef.current) return true
      if (zoomRangeRef.current != null) return true
      return false
    }

    const onDown = (e: PointerEvent) => {
      if (!canStartPan(e)) return
      const t = e.target as HTMLElement | null
      if (t?.closest('button, input, select, textarea, a')) return
      active = true
      panning = false
      startX = e.clientX
      lastX = e.clientX
      pointerId = e.pointerId
      try {
        el.setPointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
    }

    const onMove = (e: PointerEvent) => {
      if (!active) return
      if (!panning) {
        if (Math.abs(e.clientX - startX) < 5) return
        panning = true
        el.style.cursor = 'grabbing'
        el.classList.add('select-none')
      }
      const dx = e.clientX - lastX
      lastX = e.clientX
      if (dx === 0) return
      const w = Math.max(1, el.getBoundingClientRect().width)
      const deltaBars = (dx / w) * visibleBars()
      panByRef.current(deltaBars)
      e.preventDefault()
    }

    const onUp = (e: PointerEvent) => {
      if (!active) return
      active = false
      panning = false
      el.style.cursor = primaryPanRef.current || zoomRangeRef.current ? 'grab' : prevCursor
      el.classList.remove('select-none')
      if (pointerId != null) {
        try {
          el.releasePointerCapture(pointerId)
        } catch {
          /* ignore */
        }
      }
      pointerId = null
      if (e.button === 1) e.preventDefault()
    }

    el.style.cursor = primaryPan || zoomRange ? 'grab' : prevCursor
    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
    el.addEventListener('lostpointercapture', onUp)
    const onAux = (e: MouseEvent) => {
      if (e.button === 1) e.preventDefault()
    }
    el.addEventListener('auxclick', onAux)
    el.addEventListener('mousedown', onAux)

    return () => {
      el.style.cursor = prevCursor
      el.classList.remove('select-none')
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
      el.removeEventListener('lostpointercapture', onUp)
      el.removeEventListener('auxclick', onAux)
      el.removeEventListener('mousedown', onAux)
    }
  }, [chartRef, enabled, primaryPan, zoomRange])
}

/** Serialize chart SVG → PNG blob for clipboard / download. */
export async function chartElementToPngBlob(root: HTMLElement): Promise<Blob | null> {
  const svg = root.querySelector('svg')
  if (!svg) return null
  const rect = svg.getBoundingClientRect()
  const w = Math.max(1, Math.round(rect.width))
  const h = Math.max(1, Math.round(rect.height))
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(w))
  clone.setAttribute('height', String(h))
  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
  bg.setAttribute('width', '100%')
  bg.setAttribute('height', '100%')
  bg.setAttribute('fill', '#0f172a')
  clone.insertBefore(bg, clone.firstChild)

  const xml = new XMLSerializer().serializeToString(clone)
  const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }))
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const i = new Image()
      i.onload = () => resolve(i)
      i.onerror = reject
      i.src = url
    })
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.fillStyle = '#0f172a'
    ctx.fillRect(0, 0, w, h)
    ctx.drawImage(img, 0, 0, w, h)
    return await new Promise<Blob | null>((resolve) => canvas.toBlob((b) => resolve(b), 'image/png'))
  } catch {
    return null
  } finally {
    URL.revokeObjectURL(url)
  }
}

export async function copyChartImage(root: HTMLElement | null): Promise<'ok' | 'denied' | 'fail'> {
  if (!root) return 'fail'
  const blob = await chartElementToPngBlob(root)
  if (!blob) return 'fail'
  try {
    if (navigator.clipboard && 'ClipboardItem' in window) {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      return 'ok'
    }
  } catch {
    /* fall through to download */
  }
  try {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `chart-${Date.now()}.png`
    a.click()
    URL.revokeObjectURL(a.href)
    return 'ok'
  } catch {
    return 'fail'
  }
}

type MenuState = { x: number; y: number } | null

export function useChartContextMenu() {
  const [menu, setMenu] = useState<MenuState>(null)
  const openAt = useCallback((clientX: number, clientY: number) => {
    setMenu({ x: clientX, y: clientY })
  }, [])
  const close = useCallback(() => setMenu(null), [])

  useEffect(() => {
    if (!menu) return
    const onDown = () => setMenu(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(null)
    }
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [menu])

  return { menu, openAt, close }
}

export function ChartContextMenu({
  menu,
  onClose,
  onCopy,
  onResetZoom,
  onFullscreen,
  fullscreen,
  onResetChart,
}: {
  menu: MenuState
  onClose: () => void
  onCopy: () => void
  onResetZoom: () => void
  onFullscreen: () => void
  fullscreen: boolean
  onResetChart?: () => void
}) {
  if (!menu) return null
  const style: CSSProperties = {
    position: 'fixed',
    left: Math.min(menu.x, window.innerWidth - 220),
    top: Math.min(menu.y, window.innerHeight - 220),
    zIndex: 300,
  }
  const Item = ({
    label,
    icon,
    onClick,
  }: {
    label: string
    icon: ReactNode
    onClick: () => void
  }) => (
    <button
      type="button"
      className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-200 hover:bg-slate-800"
      onClick={(e) => {
        e.stopPropagation()
        onClick()
        onClose()
      }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {icon}
      {label}
    </button>
  )

  return (
    <div
      style={style}
      className="min-w-[200px] overflow-hidden rounded-lg border border-slate-700 bg-slate-900 shadow-xl shadow-black/40"
      role="menu"
    >
      <p className="border-b border-slate-800 px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
        Chart
      </p>
      <Item label="Copy chart" icon={<Copy size={13} className="text-slate-400" />} onClick={onCopy} />
      <Item label="Reset zoom" icon={<RotateCcw size={13} className="text-slate-400" />} onClick={onResetZoom} />
      <Item
        label={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        icon={fullscreen ? <Minimize2 size={13} className="text-slate-400" /> : <Maximize2 size={13} className="text-slate-400" />}
        onClick={onFullscreen}
      />
      {onResetChart && (
        <Item
          label="Reset chart to full view"
          icon={<RotateCcw size={13} className="text-amber-400/80" />}
          onClick={onResetChart}
        />
      )}
    </div>
  )
}

/** Attach right-click + ctrl/cmd+wheel zoom helpers to a chart container. */
export function useChartPointerZoom(
  chartRef: RefObject<HTMLElement | null>,
  zoomIn: () => void,
  zoomOut: () => void,
  openMenu: (x: number, y: number) => void,
) {
  const zoomInRef = useRef(zoomIn)
  const zoomOutRef = useRef(zoomOut)
  const openMenuRef = useRef(openMenu)
  zoomInRef.current = zoomIn
  zoomOutRef.current = zoomOut
  openMenuRef.current = openMenu

  useEffect(() => {
    const el = chartRef.current
    if (!el) return
    const onCtx = (e: MouseEvent) => {
      e.preventDefault()
      openMenuRef.current(e.clientX, e.clientY)
    }
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      e.preventDefault()
      if (e.deltaY < 0) zoomInRef.current()
      else zoomOutRef.current()
    }
    el.addEventListener('contextmenu', onCtx)
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      el.removeEventListener('contextmenu', onCtx)
      el.removeEventListener('wheel', onWheel)
    }
  }, [chartRef])
}
