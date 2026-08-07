import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import {
  apiErrorMessage,
  fetchDetectSectorRotationUniverse,
  runDetectSectorRotation,
} from '../../api/client'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../analysis/AnalysisBackground'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField, Input, Select } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'
import { StrategyDataSourceBar } from '../ui/StrategyDataSourceBar'

type Market = 'india' | 'us' | 'crypto'
type Row = Record<string, unknown>

const YT = 'https://www.youtube.com/watch?v=IfMDd2XlArU&t=123s'

const EXPLANATION = `Detect Sector Rotation — top-down weekly CRS + Hull confirmation
(${YT}).

1. Cyclical pullback: sector negative for 2–3 consecutive months/quarters.
2. Comparative RS: Sector÷Benchmark above its 50-week SMA (outperforming).
3. Hull confirm: sector close above HMA(9) — absolute uptrend.
4. BUY / ROTATE IN when (2) and (3) are true; higher conviction with pullback / fresh CRS cross.

India: Nifty sectors vs Nifty 50 · US: SPDR ETFs vs SPY · Crypto: themes vs BTC.
Each sector also lists linked ETFs and top 20 stocks / theme peers.
Research / education only — not financial advice.`

function Collapsible({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-medium text-slate-200">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {title}
      </button>
      {open && <div className="border-t border-slate-800/60 px-3 py-3 text-xs leading-relaxed text-slate-400 whitespace-pre-line">{children}</div>}
    </div>
  )
}

function verdictBadge(v: string) {
  if (v === 'BUY') return '🟢 BUY'
  if (v === 'WATCH') return '🟡 WATCH'
  return '🔴 AVOID'
}

