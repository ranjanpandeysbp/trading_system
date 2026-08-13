import { useState } from 'react'
import { Chip } from '../ui/Chip'

export type ChartIndicatorId =
  | 'rsi'
  | 'supertrend'
  | 'volume'
  | 'bollinger'
  | 'ema_5'
  | 'ema_9'
  | 'ema_20'
  | 'ema_50'
  | 'ema_200'

export const CHART_INDICATOR_OPTIONS: { id: ChartIndicatorId; label: string }[] = [
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

export const DEFAULT_CHART_INDICATORS: ChartIndicatorId[] = [
  'volume',
  'ema_9',
  'ema_20',
  'bollinger',
  'rsi',
]

export const INDICATOR_COLORS: Record<string, string> = {
  ema_5: '#fbbf24',
  ema_9: '#a78bfa',
  ema_20: '#34d399',
  ema_50: '#fb923c',
  ema_200: '#f472b6',
  supertrend: '#22d3ee',
  bb_upper: '#64748b',
  bb_mid: '#94a3b8',
  bb_lower: '#64748b',
  rsi: '#c084fc',
}

type NumBar = {
  open: number
  high: number
  low: number
  close: number
  volume?: number | null
}

function emaSeries(closes: number[], period: number): (number | null)[] {
  const out: (number | null)[] = closes.map(() => null)
  if (closes.length < period) return out
  const k = 2 / (period + 1)
  let prev = 0
  for (let i = 0; i < period; i++) prev += closes[i]
  prev /= period
  out[period - 1] = prev
  for (let i = period; i < closes.length; i++) {
    prev = closes[i] * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

function rsiSeries(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = closes.map(() => null)
  if (closes.length <= period) return out
  let gain = 0
  let loss = 0
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1]
    if (d >= 0) gain += d
    else loss -= d
  }
  let avgGain = gain / period
  let avgLoss = loss / period
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    const g = d > 0 ? d : 0
    const l = d < 0 ? -d : 0
    avgGain = (avgGain * (period - 1) + g) / period
    avgLoss = (avgLoss * (period - 1) + l) / period
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
  }
  return out
}

function bollingerSeries(closes: number[], period = 20, mult = 2) {
  const upper: (number | null)[] = closes.map(() => null)
  const mid: (number | null)[] = closes.map(() => null)
  const lower: (number | null)[] = closes.map(() => null)
  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1)
    const mean = slice.reduce((a, b) => a + b, 0) / period
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period
    const sd = Math.sqrt(variance)
    mid[i] = mean
    upper[i] = mean + mult * sd
    lower[i] = mean - mult * sd
  }
  return { upper, mid, lower }
}

/** ATR(period) Wilder smoothing + classic Supertrend(10, 3). */
function supertrendSeries(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 10,
  mult = 3,
): (number | null)[] {
  const n = closes.length
  const out: (number | null)[] = closes.map(() => null)
  if (n <= period) return out

  const tr: number[] = [Math.max(highs[0] - lows[0], 0)]
  for (let i = 1; i < n; i++) {
    tr.push(
      Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1]),
      ),
    )
  }

  const atr: (number | null)[] = tr.map(() => null)
  let sum = 0
  for (let i = 0; i < period; i++) sum += tr[i]
  atr[period - 1] = sum / period
  for (let i = period; i < n; i++) {
    atr[i] = ((atr[i - 1] as number) * (period - 1) + tr[i]) / period
  }

  let finalUpper = 0
  let finalLower = 0
  let dir = 1
  for (let i = period - 1; i < n; i++) {
    const a = atr[i] as number
    const hl2 = (highs[i] + lows[i]) / 2
    const basicUpper = hl2 + mult * a
    const basicLower = hl2 - mult * a
    if (i === period - 1) {
      finalUpper = basicUpper
      finalLower = basicLower
      dir = closes[i] >= finalLower ? 1 : -1
    } else {
      finalUpper = basicUpper < finalUpper || closes[i - 1] > finalUpper ? basicUpper : finalUpper
      finalLower = basicLower > finalLower || closes[i - 1] < finalLower ? basicLower : finalLower
      if (dir === 1) {
        dir = closes[i] < finalLower ? -1 : 1
      } else {
        dir = closes[i] > finalUpper ? 1 : -1
      }
    }
    out[i] = dir === 1 ? finalLower : finalUpper
  }
  return out
}

