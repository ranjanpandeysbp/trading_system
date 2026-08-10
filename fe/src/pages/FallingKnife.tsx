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
import { FormField, Input } from '../components/ui/Form'
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

1. Pick an asset class (India · US · Crypto · Commodities).
2. Choose a universe (index / top-N / custom tickers).
3. Enter drop % (e.g. 10) and lookback hours (e.g. 24).
4. Click Scan — only that market’s session hours inside the window are used.

Sessions
· India — Mon–Fri 09:15–15:30 IST
· US — Mon–Fri 09:30–16:00 America/New_York
· Crypto — 24×7
· Commodities — ~24×5 futures (Sun–Fri ET)

Fall % off high = (window high − last) / high.
Net change % = (last − first) / first — positive = risen, negative = fallen.
Also shows rise from window low %.

Educational screener only — not a buy/sell signal.`

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

export default function FallingKnife() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [dropPct, setDropPct] = useState(10)
  const [lookbackHours, setLookbackHours] = useState(24)
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
      return runFallingKnifeScan({
        asset_class: assetClass,
        tickers: picker.tickers,
        drop_pct: dropPct,
        lookback_hours: lookbackHours,
      })
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Row | undefined
  const knives = (data?.knives as Row[] | undefined) ?? []
  const results = (data?.results as Row[] | undefined) ?? []
  const session = ((data?.session as Row | undefined) ?? (sessionQ.data as Row | undefined)?.session) as Row | undefined
  const rows = showMatchedOnly ? knives : results
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
        description="Session-aware drops: net risen/fallen %, off high, off low — India · US · Crypto · Commodities"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use" defaultOpen copyText={HOW_TO}>
          {HOW_TO}
        </CollapsibleSection>
      </div>

      <Card className="mb-4 space-y-4">
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
          defaultSelectCount={50}
          onChange={setPicker}
        />

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

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !picker.tickers.length}
          >
            <TrendingDown size={16} className="mr-1.5" />
            {runMut.isPending
              ? 'Scanning…'
              : `Scan Falling Knives (${picker.tickers.length} tickers · ≥${dropPct}% / ${lookbackHours}h)`}
          </Button>
          <Chip selected={showMatchedOnly} onClick={() => setShowMatchedOnly((v) => !v)}>
            {showMatchedOnly ? 'Matched only' : 'Show all scanned'}
          </Chip>
        </div>

        {error && <Alert type="error">{error}</Alert>}
      </Card>

      {runMut.isPending && (
        <Loading message={`Scanning ${picker.tickers.length} tickers for ≥${dropPct}% drops in ${lookbackHours}h…`} />
      )}

      {data && !runMut.isPending && (
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
            {!rows.length ? (
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
                  {rows.map((r, i) => (
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

          {askContext && <AskAIPanel context={askContext} section="falling-knife" />}
        </>
      )}
    </div>
  )
}