function LinkedInstruments({ row }: { row: Row }) {
  const etfs = (row.etfs as string[]) ?? []
  const stocks = (row.top_stocks as string[]) ?? []
  const label = String(row.top_stocks_label ?? 'Top stocks')
  return (
    <div className="mt-3 space-y-2 border-t border-slate-800/60 pt-3">
      <div>
        <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">Linked ETFs</p>
        {etfs.length ? (
          <div className="flex flex-wrap gap-1.5">
            {etfs.map((e) => (
              <span key={e} className="rounded bg-slate-800/80 px-2 py-0.5 font-mono text-[11px] text-sky-300">{e}</span>
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-slate-600">No dedicated liquid ETF mapped</p>
        )}
      </div>
      <div>
        <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
          {label} ({stocks.length})
        </p>
        {stocks.length ? (
          <div className="flex flex-wrap gap-1.5">
            {stocks.map((s) => (
              <span key={s} className="rounded bg-slate-800/60 px-2 py-0.5 font-mono text-[11px] text-slate-300">{s}</span>
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-slate-600">No constituent / peer list available</p>
        )}
      </div>
    </div>
  )
}

function SectorCard({ row, defaultOpen }: { row: Row; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(Boolean(defaultOpen))
  const reasons = (row.reasons as string[]) ?? []
  const pb = (row.pullback as Row) ?? {}
  const etfs = (row.etfs as string[]) ?? []
  const etfPreview = etfs.length ? etfs.slice(0, 3).join(', ') + (etfs.length > 3 ? '…' : '') : ''
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-sm">
        <span className="font-medium text-white">
          {verdictBadge(String(row.verdict ?? 'AVOID'))} · {String(row.name)} · {String(row.setup ?? '')} · conf {String(row.confidence_pct ?? 0)}%
          {etfPreview ? <span className="ml-2 font-normal text-slate-500">· {etfPreview}</span> : null}
        </span>
        {open ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
      </button>
      {open && (
        <div className="space-y-1 border-t border-slate-800/60 px-3 py-3 text-xs text-slate-400">
          {!row.error && (
            <>
              <p>Close {String(row.close)} · CRS {String(row.crs)} · SMA50 {String(row.crs_sma_50)} · HMA {String(row.hma)}</p>
              <p>CRS&gt;SMA {row.outperforming ? '✅' : '—'} · Hull buy {row.hull_buy ? '✅' : '—'} · Pullback {pb.pullback ? '✅' : '—'} · 4w {String(row.ret_4w_pct ?? '—')}% · 13w {String(row.ret_13w_pct ?? '—')}%</p>
              {reasons.map((r) => <p key={r}>· {r}</p>)}
            </>
          )}
          {Boolean(row.error) && <p className="text-rose-400">{String(row.error)}</p>}
          <LinkedInstruments row={row} />
        </div>
      )}
    </div>
  )
}

function MarketPanel({ market, label }: { market: Market; label: string }) {
  const [crsSma, setCrsSma] = useState(50)
  const [hmaLen, setHmaLen] = useState(9)
  const [pbMonths, setPbMonths] = useState(2)
  const [pbMode, setPbMode] = useState<'months' | 'quarters'>('months')
  const [selected, setSelected] = useState<string[]>([])
  const [error, setError] = useState('')
  const bg = useAnalysisBackground('command_center', 'detect_sector_rotation')

  const universeQ = useQuery({
    queryKey: ['dsr-universe', market],
    queryFn: () => fetchDetectSectorRotationUniverse(market),
  })

  const sectors = useMemo(() => (universeQ.data?.sectors as string[]) ?? [], [universeQ.data])

  useEffect(() => {
    if (sectors.length && !selected.length) setSelected(sectors)
  }, [sectors]) // eslint-disable-line react-hooks/exhaustive-deps

  const scanMut = useMutation({
    mutationFn: () =>
      runDetectSectorRotation({
        market,
        sectors: selected.length ? selected : undefined,
        crs_sma_period: crsSma,
        hma_length: hmaLen,
        pullback_months: pbMonths,
        pullback_mode: pbMode,
      }),
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const buildPayload = () => ({
    market,
    sectors: selected.length ? selected : undefined,
    crs_sma_period: crsSma,
    hma_length: hmaLen,
    pullback_months: pbMonths,
    pullback_mode: pbMode,
  })

  const data = (bg.viewedPayload ?? scanMut.data) as Row | undefined
  const buy = (data?.buy as Row[]) ?? []
  const watch = (data?.watch as Row[]) ?? []
  const avoid = (data?.avoid as Row[]) ?? []
  const ask = data ? buildAskContext(`Detect Sector Rotation (${label})`, data) : ''

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{label} — weekly CRS vs benchmark · Hull confirmation · cyclical pullback.</p>
      <Collapsible title="📖 Strategy explanation — Detect Sector Rotation">{EXPLANATION}</Collapsible>

      <Card>
        <div className="grid gap-3 sm:grid-cols-4">
          <FormField label="CRS SMA">
            <Input type="number" min={20} max={100} value={crsSma} onChange={(e) => setCrsSma(Number(e.target.value))} />
          </FormField>
          <FormField label="HMA length">
            <Input type="number" min={5} max={21} value={hmaLen} onChange={(e) => setHmaLen(Number(e.target.value))} />
          </FormField>
          <FormField label="Pullback streak">
            <Input type="number" min={2} max={4} value={pbMonths} onChange={(e) => setPbMonths(Number(e.target.value))} />
          </FormField>
          <FormField label="Pullback mode">
            <Select value={pbMode} onChange={(e) => setPbMode(e.target.value as 'months' | 'quarters')}>
              <option value="months">Months</option>
              <option value="quarters">Quarters</option>
            </Select>
          </FormField>
        </div>

        <div className="mt-3">
          <p className="mb-2 text-xs text-slate-500">Sectors ({selected.length}/{sectors.length})</p>
          <div className="flex max-h-36 flex-wrap gap-1.5 overflow-y-auto">
            {sectors.map((s) => {
              const on = selected.includes(s)
              return (
                <Chip
                  key={s}
                  selected={on}
                  onClick={() => setSelected((prev) => (on ? prev.filter((x) => x !== s) : [...prev, s]))}
                >
                  {s}
                </Chip>
              )
            })}
          </div>
        </div>

        <Button className="mt-4" onClick={() => scanMut.mutate()} disabled={scanMut.isPending || !selected.length || bg.runInBackground}>
          {scanMut.isPending ? 'Scanning…' : `🔍 Detect rotation — ${label}`}
        </Button>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Sector Rotation · ${label} · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => (!selected.length ? 'Select at least one sector' : null))}
        />
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {scanMut.isPending && !bg.viewedPayload && <Loading message="Fetching weekly bars & computing CRS + Hull…" />}

      {data && (!scanMut.isPending || bg.viewedPayload) && (
        <Card>
          {bg.viewedReportMeta?.name && (
            <p className="mb-3 text-sm text-slate-400">
              Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
            </p>
          )}
          <StrategyDataSourceBar data={data} assetClass={market === 'us' ? 'us' : market === 'crypto' ? 'crypto' : 'india'} />
          {Boolean(data.error) && <Alert type="error">{String(data.error)}</Alert>}
          <p className="mb-3 text-sm text-slate-400">
            Benchmark: <strong className="text-white">{String(data.benchmark)}</strong> ·
            🟢 {String(data.buy_count ?? 0)} · 🟡 {String(data.watch_count ?? 0)} · 🔴 {String(data.avoid_count ?? 0)}
          </p>
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-sm font-medium text-emerald-400">Buy / Rotate in</p>
              <div className="space-y-2">{buy.length ? buy.map((r, i) => <SectorCard key={String(r.name)} row={r} defaultOpen={i === 0} />) : <p className="text-xs text-slate-500">None</p>}</div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-amber-400">Watch</p>
              <div className="space-y-2">{watch.length ? watch.map((r) => <SectorCard key={String(r.name)} row={r} />) : <p className="text-xs text-slate-500">None</p>}</div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-rose-400">Avoid</p>
              <div className="space-y-2">{avoid.slice(0, 8).map((r) => <SectorCard key={String(r.name)} row={r} />)}</div>
              {avoid.length > 8 && <p className="mt-1 text-xs text-slate-500">…and {avoid.length - 8} more</p>}
            </div>
          </div>
        </Card>
      )}

      {ask && !scanMut.isPending && <AskAIPanel context={ask} section="command-center/detect_sector_rotation" />}
    </div>
  )
}

export function DetectSectorRotationPanel() {
  const [market, setMarket] = useState<Market>('india')
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Chip selected={market === 'india'} onClick={() => setMarket('india')}>🇮🇳 India</Chip>
        <Chip selected={market === 'us'} onClick={() => setMarket('us')}>🇺🇸 US</Chip>
        <Chip selected={market === 'crypto'} onClick={() => setMarket('crypto')}>₿ Crypto</Chip>
      </div>
      <MarketPanel
        key={market}
        market={market}
        label={market === 'india' ? 'India (Nifty sectors)' : market === 'us' ? 'US (SPDR sectors)' : 'Crypto (vs BTC)'}
      />
    </div>
  )
}
