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
2. Set drop % from window high and lookback hours.
3. Scan uses only that market’s session hours.

History & forecast
1. Switch to History mode.
2. Set from/to dates, threshold % (X), and Fall / Rise / Both.
3. For each ticker you get every past move ≥ X%, event datetime, gap to next move,
   hours/days to recover back to the start of that pump/dump, plus a next-event
   forecast (datetime, confidence %, typical move %).

Sessions
· India — Mon–Fri 09:15–15:30 IST
· US — Mon–Fri 09:30–16:00 America/New_York
· Crypto — 24×7
· Commodities — ~24×5 futures (Sun–Fri ET)

Educational only — not a buy/sell signal.`

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
  return String(v).replace('T', ' ').slice(0, 16)
}

function defaultFromDate(daysBack = 90) {
  const d = new Date()
  d.setDate(d.getDate() - daysBack)
  return d.toISOString().slice(0, 10)
}

function HistoryTickerCard({ row, assetClass }: { row: Row; assetClass: AssetClass }) {
  const [open, setOpen] = useState(false)
  const events = (row.events as Row[] | undefined) ?? []
  const forecast = (row.forecast as Row | undefined) ?? {}
  const primary = (row.primary_forecast as Row | undefined) ?? null
  const fallF = (forecast.fall as Row | undefined) ?? null
  const riseF = (forecast.rise as Row | undefined) ?? null

  return (
    <div className="rounded-xl border border-slate-800/70 bg-slate-950/40">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">{String(row.ticker)}</span>
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
          </div>
          {row.error ? (
            <p className="mt-1 text-xs text-amber-400">{String(row.error)}</p>
          ) : primary != null ? (
            <p className="mt-1 text-xs text-slate-400">
              Predicted {String(primary.direction)} around{' '}
              <span className="text-slate-200">{fmtWhen(primary.predicted_next_time)}</span>
              {' · move '}
              <span className={changeClass(primary.predicted_move_pct)}>
                {fmtSignedPct(primary.predicted_move_pct)}
              </span>
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

          {(fallF || riseF) && (
            <div className="grid gap-3 lg:grid-cols-2">
              {fallF && (
                <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-3">
                  <p className="text-xs font-semibold text-rose-200">Fall forecast</p>
                  <p className="mt-1 text-sm text-slate-200">{String(fallF.plain_english ?? '')}</p>
                  <p className="mt-2 text-xs text-slate-400">
                    Confidence {String(fallF.confidence_pct)}% · next {fmtWhen(fallF.predicted_next_time)} ·
                    move {fmtSignedPct(fallF.predicted_move_pct)}
                  </p>
                </div>
              )}
              {riseF && (
                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                  <p className="text-xs font-semibold text-emerald-200">Rise forecast</p>
                  <p className="mt-1 text-sm text-slate-200">{String(riseF.plain_english ?? '')}</p>
                  <p className="mt-2 text-xs text-slate-400">
                    Confidence {String(riseF.confidence_pct)}% · next {fmtWhen(riseF.predicted_next_time)} ·
                    move {fmtSignedPct(riseF.predicted_move_pct)}
                  </p>
                </div>
              )}
            </div>
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

export default function FallingKnife() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [mode, setMode] = useState<'live' | 'history'>('live')
  const [dropPct, setDropPct] = useState(10)
  const [lookbackHours, setLookbackHours] = useState(24)
  const [fromDate, setFromDate] = useState(defaultFromDate(90))
  const [toDate, setToDate] = useState(new Date().toISOString().slice(0, 10))
  const [moveSide, setMoveSide] = useState<'fall' | 'rise' | 'both'>('both')
  const [thresholdPct, setThresholdPct] = useState(10)
  const [error, setError] = useState('')
  const [showMatchedOnly, setShowMatchedOnly] = useState(true)

  const sessionQ = useQuery({
    queryKey: ['falling-knife-session', assetClass],
    queryFn: () => fetchFallingKnifeSession(assetClass),
    staleTime: 60_000,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker / universe')
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
        })
      }
      return runFallingKnifeScan({
        asset_class: assetClass,
        tickers: picker.tickers,
        mode: 'live',
        drop_pct: dropPct,
        lookback_hours: lookbackHours,
      })
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Row | undefined
  const isHistory = String(data?.mode ?? mode) === 'history'
  const knives = (data?.knives as Row[] | undefined) ?? []
  const results = (data?.results as Row[] | undefined) ?? []
  const session = ((data?.session as Row | undefined) ?? (sessionQ.data as Row | undefined)?.session) as Row | undefined
  const liveRows = showMatchedOnly ? knives : results
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

  return (
    <div>
      <PageHeader
        title="Falling Knife"
        description="Live session knives + history of ≥X% rises/falls with recovery time and next-move forecast"
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
          defaultSelectCount={mode === 'history' ? 12 : 50}
          onChange={setPicker}
        />

        {mode === 'live' ? (
          <>
            <div className="grid max-w-3xl gap-3 sm:grid-cols-2">
              <FormField label="Drop % (from window high)">
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
            {runMut.isPending
              ? mode === 'history'
                ? 'Analyzing history…'
                : 'Scanning…'
              : mode === 'history'
                ? `Analyze history (${picker.tickers.length} · ≥${thresholdPct}%)`
                : `Scan Falling Knives (${picker.tickers.length} · ≥${dropPct}% / ${lookbackHours}h)`}
          </Button>
          {mode === 'live' && (
            <Chip selected={showMatchedOnly} onClick={() => setShowMatchedOnly((v) => !v)}>
              {showMatchedOnly ? 'Matched only' : 'Show all scanned'}
            </Chip>
          )}
        </div>

        {error && <Alert type="error">{error}</Alert>}
      </Card>

      {runMut.isPending && (
        <Loading
          message={
            mode === 'history'
              ? `Counting ≥${thresholdPct}% rises/falls and building forecasts…`
              : `Scanning ${picker.tickers.length} tickers for ≥${dropPct}% drops in ${lookbackHours}h…`
          }
        />
      )}

      {data && !runMut.isPending && isHistory && (
        <>
          <Card className="mb-4">
            <p className="text-sm text-slate-200">{String(data.plain_english ?? '')}</p>
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

      {data && !runMut.isPending && !isHistory && (
        <>
          <Card className="mb-4">
            <p className="text-sm text-slate-200">{String(data.plain_english ?? '')}</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-rose-200">
                {String((data.summary as Row | undefined)?.matched ?? knives.length)} knives
              </span>
              <span className="rounded-full border border-slate-700 px-2.5 py-1 text-slate-400">
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
                  ? `No tickers fell ≥${dropPct}% from window high in the last ${lookbackHours}h (session hours).`
                  : 'No rows.'}
              </p>
            ) : (
              <DataTable>
                <thead>
                  <tr>
                    <Th>#</Th>
                    <Th>Ticker</Th>
                    <Th>Net change %</Th>
                    <Th>Off high %</Th>
                    <Th>Off low %</Th>
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
                  {liveRows.map((r, i) => (
                    <tr key={`${r.ticker}-${i}`}>
                      <Td>{i + 1}</Td>
                      <Td>
                        <span className="font-semibold text-white">{String(r.ticker)}</span>
                        {r.direction != null && (
                          <span className="ml-2 text-[10px] uppercase text-slate-500">{String(r.direction)}</span>
                        )}
                      </Td>
                      <Td>
                        <span className={changeClass(r.change_pct)}>{fmtSignedPct(r.change_pct)}</span>
                      </Td>
                      <Td>
                        <span className={r.matched ? 'font-semibold text-rose-300' : 'text-slate-300'}>
                          {r.fall_from_high_pct != null ? `−${fmtNum(r.fall_from_high_pct)}%` : '—'}
                        </span>
                      </Td>
                      <Td>
                        <span className="text-emerald-300/90">
                          {r.rise_from_low_pct != null ? `+${fmtNum(r.rise_from_low_pct)}%` : '—'}
                        </span>
                      </Td>
                      <Td>{fmtPx(r.last, assetClass)}</Td>
                      <Td>{fmtPx(r.window_open, assetClass)}</Td>
                      <Td>{fmtPx(r.window_high, assetClass)}</Td>
                      <Td>{fmtPx(r.window_low, assetClass)}</Td>
                      <Td>{r.range_high_to_low_pct != null ? `${fmtNum(r.range_high_to_low_pct)}%` : '—'}</Td>
                      <Td>{r.bars_in_window != null ? String(r.bars_in_window) : '—'}</Td>
                      <Td>
                        {r.error ? (
                          <span className="text-xs text-amber-400">{String(r.error)}</span>
                        ) : r.matched ? (
                          <span className="text-xs text-rose-300">Knife</span>
                        ) : (
                          <span className="text-xs text-slate-500">—</span>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Card>

          {askContext && <AskAIPanel context={askContext} section="prediction/falling-knife" />}
        </>
      )}
    </div>
  )
}
