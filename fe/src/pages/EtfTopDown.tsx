import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import {
  apiErrorMessage,
  fetchEtfTopDownUniverse,
  runEtfTopDownScan,
} from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { Alert, Loading } from '../components/ui/Feedback'
import { FormField, Input, Textarea } from '../components/ui/Form'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'
import { VolumeProfileChart, type VpChartBar, type VpLevel, type VpSeries } from '../components/pro-trade/VolumeProfileChart'

type Row = Record<string, unknown>

const YOUTUBE = 'https://www.youtube.com/watch?v=a4FmBVfjtNA&t=29s'

const HOW_TO = `How to use ETF Top Down

Source: ${YOUTUBE}
(Finding H podcast — Jay’s low-drawdown ETF swing)

1. Pick a universe preset (Top ~55 from FIRE + ETF Shop, or any ETF Shop / ETF 28 SMA list).
2. Scan — first read the macro board (Gold, Silver, Nifty 50/500, bonds, India VIX).
3. Focus on the shortlist: Top 20 ETFs with P&F RS score > 0.
4. Act on Renko × D-Smart 10: BUY on cross above, SELL / trail when below.
5. Prefer rebalancing on Fridays so volatile names (e.g. Silver) don’t give back weekly gains.
6. Research only — not advice. D-Smart is approximated as EMA(10) on Renko closes.`

const OVERVIEW = `ETF Top Down — rules

Philosophy: capture ETF momentum with controlled drawdowns (baskets fall less than single stocks).

1. Top-down macros — Gold, Silver, Nifty 50, Nifty 500, GS Composite/bonds, India VIX.
2. Relative Strength via Point & Figure (−3…+3). Double Top Buy above MA = +3; DBS below MA = −3.
3. Multi-denominator vs Nifty 50 + Nifty 500.
4. Rank ~55 ETFs → keep Top 20 with score strictly > 0.
5. Entry: Renko close crosses above D-Smart 10. Exit: falls below (trailing stop).
6. Weekly rebalance (Fridays preferred).`

const LAYMAN = `In plain English

First see which big asset is winning (gold, silver, equity, bonds, fear).
Then only look at ETFs that are beating the market on a simple scorecard.
Buy when the Renko chart flips above a 10-period smart line; sell when it flips below.
Check once a week (Friday) so a sharp drop in something like silver doesn’t erase the month.`

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: digits }) : '—'
}

function ActionBadge({ action }: { action: string }) {
  const a = action.toUpperCase()
  const cls =
    a === 'BUY' || a === 'HOLD'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : a === 'SELL'
        ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
        : a === 'SKIP' || a === 'WEAK'
          ? 'border-slate-700/60 bg-slate-800/40 text-slate-400'
          : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${cls}`}>
      {a}
    </span>
  )
}

function ResultCard({ result, index, showCharts }: { result: Row; index: number; showCharts: boolean }) {
  const [open, setOpen] = useState(index < 8 || Boolean(result.shortlisted) || Boolean(result.take_trade))
  const metrics = (result.metrics as Row | undefined) ?? {}
  const checks = (result.checks as Row[] | undefined) ?? []
  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(
    () =>
      (result.chart_series as VpSeries[] | undefined) ?? [
        { key: 'sma_ds', label: 'D-Smart≈EMA10', color: '#a78bfa' },
      ],
    [result.chart_series],
  )
  const levels = useMemo<VpLevel[]>(
    () => ((result.chart_levels as VpLevel[] | undefined) ?? []).filter((l) => l && l.price != null),
    [result.chart_levels],
  )

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left"
      >
        <span className="font-semibold text-white">{String(result.ticker)}</span>
        {result.rs_rank != null && (
          <span className="text-xs text-sky-300">RS #{String(result.rs_rank)}</span>
        )}
        {result.rs_score != null && (
          <span className="text-xs text-slate-300">score {fmtNum(result.rs_score, 0)}</span>
        )}
        {result.ltp != null && <span className="text-sm text-slate-400">₹{fmtNum(result.ltp)}</span>}
        <ActionBadge action={String(result.action ?? 'WAIT')} />
        {result.shortlisted ? (
          <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-200">
            Top list
          </span>
        ) : null}
        {result.error != null && <span className="text-xs text-amber-400">{String(result.error)}</span>}
      </button>
      {open && !result.error && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          {result.reason != null && (
            <p className="text-sm leading-relaxed text-slate-300">{String(result.reason)}</p>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {metrics.d_smart != null && (
              <span>
                D-Smart: <strong className="text-slate-300">{fmtNum(metrics.d_smart)}</strong>
              </span>
            )}
            {metrics.renko_close != null && (
              <span>
                Renko: <strong className="text-slate-300">{fmtNum(metrics.renko_close)}</strong>
              </span>
            )}
            {metrics.renko_bricks != null && (
              <span>
                Bricks: <strong className="text-slate-300">{String(metrics.renko_bricks)}</strong>
              </span>
            )}
            {metrics.bar_date != null && (
              <span>
                Bar: <strong className="text-slate-300">{String(metrics.bar_date)}</strong>
              </span>
            )}
          </div>
          {checks.length > 0 && (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {checks.map((ch) => {
                const ok = Boolean(ch.passed ?? ch.pass)
                return (
                  <div
                    key={String(ch.id)}
                    className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                      ok
                        ? 'border-emerald-500/25 bg-emerald-500/5 text-emerald-200'
                        : 'border-slate-800/80 bg-slate-950/40 text-slate-500'
                    }`}
                  >
                    <span className="font-medium">
                      {ok ? '✓' : '✗'} {String(ch.label)}
                    </span>
                    <p className="mt-0.5 text-[11px] opacity-80">{String(ch.detail)}</p>
                  </div>
                )
              })}
            </div>
          )}
          {showCharts && chartData.length > 0 && (
            <VolumeProfileChart
              chartData={chartData}
              series={series}
              levels={levels}
              readingGuide="Purple line ≈ D-Smart 10 (EMA on price; Renko cross drives BUY/SELL). Prefer weekly Friday checks."
            />
          )}
          {result.ai_context != null && (
            <AskAIPanel
              context={String(result.ai_context)}
              section={`etf-top-down/${String(result.ticker ?? '')}`}
            />
          )}
        </div>
      )}
    </div>
  )
}

