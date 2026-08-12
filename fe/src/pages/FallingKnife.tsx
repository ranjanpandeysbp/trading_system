import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { TrendingDown } from 'lucide-react'
import {
  apiErrorMessage,
  fetchFallingKnifeSession,
  runFallingKnifeScan,
} from '../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, Td, Th } from '../components/ui/Table'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'
import { VolumeProfileChart, type VpChartBar } from '../components/pro-trade/VolumeProfileChart'
import { TradeSetupBanner, tradeSetupFromResult } from '../components/pro-trade/TradeSetupBanner'
import { FallRiseForecastCards, forecastFromResult } from '../components/pro-trade/FallRiseForecastCards'
import { UseAiCheckbox, useTradeSetupAi } from '../components/pro-trade/UseAiCheckbox'
import { tickerDisplayLabel, tickerNameOnly } from '../components/ui/tickerDisplay'

type Row = Record<string, unknown>

const ASSET_CLASSES: { id: AssetClass; label: string }[] = [
  { id: 'india', label: 'India' },
  { id: 'us', label: 'US' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'commodity', label: 'Commodities' },
]

const HOW_TO = `Falling Knife — How to

Live scan
1. Pick asset class + universe.
2. Set threshold % and lookback hours.
3. Choose Falls / Rises / Both (default: both).
   · Fall = last price ≥ X% below the window high
   · Rise = last price ≥ X% above the window low
4. Scan uses only that market’s session hours.
5. Each ticker also gets Fall/Rise next-move forecasts (Conf %, next time, move %, SL %, TP %)
   from ~90d daily history — same cards as History mode.

History & forecast
1. Switch to History mode.
2. Set from/to dates, threshold % (X), and Fall / Rise / Both.
3. For each ticker you get every past move ≥ X%, event datetime, gap to next move,
   hours/days to recover back to the start of that pump/dump, plus a next-event
   forecast (datetime, confidence %, typical move %, SL %, TP %).

From top (loop hours)
1. Switch to From top mode.
2. Set fall threshold % (X) and Loop hours.
3. Finds names currently ≥ X% below their high in that loop window.
4. For each match: chance of reverse vs continued fall (from similar historical
   drawdowns), expected bounce % if it reverses, further-fall % if it continues,
   and a confidence score.

Sessions
· India — Mon–Fri 09:15–15:30 IST
· US — Mon–Fri 09:30–16:00 America/New_York
· Crypto — 24×7
· Commodities — ~24×5 futures (Sun–Fri ET)

Educational only — not a buy/sell signal.

Trade setup
· Live: matched falls → mean-reversion BUY (knife catch); rises → SELL fade.
· History: next-event forecast includes % confidence, %SL, and %TP (ATR-sane).
· From top: reverse bias → long bounce; continue bias → short fade (when clear).
· Always shown as Conf % · SL % · TP %.
· Optional Use AI checkbox: after the rule-based scan, AI re-scores Conf/SL/TP
  and reverse/continue odds (falls back to rules if no API key).`

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function fmtSignedPct(v: unknown, digits = 2) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

function changeClass(v: unknown) {
  const n = Number(v)
  if (!Number.isFinite(n)) return 'text-slate-400'
  if (n > 0.05) return 'font-medium text-emerald-300'
  if (n < -0.05) return 'font-medium text-rose-300'
  return 'text-slate-400'
}

function fmtPx(v: unknown, assetClass: AssetClass) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const prefix = assetClass === 'india' ? '₹' : assetClass === 'crypto' ? '' : '$'
  return `${prefix}${n.toLocaleString(undefined, { maximumFractionDigits: 4 })}`
}

function fmtWhen(v: unknown) {
  if (v == null || v === '') return '—'
  const s = String(v)
  if (s.includes('IST')) return s
  return s.replace('T', ' ').slice(0, 16)
}

function fmtForecastWhen(f: Row | null | undefined) {
  if (!f) return '—'
  if (f.predicted_next_time_ist) return String(f.predicted_next_time_ist)
  return fmtWhen(f.predicted_next_time)
}

function defaultFromDate(daysBack = 90) {
  const d = new Date()
  d.setDate(d.getDate() - daysBack)
  return d.toISOString().slice(0, 10)
}

function toVpBars(raw: unknown): VpChartBar[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((b) => {
      const row = b as Row
      const open = Number(row.open)
      const high = Number(row.high)
      const low = Number(row.low)
      const close = Number(row.close)
      if (![open, high, low, close].every(Number.isFinite)) return null
      return {
        time: String(row.time ?? row.label ?? ''),
        open,
        high,
        low,
        close,
        volume: row.volume != null && Number.isFinite(Number(row.volume)) ? Number(row.volume) : null,
      } as VpChartBar
    })
    .filter((b): b is VpChartBar => Boolean(b && b.time))
}

