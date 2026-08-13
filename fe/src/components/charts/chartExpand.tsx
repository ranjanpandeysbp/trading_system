import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Maximize2, Minimize2, X } from 'lucide-react'
import { Chip } from '../ui/Chip'

export type ChartSizeMode = 'normal' | 'large' | 'xl'

const SIZE_META: Record<
  ChartSizeMode,
  { label: string; /** Tailwind height when inline */ heightClass: string; title: string }
> = {
  normal: { label: 'Normal', heightClass: 'h-72', title: 'Default chart height' },
  large: { label: 'Large', heightClass: 'h-[min(70vh,560px)] min-h-[360px]', title: 'Taller chart for analysis' },
  xl: { label: 'XL', heightClass: 'h-[min(85vh,720px)] min-h-[420px]', title: 'Extra tall chart' },
}

export function useChartExpand(defaultSize: ChartSizeMode = 'normal') {
  const [size, setSize] = useState<ChartSizeMode>(defaultSize)
  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    if (!fullscreen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [fullscreen])

  const heightClass = fullscreen
    ? 'h-[calc(100dvh-7.5rem)] min-h-[280px] sm:h-[calc(100dvh-6.5rem)]'
    : SIZE_META[size].heightClass

  return {
    size,
    setSize,
    fullscreen,
    setFullscreen,
    toggleFullscreen: () => setFullscreen((v) => !v),
    heightClass,
    sizeLabel: SIZE_META[size].label,
  }
}

export type ChartExpandApi = ReturnType<typeof useChartExpand>

/** Size presets + fullscreen toggle for chart toolbars. */
export function ChartExpandControls({
  size,
  setSize,
  fullscreen,
  setFullscreen,
}: {
  size: ChartSizeMode
  setSize: (s: ChartSizeMode) => void
  fullscreen: boolean
  setFullscreen: (v: boolean | ((p: boolean) => boolean)) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {(['normal', 'large', 'xl'] as ChartSizeMode[]).map((s) => (
        <Chip
          key={s}
          selected={!fullscreen && size === s}
          title={SIZE_META[s].title}
          onClick={() => {
            setSize(s)
            setFullscreen(false)
          }}
        >
          {SIZE_META[s].label}
        </Chip>
      ))}
      <Chip
        selected={fullscreen}
        title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen — biggest view on desktop & mobile'}
        onClick={() => setFullscreen((v) => !v)}
      >
        <span className="inline-flex items-center gap-1">
          {fullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
          {fullscreen ? 'Exit' : 'Fullscreen'}
        </span>
      </Chip>
    </div>
  )
}

/**
 * When fullscreen, portals children into a fixed viewport overlay.
 * Keep a single chart instance (pass the same tree as children).
 */
export function ChartExpandFrame({
  fullscreen,
  onClose,
  title = 'Chart',
  children,
}: {
  fullscreen: boolean
  onClose: () => void
  title?: string
  children: ReactNode
}) {
  if (!fullscreen) return <>{children}</>

  return createPortal(
    <div className="fixed inset-0 z-[200] flex flex-col bg-slate-950/98 backdrop-blur-sm">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-800/80 px-3 py-2 sm:px-4">
        <p className="truncate text-sm font-medium text-slate-200">{title}</p>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-300 hover:border-slate-500 hover:text-white"
          title="Exit fullscreen (Esc)"
        >
          <X size={14} />
          Close
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-2 sm:p-3">{children}</div>
    </div>,
    document.body,
  )
}
