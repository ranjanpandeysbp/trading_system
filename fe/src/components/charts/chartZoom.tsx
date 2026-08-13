import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from 'react'
import { Copy, Maximize2, Minimize2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'
import { Chip } from '../ui/Chip'

const MIN_BARS = 12

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n))
}

/** Index-window zoom for OHLC series (TradingView-like zoom in/out). */
export function useIndexZoom(totalLength: number, minBars = MIN_BARS) {
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null)

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
    if (next >= len - 1) {
      setZoomRange(null)
      return
    }
    const mid = (a + b) / 2
    const start = clamp(Math.round(mid - next / 2), 0, len - next)
    setZoomRange([start, start + next - 1])
  }, [totalLength, zoomRange])

  const resetZoom = useCallback(() => setZoomRange(null), [])

  return {
    zoomRange,
    setZoomRange,
    zoomIn,
    zoomOut,
    resetZoom,
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
    </div>
  )
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
  // Dark background so copied chart isn't transparent on white paste targets
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
