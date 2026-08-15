import { useEffect, useMemo, useState } from 'react'
import type { PlotInsets } from './ChartDrawingLayer'

/** Viewport width under this is treated as mobile for chart axis packing. */
export const CHART_NARROW_BREAKPOINT = 640

export type ChartPlotMargin = {
  top: number
  right: number
  left: number
  bottom: number
}

export type ChartAxisLayout = {
  narrow: boolean
  margin: ChartPlotMargin
  /** Left (or primary) price Y-axis width in px */
  priceAxisWidth: number
  /** Right secondary axis (volume / dual scale) width */
  secondaryAxisWidth: number
  /** RSI / MACD / oscillator axis width */
  oscAxisWidth: number
  tickFontSize: number
  minTickGap: number
  /** Drawing overlay insets for a left price axis only */
  plotInsets: PlotInsets
  /** Drawing overlay when a right secondary axis is also shown */
  plotInsetsWithRightAxis: PlotInsets
  /** Compact tick formatter for crowded mobile axes */
  compactTick: (v: number) => string
}

function compactTick(v: number): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  const a = Math.abs(n)
  if (a >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (a >= 1e4) return `${(n / 1e3).toFixed(0)}K`
  if (a >= 100) return String(Math.round(n))
  if (a >= 10) return n.toFixed(1)
  return n.toFixed(2)
}

export function useNarrowChart(breakpointPx = CHART_NARROW_BREAKPOINT): boolean {
  const [narrow, setNarrow] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.innerWidth < breakpointPx
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia(`(max-width: ${breakpointPx - 1}px)`)
    const apply = () => setNarrow(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [breakpointPx])

  return narrow
}

/**
 * Shared Recharts margin + Y-axis widths.
 * On mobile, axes hug the edges with minimal width so the plot uses max horizontal space.
 */
export function useChartAxisLayout(options?: {
  breakpointPx?: number
  /** Extra bottom margin (e.g. for X-axis labels) */
  bottomPad?: number
  /** Desktop left margin (inside plot, before axis) */
  desktopLeftMargin?: number
  desktopRightMargin?: number
  desktopPriceAxisWidth?: number
  desktopSecondaryAxisWidth?: number
}): ChartAxisLayout {
  const narrow = useNarrowChart(options?.breakpointPx)
  const bottomPad = options?.bottomPad ?? 4
  const dLeft = options?.desktopLeftMargin ?? 4
  const dRight = options?.desktopRightMargin ?? 12
  const dPrice = options?.desktopPriceAxisWidth ?? 56
  const dSec = options?.desktopSecondaryAxisWidth ?? 44

  return useMemo(() => {
    if (narrow) {
      const margin: ChartPlotMargin = { top: 4, right: 0, left: 0, bottom: bottomPad }
      const priceAxisWidth = 26
      const secondaryAxisWidth = 0
      const oscAxisWidth = 22
      return {
        narrow: true,
        margin,
        priceAxisWidth,
        secondaryAxisWidth,
        oscAxisWidth,
        tickFontSize: 8,
        minTickGap: 48,
        plotInsets: {
          top: margin.top,
          right: margin.right,
          bottom: Math.max(margin.bottom, 20),
          left: margin.left + priceAxisWidth,
        },
        plotInsetsWithRightAxis: {
          top: margin.top,
          right: margin.right + secondaryAxisWidth,
          bottom: Math.max(margin.bottom, 20),
          left: margin.left + priceAxisWidth,
        },
        compactTick,
      }
    }

    const margin: ChartPlotMargin = {
      top: 8,
      right: dRight,
      left: dLeft,
      bottom: bottomPad,
    }
    return {
      narrow: false,
      margin,
      priceAxisWidth: dPrice,
      secondaryAxisWidth: dSec,
      oscAxisWidth: 36,
      tickFontSize: 10,
      minTickGap: 36,
      plotInsets: {
        top: margin.top,
        right: margin.right,
        bottom: Math.max(margin.bottom, 28),
        left: margin.left + dPrice,
      },
      plotInsetsWithRightAxis: {
        top: margin.top,
        right: margin.right + dSec,
        bottom: Math.max(margin.bottom, 28),
        left: margin.left + dPrice,
      },
      compactTick,
    }
  }, [narrow, bottomPad, dLeft, dRight, dPrice, dSec])
}