export default function EtfTopDown() {
  const [preset, setPreset] = useState('Top ~55 (FIRE + ETF Shop)')
  const [customTickers, setCustomTickers] = useState('')
  const [topN, setTopN] = useState(20)
  const [renkoBox, setRenkoBox] = useState(1)
  const [pnfBox, setPnfBox] = useState(0.25)
  const [dSmart, setDSmart] = useState(10)
  const [filter, setFilter] = useState<'shortlist' | 'all' | 'buy' | 'sell' | 'hold'>('shortlist')
  const [showCharts, setShowCharts] = useState(false)
  const [error, setError] = useState('')

  const universeQ = useQuery({
    queryKey: ['etf-top-down-universe'],
    queryFn: fetchEtfTopDownUniverse,
    staleTime: 60_000,
  })

  const presets = universeQ.data?.presets ?? { 'Top ~55 (FIRE + ETF Shop)': [] }

  const buildPayload = useCallback(() => {
    const custom = customTickers
      .split(/[\s,;]+/)
      .map((t) => t.replace(/^NSE:/i, '').trim().toUpperCase())
      .filter(Boolean)
    return {
      preset: custom.length ? null : preset,
      tickers: custom,
      top_n: topN,
      renko_box_pct: renkoBox,
      pn_f_box_pct: pnfBox,
      d_smart_period: dSmart,
    }
  }, [customTickers, preset, topN, renkoBox, pnfBox, dSmart])

  const runMut = useMutation({
    mutationFn: () => runEtfTopDownScan(buildPayload()),
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Row | undefined
  const macro = (data?.macro_board as Row[] | undefined) ?? []
  const summary = (data?.summary as Row | undefined) ?? undefined
  const rebalance = (data?.rebalance_hint as Row | undefined) ?? undefined
  const results = (data?.results as Row[] | undefined) ?? []
  const askContext = data ? buildAskContext('ETF Top Down', data) : ''

  const filtered = useMemo(() => {
    if (filter === 'shortlist') return results.filter((r) => r.shortlisted)
    if (filter === 'buy') return results.filter((r) => r.action === 'BUY')
    if (filter === 'sell') return results.filter((r) => r.action === 'SELL')
    if (filter === 'hold') return results.filter((r) => r.action === 'HOLD')
    return results
  }, [results, filter])

  const presetCount = presets[preset]?.length ?? 0

  return (
    <div>
      <PageHeader
        title="ETF Top Down"
        description="Macro RS filter → Top 20 P&F scores → Renko + D-Smart 10 · weekly Friday rebalance"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={HOW_TO}>
          {HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {OVERVIEW}
        </CollapsibleSection>
        <p className="text-xs text-slate-500">
          ETF universe from{' '}
          <Link to="/etf-ta-in" className="text-sky-400 hover:underline">
            ETF Shop
          </Link>{' '}
          and{' '}
          <Link to="/etf-28-sma" className="text-sky-400 hover:underline">
            ETF 28 SMA
          </Link>
          .{' '}
          <a href={YOUTUBE} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-400 hover:underline">
            Video <ExternalLink size={11} />
          </a>
        </p>
      </div>

      <Card className="mb-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Universe preset</p>
        <div className="mb-3 flex flex-wrap gap-2">
          {Object.keys(presets).map((name) => (
            <Chip
              key={name}
              selected={preset === name && !customTickers.trim()}
              onClick={() => {
                setPreset(name)
                setCustomTickers('')
              }}
            >
              {name}
              {presets[name]?.length ? ` (${presets[name].length})` : ''}
            </Chip>
          ))}
        </div>

        <FormField label="Custom tickers (optional — overrides preset)">
          <Textarea
            rows={2}
            placeholder="NIFTYBEES SILVERBEES GOLDBEES …"
            value={customTickers}
            onChange={(e) => setCustomTickers(e.target.value)}
          />
        </FormField>

        <div className="mt-4 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Top N (score > 0)">
            <Input type="number" min={5} max={40} value={topN} onChange={(e) => setTopN(Number(e.target.value) || 20)} />
          </FormField>
          <FormField label="Renko box %">
            <Input type="number" step="0.25" min={0.25} max={5} value={renkoBox} onChange={(e) => setRenkoBox(Number(e.target.value) || 1)} />
          </FormField>
          <FormField label="P&F box %">
            <Input type="number" step="0.05" min={0.1} max={2} value={pnfBox} onChange={(e) => setPnfBox(Number(e.target.value) || 0.25)} />
          </FormField>
          <FormField label="D-Smart period">
            <Input type="number" min={5} max={20} value={dSmart} onChange={(e) => setDSmart(Number(e.target.value) || 10)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={showCharts} onClick={() => setShowCharts((v) => !v)}>
            Charts
          </Chip>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || universeQ.isLoading}>
            {runMut.isPending
              ? 'Scanning…'
              : `Scan ETF Top Down (${customTickers.trim() ? 'custom' : presetCount || '…'} ETFs)`}
          </Button>
        </div>
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Ranking macros, P&F RS scores, Renko × D-Smart…" />}

      {data && !runMut.isPending && (
        <>
          {macro.length > 0 && (
            <Card className="mb-4">
              <p className="mb-2 text-sm font-medium text-slate-200">Top-down macro board</p>
              <p className="mb-3 text-xs text-slate-500">
                Which asset class is dominating? (VIX / bond yields inverted so higher score = calmer / friendlier)
              </p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {macro.map((m) => (
                  <div
                    key={String(m.id)}
                    className={`rounded-lg border px-3 py-2 ${
                      m.rank === 1
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : 'border-slate-800/80 bg-slate-950/40'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-white">{String(m.label)}</span>
                      {m.rank != null && <span className="text-xs text-slate-400">#{String(m.rank)}</span>}
                    </div>
                    <p className="mt-1 text-xs text-slate-400">
                      {m.symbol != null ? String(m.symbol) : ''}
                      {m.ltp != null ? ` · ₹${fmtNum(m.ltp)}` : ''}
                    </p>
                    <p className="mt-1 text-sm font-semibold text-sky-200">
                      {m.total_score != null ? `RS ${fmtNum(m.total_score, 0)}` : String(m.error ?? '—')}
                    </p>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {rebalance && (
            <Card className="mb-4">
              <p className="text-sm text-slate-300">
                Weekly rebalance: <strong className="text-white">{String(rebalance.note)}</strong>
                {rebalance.is_friday_utc ? (
                  <span className="ml-2 text-xs text-emerald-300">Friday window (UTC)</span>
                ) : (
                  <span className="ml-2 text-xs text-amber-200">Not Friday UTC — still review, prefer Friday fills</span>
                )}
              </p>
            </Card>
          )}

          {summary && (
            <Card className="mb-4">
              <div className="mb-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-200">
                  {String(summary.shortlisted ?? 0)} shortlisted
                </span>
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-200">
                  {String(summary.buy ?? 0)} buy
                </span>
                <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-rose-200">
                  {String(summary.sell ?? 0)} sell
                </span>
                <span className="rounded-full border border-slate-700 px-2.5 py-1 text-slate-400">
                  {String(summary.hold ?? 0)} hold · {String(summary.scanned ?? 0)} scanned
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {(
                  [
                    ['shortlist', 'Shortlist'],
                    ['buy', 'Buys'],
                    ['sell', 'Sells'],
                    ['hold', 'Holds'],
                    ['all', 'All'],
                  ] as const
                ).map(([id, label]) => (
                  <Chip key={id} selected={filter === id} onClick={() => setFilter(id)}>
                    {label}
                  </Chip>
                ))}
              </div>
            </Card>
          )}

          <div className="mb-4 space-y-2">
            {filtered.map((r, i) => (
              <ResultCard key={`${r.ticker}-${i}`} result={r} index={i} showCharts={showCharts} />
            ))}
            {!filtered.length && (
              <Card>
                <p className="text-sm text-slate-400">No rows for this filter.</p>
              </Card>
            )}
          </div>

          {askContext && <AskAIPanel context={askContext} section="etf-top-down" />}
        </>
      )}
    </div>
  )
}