/** Attach indicator columns onto OHLC bars (null until warm-up). */
export function enrichBarsWithIndicators<T extends NumBar>(
  bars: T[],
): Array<T & Record<string, number | null>> {
  if (!bars.length) return []
  const closes = bars.map((b) => Number(b.close))
  const highs = bars.map((b) => Number(b.high))
  const lows = bars.map((b) => Number(b.low))
  const ema5 = emaSeries(closes, 5)
  const ema9 = emaSeries(closes, 9)
  const ema20 = emaSeries(closes, 20)
  const ema50 = emaSeries(closes, 50)
  const ema200 = emaSeries(closes, 200)
  const rsi = rsiSeries(closes, 14)
  const bb = bollingerSeries(closes, 20, 2)
  const st = supertrendSeries(highs, lows, closes, 10, 3)

  return bars.map((b, i) => ({
    ...b,
    ema_5: ema5[i],
    ema_9: ema9[i],
    ema_20: ema20[i],
    ema_50: ema50[i],
    ema_200: ema200[i],
    rsi: rsi[i],
    bb_upper: bb.upper[i],
    bb_mid: bb.mid[i],
    bb_lower: bb.lower[i],
    supertrend: st[i],
  }))
}

export function useChartIndicators(defaultSelected: ChartIndicatorId[] = DEFAULT_CHART_INDICATORS) {
  const [selected, setSelected] = useState<ChartIndicatorId[]>(defaultSelected)
  const toggle = (id: ChartIndicatorId) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }
  return { selected, setSelected, toggle }
}

/** Candles / Line + indicator chips. */
export function ChartStyleIndicatorControls({
  chartType,
  setChartType,
  selected,
  toggle,
}: {
  chartType: 'candles' | 'line'
  setChartType: (t: 'candles' | 'line') => void
  selected: ChartIndicatorId[]
  toggle: (id: ChartIndicatorId) => void
}) {
  return (
    <>
      <Chip selected={chartType === 'candles'} onClick={() => setChartType('candles')}>
        Candles
      </Chip>
      <Chip selected={chartType === 'line'} onClick={() => setChartType('line')}>
        Line
      </Chip>
      {CHART_INDICATOR_OPTIONS.map((opt) => (
        <Chip key={opt.id} selected={selected.includes(opt.id)} onClick={() => toggle(opt.id)}>
          {opt.label}
        </Chip>
      ))}
    </>
  )
}

export function overlayKeysFor(selected: ChartIndicatorId[]) {
  const keys: { key: string; color: string; label: string; dash?: string }[] = []
  for (const id of ['ema_5', 'ema_9', 'ema_20', 'ema_50', 'ema_200'] as ChartIndicatorId[]) {
    if (selected.includes(id)) {
      keys.push({ key: id, color: INDICATOR_COLORS[id], label: id.replace('_', ' ').toUpperCase() })
    }
  }
  if (selected.includes('supertrend')) {
    keys.push({ key: 'supertrend', color: INDICATOR_COLORS.supertrend, label: 'Supertrend', dash: '4 2' })
  }
  if (selected.includes('bollinger')) {
    keys.push(
      { key: 'bb_upper', color: INDICATOR_COLORS.bb_upper, label: 'BB Upper', dash: '3 3' },
      { key: 'bb_mid', color: INDICATOR_COLORS.bb_mid, label: 'BB Mid', dash: '2 2' },
      { key: 'bb_lower', color: INDICATOR_COLORS.bb_lower, label: 'BB Lower', dash: '3 3' },
    )
  }
  return keys
}