function HistoryTickerCard({ row, assetClass }: { row: Row; assetClass: AssetClass }) {
  const [open, setOpen] = useState(false)
  const events = (row.events as Row[] | undefined) ?? []
  const forecast = (row.forecast as Row | undefined) ?? {}
  const primary = (row.primary_forecast as Row | undefined) ?? null
  const chartBars = useMemo(() => toVpBars(row.chart_data), [row.chart_data])
  const tradeSetup = useMemo(() => {
    const fromRow = tradeSetupFromResult(row)
    if (fromRow) return fromRow
    if (primary) return tradeSetupFromResult(primary)
    return null
  }, [row, primary])

  return (
    <div className="rounded-xl border border-slate-800/70 bg-slate-950/40">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">
              {tickerNameOnly(row) || String(row.ticker)}
            </span>
            {tickerNameOnly(row) && (
              <span className="text-[10px] text-slate-500">{String(row.ticker)}</span>
            )}
            <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] text-rose-300">
              {String(row.fall_count ?? 0)} falls
            </span>
            <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-300">
              {String(row.rise_count ?? 0)} rises
            </span>
            {primary != null && (
              <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-300">
                Next {String(primary.direction)} · {String(primary.confidence_pct)}% conf
              </span>
            )}
            {tradeSetup?.sl_pct != null && tradeSetup?.tp_pct != null && (
              <span className="rounded bg-slate-700/40 px-1.5 py-0.5 text-[10px] text-slate-300">
                SL {fmtNum(tradeSetup.sl_pct, 1)}% · TP {fmtNum(tradeSetup.tp_pct, 1)}%
              </span>
            )}
          </div>
          {row.error ? (
            <p className="mt-1 text-xs text-amber-400">{String(row.error)}</p>
          ) : primary != null ? (
            <p className="mt-1 text-xs text-slate-400">
              Predicted {String(primary.direction)} around{' '}
              <span className="text-slate-200">{fmtForecastWhen(primary)}</span>
              {primary.hours_until_label != null ? (
                <span className="text-slate-500"> · in {String(primary.hours_until_label)}</span>
              ) : null}
              {' · move '}
              <span className={changeClass(primary.predicted_move_pct)}>
                {fmtSignedPct(primary.predicted_move_pct)}
              </span>
              {Number(primary.cycles_skipped) > 0 ? (
                <span className="text-amber-400/90">
                  {' '}
                  · rolled +{String(primary.cycles_skipped)} past cycle
                  {Number(primary.cycles_skipped) === 1 ? '' : 's'}
                </span>
              ) : null}
              {primary.median_recovery_label != null
                ? ` · typical recovery ${String(primary.median_recovery_label)}`
                : ''}
            </p>
          ) : (
            <p className="mt-1 text-xs text-slate-500">No forecast yet — need more historical events.</p>
          )}
        </div>
        <span className="shrink-0 text-slate-500">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-800/60 px-4 py-3">
          {tradeSetup && <TradeSetupBanner setup={tradeSetup} />}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg bg-slate-900/50 p-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Last</p>
              <p className="mt-1 text-sm text-white">{fmtPx(row.last, assetClass)}</p>
              <p className="text-[11px] text-slate-500">{fmtWhen(row.range_end)}</p>
            </div>
            <div className="rounded-lg bg-slate-900/50 p-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Avg fall / rise</p>
              <p className="mt-1 text-sm">
                <span className="text-rose-300">−{fmtNum(row.avg_fall_pct)}%</span>
                {' / '}
                <span className="text-emerald-300">+{fmtNum(row.avg_rise_pct)}%</span>
              </p>
            </div>
            <div className="rounded-lg bg-slate-900/50 p-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Median recovery</p>
              <p className="mt-1 text-xs text-slate-300">
                Fall: {String(row.avg_fall_recovery_label ?? '—')}
              </p>
              <p className="text-xs text-slate-300">Rise: {String(row.avg_rise_recovery_label ?? '—')}</p>
            </div>
            <div className="rounded-lg bg-slate-900/50 p-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Bars in range</p>
              <p className="mt-1 text-sm text-white">{String(row.bars_in_range ?? '—')}</p>
              <p className="text-[11px] text-slate-500">{String(row.interval ?? '')}</p>
            </div>
          </div>

          <FallRiseForecastCards forecast={forecast} />

          {chartBars.length > 0 && (
            <VolumeProfileChart
              chartData={chartBars}
              readingGuide="Toggle Candles / Line above the chart. Session OHLC for this ticker over the selected history window."
            />
          )}

          {!events.length ? (
            <p className="text-sm text-slate-500">No threshold events in this date range.</p>
          ) : (
            <DataTable title={`Events (${events.length})`}>
              <thead>
                <tr>
                  <Th>#</Th>
                  <Th>Side</Th>
                  <Th>Event time</Th>
                  <Th>Move %</Th>
                  <Th>Start → event</Th>
                  <Th>Gap to next</Th>
                  <Th>Recovery</Th>
                </tr>
              </thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={`${e.event_time}-${i}`}>
                    <Td>{i + 1}</Td>
                    <Td>
                      <span className={e.direction === 'fall' ? 'text-rose-300' : 'text-emerald-300'}>
                        {String(e.direction)}
                      </span>
                    </Td>
                    <Td className="whitespace-nowrap text-xs">{fmtWhen(e.event_time)}</Td>
                    <Td>
                      <span className={changeClass(e.move_pct)}>{fmtSignedPct(e.move_pct)}</span>
                    </Td>
                    <Td className="text-xs text-slate-400">
                      {fmtWhen(e.start_time)}
                      <div className="text-slate-500">{String(e.move_label ?? '')}</div>
                    </Td>
                    <Td className="text-xs text-slate-400">
                      {e.gap_to_next_label != null ? String(e.gap_to_next_label) : '—'}
                      {e.next_event_direction != null && (
                        <div className="text-slate-500">→ {String(e.next_event_direction)}</div>
                      )}
                    </Td>
                    <Td className="text-xs">
                      {e.recovered ? (
                        <span className="text-sky-300">{String(e.recovery_label ?? 'recovered')}</span>
                      ) : (
                        <span className="text-slate-500">not yet</span>
                      )}
                      {e.recovery_time != null && (
                        <div className="text-slate-500">{fmtWhen(e.recovery_time)}</div>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </div>
      )}
    </div>
  )
}

function biasClass(bias: unknown) {
  const b = String(bias || '')
  if (b === 'reverse') return 'text-emerald-300'
  if (b === 'continue') return 'text-rose-300'
  if (b === 'mixed') return 'text-amber-300'
  return 'text-slate-400'
}

function FromTopTickerCard({ row, assetClass }: { row: Row; assetClass: AssetClass }) {
  const [open, setOpen] = useState(false)
  const chartBars = useMemo(() => toVpBars(row.chart_data), [row.chart_data])
  const tradeSetup = useMemo(() => tradeSetupFromResult(row), [row])
  const matched = Boolean(row.matched)

  return (
    <div className="rounded-xl border border-slate-800/70 bg-slate-950/40">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">
              {tickerNameOnly(row) || String(row.ticker)}
            </span>
            {tickerNameOnly(row) && (
              <span className="text-[10px] text-slate-500">{String(row.ticker)}</span>
            )}
            {matched ? (
              <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] text-rose-300">
                −{fmtNum(row.fall_from_top_pct)}% off top
              </span>
            ) : (
              <span className="rounded bg-slate-700/40 px-1.5 py-0.5 text-[10px] text-slate-400">
                below threshold
              </span>
            )}
            <span className={`rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] ${biasClass(row.bias)}`}>
              {String(row.bias_label ?? row.bias ?? '—')}
            </span>
            <span className="rounded bg-slate-700/40 px-1.5 py-0.5 text-[10px] text-slate-300">
              Conf {fmtNum(row.confidence_pct, 0)}%
            </span>
            {tradeSetup?.sl_pct != null && tradeSetup?.tp_pct != null && (
              <span className="rounded bg-slate-700/40 px-1.5 py-0.5 text-[10px] text-slate-300">
                SL {fmtNum(tradeSetup.sl_pct, 1)}% · TP {fmtNum(tradeSetup.tp_pct, 1)}%
              </span>
            )}
          </div>
          {row.error ? (
            <p className="mt-1 text-xs text-amber-400">{String(row.error)}</p>
          ) : (
            <p className="mt-1 text-xs text-slate-400">
              Reverse{' '}
              <span className="text-emerald-300">{fmtNum(row.reverse_chance_pct, 0)}%</span>
              {' · Continue '}
              <span className="text-rose-300">{fmtNum(row.continue_chance_pct, 0)}%</span>
              {row.upside_if_reverse_pct != null && (
                <>
                  {' · Upside if reverse '}
                  <span className="text-emerald-300">~{fmtNum(row.upside_if_reverse_pct)}%</span>
                </>
              )}
              {row.further_fall_if_continue_pct != null && (
                <>
                  {' · Further fall if continue '}
                  <span className="text-rose-300">~{fmtNum(row.further_fall_if_continue_pct)}%</span>
                </>
              )}
            </p>
          )}
        </div>
        <span className="shrink-0 text-xs text-slate-500">{open ? 'Hide' : 'Details'}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-4 py-3">
          {row.plain_english != null && (
            <p className="text-sm text-slate-300">{String(row.plain_english)}</p>
          )}
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <div className="rounded-lg border border-slate-800/80 bg-slate-900/50 px-3 py-2">
              <div className="text-slate-500">Peak high</div>
              <div className="mt-0.5 text-slate-200">{fmtPx(row.peak_high, assetClass)}</div>
              <div className="text-[10px] text-slate-500">{fmtWhen(row.peak_time_ist ?? row.peak_time)}</div>
            </div>
            <div className="rounded-lg border border-slate-800/80 bg-slate-900/50 px-3 py-2">
              <div className="text-slate-500">Last</div>
              <div className="mt-0.5 text-slate-200">{fmtPx(row.last, assetClass)}</div>
              <div className="text-[10px] text-slate-500">
                {row.hours_since_peak_label != null
                  ? `${String(row.hours_since_peak_label)} since peak`
                  : row.days_since_peak != null
                    ? `${String(row.days_since_peak)}d since peak`
                    : '—'}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800/80 bg-slate-900/50 px-3 py-2">
              <div className="text-slate-500">Reverse chance</div>
              <div className="mt-0.5 text-emerald-300">{fmtNum(row.reverse_chance_pct, 0)}%</div>
              <div className="text-[10px] text-slate-500">
                Upside ~{fmtNum(row.upside_if_reverse_pct)}%
                {row.upside_toward_peak_pct != null
                  ? ` (≤${fmtNum(row.upside_toward_peak_pct)}% to peak)`
                  : ''}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800/80 bg-slate-900/50 px-3 py-2">
              <div className="text-slate-500">Continue chance</div>
              <div className="mt-0.5 text-rose-300">{fmtNum(row.continue_chance_pct, 0)}%</div>
              <div className="text-[10px] text-slate-500">
                Further fall ~{fmtNum(row.further_fall_if_continue_pct)}%
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-[10px] text-slate-500">
            <span>{String(row.analogues ?? 0)} analogues</span>
            <span>· conf {fmtNum(row.confidence_pct, 0)}%</span>
            {row.recovered_to_peak_rate_pct != null && (
              <span>· hit peak again {fmtNum(row.recovered_to_peak_rate_pct, 0)}%</span>
            )}
            {row.room_to_peak_pct != null && (
              <span>· room to peak +{fmtNum(row.room_to_peak_pct)}%</span>
            )}
          </div>
          <TradeSetupBanner setup={tradeSetup} />
          {chartBars.length > 0 && (
            <VolumeProfileChart
              chartData={chartBars}
              readingGuide="Daily bars over the lookback. Peak high drives the from-top drawdown; odds use similar historical drawdowns."
            />
          )}
        </div>
      )}
    </div>
  )
}

export default function FallingKnife() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [mode, setMode] = useState<'live' | 'history' | 'from_top'>('live')
  const [dropPct, setDropPct] = useState(10)
  const [lookbackHours, setLookbackHours] = useState(24)
  const [loopHours, setLoopHours] = useState(24)
  const [fromDate, setFromDate] = useState(defaultFromDate(90))
  const [toDate, setToDate] = useState(new Date().toISOString().slice(0, 10))
  const [moveSide, setMoveSide] = useState<'fall' | 'rise' | 'both'>('both')
  const [thresholdPct, setThresholdPct] = useState(10)
  const [fromTopPct, setFromTopPct] = useState(10)
  const [error, setError] = useState('')
  const [showMatchedOnly, setShowMatchedOnly] = useState(true)
  const [selectedLiveTicker, setSelectedLiveTicker] = useState<string | null>(null)
  const { useAi, setUseAi } = useTradeSetupAi()

  const sessionQ = useQuery({
    queryKey: ['falling-knife-session', assetClass],
    queryFn: () => fetchFallingKnifeSession(assetClass),
    staleTime: 60_000,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker / universe')
      if (mode === 'from_top') {
        return runFallingKnifeScan({
          asset_class: assetClass,
          tickers: picker.tickers,
          mode: 'from_top',
          drop_pct: fromTopPct,
          threshold_pct: fromTopPct,
          lookback_hours: loopHours,
          use_ai: useAi,
        })
      }
      if (mode === 'history') {
        if (!fromDate) throw new Error('Set a from date for history mode')
        return runFallingKnifeScan({
          asset_class: assetClass,
          tickers: picker.tickers,
          mode: 'history',
          from_date: fromDate,
          to_date: toDate || undefined,
          move_side: moveSide,
          threshold_pct: thresholdPct,
          drop_pct: thresholdPct,
          use_ai: useAi,
        })
      }
      return runFallingKnifeScan({
        asset_class: assetClass,
        tickers: picker.tickers,
        mode: 'live',
        drop_pct: dropPct,
        lookback_hours: lookbackHours,
        move_side: moveSide,
        use_ai: useAi,
      })
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Row | undefined
  const dataMode = String(data?.mode ?? mode)
  const isHistory = dataMode === 'history'
  const isFromTop = dataMode === 'from_top'
  const knives = (data?.knives as Row[] | undefined) ?? []
  const results = (data?.results as Row[] | undefined) ?? []
  const session = ((data?.session as Row | undefined) ?? (sessionQ.data as Row | undefined)?.session) as Row | undefined
  const liveRows = showMatchedOnly ? knives : results
  const fromTopRows = showMatchedOnly ? knives : results
  const selectedLiveRow = useMemo(() => {
    if (!liveRows.length) return null
    if (selectedLiveTicker) {
      const hit = liveRows.find((r) => String(r.ticker) === selectedLiveTicker)
      if (hit) return hit
    }
    return liveRows[0] ?? null
  }, [liveRows, selectedLiveTicker])
  const selectedLiveBars = useMemo(
    () => toVpBars(selectedLiveRow?.chart_data),
    [selectedLiveRow],
  )
  const askContext = data ? buildAskContext('Falling Knife', data) : ''

  const presets = useMemo(
    () => [
      { label: '10% / 24h', pct: 10, hours: 24 },
      { label: '5% / 6h', pct: 5, hours: 6 },
      { label: '8% / 48h', pct: 8, hours: 48 },
      { label: '15% / 72h', pct: 15, hours: 72 },
    ],
    [],
  )

  const fromTopPresets = useMemo(
    () => [
      { label: '10% / 24h', pct: 10, hours: 24 },
      { label: '8% / 48h', pct: 8, hours: 48 },
      { label: '15% / 72h', pct: 15, hours: 72 },
      { label: '20% / 168h', pct: 20, hours: 168 },
    ],
    [],
  )

  const scanButtonLabel = (() => {
    if (runMut.isPending) {
      if (mode === 'history') return 'Analyzing history…'
      if (mode === 'from_top') return 'Scanning from tops…'
      return 'Scanning…'
    }
    if (mode === 'history') return `Analyze history (${picker.tickers.length} · ≥${thresholdPct}%)`
    if (mode === 'from_top') {
      return `Scan from top (≥${fromTopPct}% / ${loopHours}h · ${picker.tickers.length})`
    }
    return `Scan (≥${dropPct}% ${moveSide === 'fall' ? 'falls' : moveSide === 'rise' ? 'rises' : 'falls & rises'} / ${lookbackHours}h · ${picker.tickers.length})`
  })()

  const loadingMessage = (() => {
    if (mode === 'history') return `Counting ≥${thresholdPct}% rises/falls and building forecasts…`
    if (mode === 'from_top') {
      return useAi
        ? `Finding names ≥${fromTopPct}% below their ${loopHours}h high + AI refining odds…`
        : `Finding names ≥${fromTopPct}% below their ${loopHours}h high and scoring reverse/continue odds…`
    }
    return useAi
      ? `Scanning ${picker.tickers.length} tickers + AI refining Conf/SL/TP…`
      : `Scanning ${picker.tickers.length} tickers for ≥${dropPct}% ${moveSide === 'fall' ? 'falls' : moveSide === 'rise' ? 'rises' : 'falls & rises'} in ${lookbackHours}h…`
  })()

  return (
    <div>
      <PageHeader
        title="Falling Knife"
        description="Live session rises & falls, history of ≥X% moves, and loop-hour peak drawdowns with reverse/continue odds"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use" defaultOpen copyText={HOW_TO}>
          {HOW_TO}
        </CollapsibleSection>
      </div>

      <Card className="mb-4 space-y-4">
        <div className="flex flex-wrap gap-2">
          <Chip selected={mode === 'live'} onClick={() => setMode('live')}>
            Live scan
          </Chip>
          <Chip selected={mode === 'history'} onClick={() => setMode('history')}>
            History & forecast
          </Chip>
          <Chip selected={mode === 'from_top'} onClick={() => setMode('from_top')}>
            From top
          </Chip>
        </div>

        <div className="flex flex-wrap gap-2">
          {ASSET_CLASSES.map((a) => (
            <Chip
              key={a.id}
              selected={assetClass === a.id}
              onClick={() => {
                setAssetClass(a.id)
                setPicker({ tickers: [], durations: [] })
              }}
            >
              {a.label}
            </Chip>
          ))}
        </div>

        {session != null && (
          <p className="text-xs text-slate-400">
            Session: <span className="text-slate-200">{String(session.label ?? '')}</span>
            {session.note != null ? ` — ${String(session.note)}` : ''}
          </p>
        )}

        <AssetClassTickerPicker
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={mode === 'history' || mode === 'from_top' ? 12 : 50}
          onChange={setPicker}
        />

        {mode === 'live' ? (
          <>
            <div className="grid max-w-4xl gap-3 sm:grid-cols-3">
              <FormField label="Threshold % (X)">
                <Input
                  type="number"
                  min={0.5}
                  max={90}
                  step={0.5}
                  value={dropPct}
                  onChange={(e) => setDropPct(Number(e.target.value) || 10)}
                />
              </FormField>
              <FormField label="Lookback hours">
                <Input
                  type="number"
                  min={1}
                  max={336}
                  step={1}
                  value={lookbackHours}
                  onChange={(e) => setLookbackHours(Number(e.target.value) || 24)}
                />
              </FormField>
              <FormField label="Count">
                <Select value={moveSide} onChange={(e) => setMoveSide(e.target.value as 'fall' | 'rise' | 'both')}>
                  <option value="both">Falls & rises</option>
                  <option value="fall">Falls only</option>
                  <option value="rise">Rises only</option>
                </Select>
              </FormField>
            </div>
            <div className="flex flex-wrap gap-2">
              {presets.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  className="rounded-lg border border-slate-700/80 px-2.5 py-1.5 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
                  onClick={() => {
                    setDropPct(p.pct)
                    setLookbackHours(p.hours)
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </>
        ) : mode === 'from_top' ? (
          <>
            <div className="grid max-w-3xl gap-3 sm:grid-cols-2">
              <FormField label="Fallen from top ≥ % (X)">
                <Input
                  type="number"
                  min={0.5}
                  max={90}
                  step={0.5}
                  value={fromTopPct}
                  onChange={(e) => setFromTopPct(Number(e.target.value) || 10)}
                />
              </FormField>
              <FormField label="Loop hours">
                <Input
                  type="number"
                  min={1}
                  max={336}
                  step={1}
                  value={loopHours}
                  onChange={(e) => setLoopHours(Number(e.target.value) || 24)}
                />
              </FormField>
            </div>
            <p className="text-xs text-slate-500">
              Finds tickers currently ≥ X% below their high in the last loop hours, then scores reverse vs
              continue odds from similar historical drawdowns.
            </p>
            <div className="flex flex-wrap gap-2">
              {fromTopPresets.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  className="rounded-lg border border-slate-700/80 px-2.5 py-1.5 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
                  onClick={() => {
                    setFromTopPct(p.pct)
                    setLoopHours(p.hours)
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <FormField label="From date">
              <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
            </FormField>
            <FormField label="To date">
              <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
            </FormField>
            <FormField label="Threshold % (X)">
              <Input
                type="number"
                min={0.5}
                max={90}
                step={0.5}
                value={thresholdPct}
                onChange={(e) => setThresholdPct(Number(e.target.value) || 10)}
              />
            </FormField>
            <FormField label="Count">
              <Select value={moveSide} onChange={(e) => setMoveSide(e.target.value as 'fall' | 'rise' | 'both')}>
                <option value="both">Falls & rises</option>
                <option value="fall">Falls only</option>
                <option value="rise">Rises only</option>
              </Select>
            </FormField>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !picker.tickers.length}
          >
            <TrendingDown size={16} className="mr-1.5" />
            {scanButtonLabel}
          </Button>
          {(mode === 'live' || mode === 'from_top') && (
            <Chip selected={showMatchedOnly} onClick={() => setShowMatchedOnly((v) => !v)}>
              {showMatchedOnly ? 'Matched only' : 'Show all scanned'}
            </Chip>
          )}
        </div>

        <UseAiCheckbox checked={useAi} onChange={setUseAi} className="mt-1" />

        {error && <Alert type="error">{error}</Alert>}
      </Card>

      {runMut.isPending && <Loading message={loadingMessage} />}

      {data && !runMut.isPending && isFromTop && (
        <>
          <Card className="mb-4">
            <p className="text-sm text-slate-200">{String(data.plain_english ?? '')}</p>
            {data.ai_refinement != null && (
              <p className="mt-2 text-xs text-violet-300/90">
                AI: {String((data.ai_refinement as Row).reason ?? '')}
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-rose-200">
                {String((data.summary as Row | undefined)?.matched ?? knives.length)} matched
              </span>
              <span className="rounded-full border border-slate-700 px-2.5 py-1 text-slate-400">
                {String((data.summary as Row | undefined)?.scanned ?? results.length)} scanned · ≥
                {String(data.drop_pct ?? fromTopPct)}% / {String(data.loop_hours ?? data.lookback_hours ?? loopHours)}h
              </span>
            </div>
          </Card>

          <div className="mb-4 space-y-3">
            {!fromTopRows.length ? (
              <Card>
                <p className="text-sm text-slate-400">
                  {showMatchedOnly
                    ? `No tickers ≥${fromTopPct}% below their ${loopHours}h high.`
                    : 'No results.'}
                </p>
              </Card>
            ) : (
              fromTopRows.map((r) => (
                <FromTopTickerCard key={String(r.ticker)} row={r} assetClass={assetClass} />
              ))
            )}
          </div>

          {askContext && <AskAIPanel context={askContext} section="prediction/falling-knife" />}
        </>
      )}

      {data && !runMut.isPending && isHistory && (
        <>
          <Card className="mb-4">
            <p className="text-sm text-slate-200">{String(data.plain_english ?? '')}</p>
            {data.ai_refinement != null && (
              <p className="mt-2 text-xs text-violet-300/90">
                AI: {String((data.ai_refinement as Row).reason ?? '')}
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-rose-200">
                {String((data.summary as Row | undefined)?.fall_events ?? data.total_fall_events ?? 0)} falls
              </span>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-200">
                {String((data.summary as Row | undefined)?.rise_events ?? data.total_rise_events ?? 0)} rises
              </span>
              <span className="rounded-full border border-slate-700 px-2.5 py-1 text-slate-400">
                {String((data.summary as Row | undefined)?.scanned ?? results.length)} tickers ·{' '}
                {String(data.from_date)} → {String(data.to_date)}
              </span>
            </div>
          </Card>

          <div className="mb-4 space-y-3">
            {!results.length ? (
              <Card>
                <p className="text-sm text-slate-400">No results.</p>
              </Card>
            ) : (
              results.map((r) => (
                <HistoryTickerCard key={String(r.ticker)} row={r} assetClass={assetClass} />
              ))
            )}
          </div>

          {askContext && <AskAIPanel context={askContext} section="prediction/falling-knife" />}
        </>
      )}

      {data && !runMut.isPending && !isHistory && !isFromTop && (
        <>
          <Card className="mb-4">
            <p className="text-sm text-slate-200">{String(data.plain_english ?? '')}</p>
            {data.ai_refinement != null && (
              <p className="mt-2 text-xs text-violet-300/90">
                AI: {String((data.ai_refinement as Row).reason ?? '')}
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-rose-200">
                {String((data.summary as Row | undefined)?.matched_falls ?? data.matched_falls ?? 0)} falls
              </span>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-200">
                {String((data.summary as Row | undefined)?.matched_rises ?? data.matched_rises ?? 0)} rises
              </span>
              <span className="rounded-full border border-slate-700 px-2.5 py-1 text-slate-400">
                {String((data.summary as Row | undefined)?.matched ?? knives.length)} matched ·{' '}
                {String((data.summary as Row | undefined)?.scanned ?? results.length)} scanned
              </span>
              <span className="rounded-full border border-slate-700 px-2.5 py-1 text-slate-400">
                {String(data.interval ?? '')} bars · {String((data.session as Row | undefined)?.label ?? '')}
              </span>
            </div>
          </Card>

          <Card className="mb-4 overflow-x-auto">
            {!liveRows.length ? (
              <p className="text-sm text-slate-400">
                {showMatchedOnly
                  ? `No tickers matched ≥${dropPct}% ${moveSide === 'fall' ? 'fall from high' : moveSide === 'rise' ? 'rise from low' : 'fall from high or rise from low'} in the last ${lookbackHours}h (session hours).`
                  : 'No rows.'}
              </p>
            ) : (
              <>
                <p className="mb-2 text-xs text-slate-500">
                  Click a row to load its chart (Candles / Line toggle on the chart).
                </p>
                <DataTable>
                  <thead>
                    <tr>
                      <Th>#</Th>
                      <Th>Ticker</Th>
                      <Th>Net change %</Th>
                      <Th>Off high %</Th>
                      <Th>Off low %</Th>
                      <Th>Conf %</Th>
                      <Th>SL %</Th>
                      <Th>TP %</Th>
                      <Th>Last</Th>
                      <Th>Open</Th>
                      <Th>High</Th>
                      <Th>Low</Th>
                      <Th>H→L %</Th>
                      <Th>Bars</Th>
                      <Th>Status</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {liveRows.map((r, i) => {
                      const matchFall = Boolean(r.match_fall)
                      const matchRise = Boolean(r.match_rise)
                      const isSelected = String(selectedLiveRow?.ticker ?? '') === String(r.ticker)
                      const setup = tradeSetupFromResult(r)
                      let statusLabel = '—'
                      let statusClass = 'text-xs text-slate-500'
                      if (r.error) {
                        statusLabel = String(r.error)
                        statusClass = 'text-xs text-amber-400'
                      } else if (matchFall && matchRise) {
                        statusLabel = 'Fall + Rise'
                        statusClass = 'text-xs text-amber-300'
                      } else if (matchFall) {
                        statusLabel = 'Fall'
                        statusClass = 'text-xs text-rose-300'
                      } else if (matchRise) {
                        statusLabel = 'Rise'
                        statusClass = 'text-xs text-emerald-300'
                      }
                      return (
                        <tr
                          key={`${r.ticker}-${i}`}
                          className={`cursor-pointer ${isSelected ? 'bg-sky-500/10' : 'hover:bg-slate-800/40'}`}
                          onClick={() => setSelectedLiveTicker(String(r.ticker))}
                        >
                          <Td>{i + 1}</Td>
                          <Td>
                            <span className="font-semibold text-white">
                              {tickerNameOnly(r) || String(r.ticker)}
                            </span>
                            {tickerNameOnly(r) && (
                              <div className="text-[10px] text-slate-500">{String(r.ticker)}</div>
                            )}
                            {r.direction != null && (
                              <span className="ml-2 text-[10px] uppercase text-slate-500">{String(r.direction)}</span>
                            )}
                            {setup?.action != null && setup.action !== 'WAIT' && (
                              <span
                                className={`ml-2 text-[10px] font-semibold ${
                                  setup.action === 'BUY' ? 'text-emerald-400' : 'text-rose-400'
                                }`}
                              >
                                {String(setup.action)}
                              </span>
                            )}
                          </Td>
                          <Td>
                            <span className={changeClass(r.change_pct)}>{fmtSignedPct(r.change_pct)}</span>
                          </Td>
                          <Td>
                            <span className={matchFall ? 'font-semibold text-rose-300' : 'text-slate-300'}>
                              {r.fall_from_high_pct != null ? `−${fmtNum(r.fall_from_high_pct)}%` : '—'}
                            </span>
                          </Td>
                          <Td>
                            <span className={matchRise ? 'font-semibold text-emerald-300' : 'text-emerald-300/70'}>
                              {r.rise_from_low_pct != null ? `+${fmtNum(r.rise_from_low_pct)}%` : '—'}
                            </span>
                          </Td>
                          <Td>
                            <span className="text-slate-200">
                              {setup?.confidence_pct != null ? `${fmtNum(setup.confidence_pct, 0)}%` : '—'}
                            </span>
                          </Td>
                          <Td>
                            <span className="text-rose-300">
                              {setup?.sl_pct != null ? `${fmtNum(setup.sl_pct, 1)}%` : '—'}
                            </span>
                          </Td>
                          <Td>
                            <span className="text-emerald-300">
                              {setup?.tp_pct != null ? `${fmtNum(setup.tp_pct, 1)}%` : '—'}
                            </span>
                          </Td>
                          <Td>{fmtPx(r.last, assetClass)}</Td>
                          <Td>{fmtPx(r.window_open, assetClass)}</Td>
                          <Td>{fmtPx(r.window_high, assetClass)}</Td>
                          <Td>{fmtPx(r.window_low, assetClass)}</Td>
                          <Td>{r.range_high_to_low_pct != null ? `${fmtNum(r.range_high_to_low_pct)}%` : '—'}</Td>
                          <Td>{r.bars_in_window != null ? String(r.bars_in_window) : '—'}</Td>
                          <Td>
                            <span className={statusClass}>{statusLabel}</span>
                          </Td>
                        </tr>
                      )
                    })}
                  </tbody>
                </DataTable>
                {selectedLiveBars.length > 0 && selectedLiveRow && (
                  <div className="mt-4 border-t border-slate-800/60 pt-4">
                    <p className="mb-2 text-sm font-medium text-white">
                      Chart · {tickerDisplayLabel(selectedLiveRow)}
                    </p>
                    <div className="mb-3">
                      <TradeSetupBanner setup={tradeSetupFromResult(selectedLiveRow)} />
                    </div>
                    <div className="mb-3">
                      <FallRiseForecastCards forecast={forecastFromResult(selectedLiveRow)} />
                    </div>
                    <VolumeProfileChart
                      chartData={selectedLiveBars}
                      readingGuide="Use Candles or Line. Live session window high/low drive the fall/rise match. Forecast cards use ~90d daily history."
                    />
                  </div>
                )}
              </>
            )}
          </Card>

          {askContext && <AskAIPanel context={askContext} section="prediction/falling-knife" />}
        </>
      )}
    </div>
  )
}
