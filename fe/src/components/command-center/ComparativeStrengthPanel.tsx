import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  apiErrorMessage,
  fetchComparativeStrengthPresets,
  fetchTickerSuggestions,
  runComparativeStrength,
} from '../../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from './AssetClassTickerPicker'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../analysis/AnalysisBackground'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Alert, Loading } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { StrategyDataSourceBar } from '../ui/StrategyDataSourceBar'
import { FormField, Input, Select } from '../ui/Form'
import { StatCard } from '../ui/StatCard'
import { HowToBox } from '../ui/CopyAllButton'

type Row = Record<string, unknown>

const CS_HOW_TO = `Comparative Strength — How to

How to run
1. Select asset class (India / US / Crypto / Commodity).
2. Pick a base from presets or type a symbol (NIFTY 50, SPY, BTC…).
3. Add one or more compare tickers in the picker.
4. Choose timeframe (1m→1w) and lookback bars (how many bars of relative return).
5. Click Run comparative strength (or queue in background).
6. Click a peer row to see the cumulative return chart vs the base; use AI View for the best relative long/short.

What “compare ticker” means
- Base = the benchmark (e.g. NIFTY 50).
- Compare ticker = each stock you picked to rank against the base (e.g. TECHM).
- LONG TECHM vs NIFTY 50 means TECHM beat the base on a relative basis — prefer buying/holding TECHM, not longing the index itself.

How to read the table
- STRONGER — compare ticker beat the base (positive RS %). Lean LONG that ticker.
- WEAKER — compare ticker lagged the base. Lean SHORT that ticker (or overweight the base).
- INLINE — roughly matched the base; no strong relative edge.
- %SL / %TP — ATR-based educational stop and target on the compare ticker (~2:1 R:R).
- Confidence % — higher when RS is large, horizons agree, CRS / EMA / volume support the lean.

Playbook tips
- Prefer LONG leaders only when Advance Decline shows a healthy tape on the base universe.
- Prefer SHORT laggards when breadth is weak (A/D < 1, downtrend) and the peer is even weaker.
- Use daily/weekly for swing pairs; 15m–1h for intraday relative scalps.
- Educational lean only — not a broker order ticket.

Pair with
Advance Decline · Weak / Strong · Detect Sector Rotation · Take Trade / One-Click for timing.`

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'] as const
const LOOKBACKS = [5, 10, 20, 40, 60] as const

function fmtPct(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function actionTone(action: string): string {
  if (action === 'LONG') return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
  if (action === 'SHORT') return 'bg-rose-500/15 text-rose-300 border-rose-500/30'
  if (action.includes('LONG')) return 'bg-emerald-500/10 text-emerald-400/90 border-emerald-500/20'
  if (action.includes('SHORT')) return 'bg-rose-500/10 text-rose-400/90 border-rose-500/20'
  return 'bg-slate-500/10 text-slate-300 border-slate-600/40'
}

function statusTone(status: string): string {
  if (status === 'STRONGER') return 'text-emerald-300'
  if (status === 'WEAKER') return 'text-rose-300'
  if (status === 'INLINE') return 'text-slate-300'
  return 'text-amber-300'
}

function SpreadChart({ row, base }: { row: Row; base: string }) {
  const series = (row.series as Row[]) ?? []
  if (!series.length) return null
  return (
    <div className="mt-3 h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={24} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} width={40} unit="%" />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#e2e8f0' }}
          />
          <Legend />
          <Line type="monotone" dataKey="peer_cum_pct" name={String(row.symbol)} stroke="#34d399" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="base_cum_pct" name={base} stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
          <Line type="monotone" dataKey="spread_pct" name="RS spread" stroke="#fbbf24" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ComparativeStrengthPanel() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [basePreset, setBasePreset] = useState('')
  const [baseSymbol, setBaseSymbol] = useState('NIFTY 50')
  const [baseQuery, setBaseQuery] = useState('')
  const [compare, setCompare] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [timeframe, setTimeframe] = useState('1d')
  const [lookback, setLookback] = useState(20)
  const [selectedPeer, setSelectedPeer] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [showHow, setShowHow] = useState(false)
  const bg = useAnalysisBackground('command_center', 'comparative_strength')

  const presetsQuery = useQuery({
    queryKey: ['comparative-strength-presets', assetClass],
    queryFn: () => fetchComparativeStrengthPresets(assetClass),
    staleTime: 60_000,
  })

  const suggestQuery = useQuery({
    queryKey: ['cs-base-suggest', assetClass, baseQuery],
    queryFn: () => fetchTickerSuggestions(assetClass, baseQuery, 20),
    enabled: baseQuery.trim().length >= 1,
    staleTime: 20_000,
  })

  useEffect(() => {
    const presets = presetsQuery.data?.presets ?? []
    if (!presets.length) return
    if (presetsQuery.data?.asset_class && presetsQuery.data.asset_class !== assetClass) return
    const first = presets[0]
    setBasePreset(first.symbol)
    setBaseSymbol(first.symbol)
  }, [assetClass, presetsQuery.data])

  const buildPayload = () => ({
    asset_class: assetClass,
    base_symbol: baseSymbol.trim(),
    compare_symbols: compare.tickers,
    timeframe,
    lookback_bars: lookback,
  })

  const runMut = useMutation({
    mutationFn: () => runComparativeStrength(buildPayload()),
    onSuccess: (data) => {
      setError('')
      bg.setViewedReportId(null)
      const rows = ((data as Row)?.rows as Row[]) ?? []
      const firstOk = rows.find((r) => r.status === 'STRONGER' || r.status === 'WEAKER' || r.status === 'INLINE')
      setSelectedPeer(firstOk ? String(firstOk.symbol) : null)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Row | undefined
  const rows = useMemo(() => ((data?.rows as Row[]) ?? []), [data])
  const stronger = useMemo(() => ((data?.stronger as Row[]) ?? []), [data])
  const weaker = useMemo(() => ((data?.weaker as Row[]) ?? []), [data])
  const ideas = useMemo(() => ((data?.trade_ideas as Row[]) ?? []), [data])
  const howTo = useMemo(() => ((data?.how_to_read as string[]) ?? []), [data])
  const chartRow = rows.find((r) => String(r.symbol) === selectedPeer) ?? rows[0]
  const askContext = data ? buildAskContext('Comparative Strength', data) : ''

  useEffect(() => {
    if (!data || Boolean(data.error)) return
    const r = ((data.rows as Row[]) ?? [])
    const firstOk = r.find((row) => row.status === 'STRONGER' || row.status === 'WEAKER' || row.status === 'INLINE')
    if (firstOk) setSelectedPeer(String(firstOk.symbol))
  }, [data])

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-relaxed text-slate-300">
              Pick a <strong className="text-white">base</strong> index or stock, then one or more{' '}
              <strong className="text-white">compare</strong> tickers. The scan ranks who is{' '}
              <strong className="text-emerald-300">stronger</strong> / <strong className="text-rose-300">weaker</strong>{' '}
              than the base by relative % and suggests LONG / SHORT leans with confidence.
            </p>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              Relative strength % = compare-ticker return − base return. Positive means the compare ticker beat the base.
              Confidence blends RS size, multi-horizon agreement, CRS slope, EMA stack, and volume. Educational only.
            </p>
          </div>
          <button
            type="button"
            className="shrink-0 text-xs text-slate-400 hover:text-white"
            onClick={() => setShowHow((v) => !v)}
          >
            {showHow ? 'Hide guide' : 'How to'}
          </button>
        </div>

        {showHow && (
          <HowToBox copyText={CS_HOW_TO} className="space-y-3">
            <div>
              <p className="mb-1.5 font-medium text-slate-200">How to run</p>
              <ol className="list-decimal space-y-1 pl-4">
                <li>Select <span className="text-slate-300">asset class</span> (India / US / Crypto / Commodity).</li>
                <li>Pick a <span className="text-slate-300">base</span> from presets or type a symbol (NIFTY 50, SPY, BTC…).</li>
                <li>Add one or more <span className="text-slate-300">compare</span> tickers in the picker.</li>
                <li>Choose <span className="text-slate-300">timeframe</span> (1m→1w) and <span className="text-slate-300">lookback bars</span> (how many bars of relative return).</li>
                <li>Click <span className="text-slate-300">Run comparative strength</span> (or queue in background).</li>
                <li>Click a peer row to see the cumulative return chart vs the base; use <span className="text-slate-300">AI View</span> for the best relative long/short.</li>
              </ol>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">What “compare ticker” means</p>
              <ul className="list-disc space-y-1 pl-4">
                <li><span className="text-slate-300">Base</span> = the benchmark (e.g. NIFTY 50).</li>
                <li><span className="text-slate-300">Compare ticker</span> = each stock you picked to rank against the base (e.g. TECHM). Older copy said “peer” — same thing.</li>
                <li>
                  <span className="text-emerald-300">LONG TECHM vs NIFTY 50</span> means: TECHM beat the base on a relative basis —
                  prefer buying / holding <span className="text-slate-300">TECHM</span>, not longing the index itself.
                </li>
                <li>
                  Timing tip: buy pullbacks in TECHM; use weakness in NIFTY 50 or TECHM’s own EMA as entry timing.
                </li>
              </ul>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">How to read the table</p>
              <ul className="list-disc space-y-1 pl-4">
                <li><span className="text-emerald-300">STRONGER</span> — compare ticker beat the base (positive RS %). Lean <span className="text-emerald-300">LONG</span> that ticker.</li>
                <li><span className="text-rose-300">WEAKER</span> — compare ticker lagged the base. Lean <span className="text-rose-300">SHORT</span> that ticker (or overweight the base).</li>
                <li><span className="text-slate-300">INLINE</span> — roughly matched the base; no strong relative edge.</li>
                <li><span className="text-slate-300">%SL / %TP</span> — ATR-based educational stop and target on the compare ticker (~2:1 R:R).</li>
                <li><span className="text-slate-300">Confidence %</span> — higher when RS is large, horizons agree, CRS / EMA / volume support the lean.</li>
              </ul>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">Playbook tips</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>Prefer LONG leaders only when <span className="text-slate-300">Advance Decline</span> shows a healthy tape on the base universe.</li>
                <li>Prefer SHORT laggards when breadth is weak (A/D &lt; 1, downtrend) and the peer is even weaker.</li>
                <li>Use daily/weekly for swing pairs; 15m–1h for intraday relative scalps.</li>
                <li>Educational lean only — not a broker order ticket. Always set your own SL/TP.</li>
              </ul>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">Pair with</p>
              <p>
                <span className="text-slate-300">Advance Decline</span> (is the advance healthy?) ·{' '}
                <span className="text-slate-300">Weak / Strong</span> ·{' '}
                <span className="text-slate-300">Detect Sector Rotation</span> ·{' '}
                <span className="text-slate-300">Take Trade / One-Click</span> for timing.
              </p>
            </div>
          </HowToBox>
        )}

        <div className="grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Asset class">
            <Select
              value={assetClass}
              onChange={(e) => {
                setAssetClass(e.target.value as AssetClass)
                setCompare({ tickers: [], durations: ['1d'] })
              }}
            >
              <option value="india">India</option>
              <option value="us">US</option>
              <option value="crypto">Crypto</option>
              <option value="commodity">Commodity</option>
            </Select>
          </FormField>
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </Select>
          </FormField>
          <FormField label="Lookback bars">
            <Select value={String(lookback)} onChange={(e) => setLookback(Number(e.target.value))}>
              {LOOKBACKS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          </FormField>
          <FormField label="Base preset">
            <Select
              value={basePreset}
              onChange={(e) => {
                const v = e.target.value
                setBasePreset(v)
                setBaseSymbol(v)
              }}
            >
              {(presetsQuery.data?.presets ?? [{ symbol: baseSymbol, label: baseSymbol }]).map((p) => (
                <option key={p.symbol} value={p.symbol}>{p.label}</option>
              ))}
            </Select>
          </FormField>
        </div>

        <div className="mt-3 grid max-w-5xl gap-3 lg:grid-cols-2">
          <FormField label="Base index / stock">
            <Input
              value={baseSymbol}
              onChange={(e) => {
                setBaseSymbol(e.target.value.toUpperCase())
                setBaseQuery(e.target.value)
              }}
              placeholder="e.g. NIFTY 50 · RELIANCE · SPY · BTC"
            />
            {Boolean(suggestQuery.data?.tickers?.length) && baseQuery.trim() && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(suggestQuery.data?.tickers ?? []).slice(0, 8).map((t) => (
                  <Chip
                    key={t}
                    selected={baseSymbol === t}
                    onClick={() => {
                      setBaseSymbol(t)
                      setBasePreset(t)
                      setBaseQuery('')
                    }}
                  >
                    {t}
                  </Chip>
                ))}
              </div>
            )}
          </FormField>
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              Compare tickers (one or more)
            </p>
            <AssetClassTickerPicker
              assetClass={assetClass}
              showDurations={false}
              defaultSelectCount={15}
              onChange={setCompare}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !baseSymbol.trim() || compare.tickers.length === 0 || bg.runInBackground}
          >
            {runMut.isPending ? 'Comparing strength…' : 'Run Comparative Strength'}
          </Button>
          {compare.tickers.length > 0 && (
            <span className="text-xs text-slate-500">
              {compare.tickers.length} peer{compare.tickers.length === 1 ? '' : 's'} selected
            </span>
          )}
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Comparative Strength · ${baseSymbol || 'base'} · ${timeframe} · ${new Date().toLocaleDateString()}`}
          onStart={() =>
            bg.startBackground(buildPayload(), () => {
              if (!baseSymbol.trim()) return 'Enter a base index or stock'
              if (!compare.tickers.length) return 'Select at least one compare ticker'
              return null
            })
          }
        />

        {(error || runMut.isError) && (
          <div className="mt-3">
            <Alert type="error">{error || apiErrorMessage(runMut.error)}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && (
        <Loading message="Fetching OHLC and ranking relative strength…" />
      )}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          {bg.viewedReportMeta?.name && (
            <p className="text-sm text-slate-400">
              Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
            </p>
          )}
          {Boolean(data.error) && <Alert type="error">{String(data.error)}</Alert>}

          {!data.error && (
            <Card className="space-y-4">
              <StrategyDataSourceBar data={data} assetClass={assetClass} />
              <div className="rounded-xl border border-slate-700/50 bg-slate-950/40 px-3 py-3 text-sm text-slate-300">
                <p className="font-medium text-slate-100">Results in plain English</p>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">{String(data.summary ?? '')}</p>
                {howTo.length > 0 && (
                  <ul className="mt-2 space-y-0.5 border-t border-slate-800/60 pt-2">
                    {howTo.map((line) => (
                      <li key={line} className="text-xs text-slate-500">· {line}</li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard label="Base" value={String(data.base_symbol ?? baseSymbol)} />
                <StatCard
                  label="Base return"
                  value={fmtPct(data.base_return_pct)}
                  trend={Number(data.base_return_pct) >= 0 ? 'up' : 'down'}
                />
                <StatCard label="Stronger / Weaker" value={`${stronger.length} / ${weaker.length}`} />
                <StatCard label="Trade ideas" value={String(ideas.length)} />
              </div>

              {ideas.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium text-slate-200">Trade opportunities</p>
                  <p className="text-[11px] text-slate-500">
                    Compare ticker = the stock named in the card (not the base). %SL / %TP are ATR-based educational levels on that ticker.
                  </p>
                  <div className="grid gap-2 lg:grid-cols-2">
                    {ideas.slice(0, 6).map((idea) => {
                      const ticker = String(idea.ticker ?? idea.symbol ?? '')
                      const baseT = String(idea.base_ticker ?? data.base_symbol ?? baseSymbol)
                      return (
                        <div
                          key={`${ticker}-${String(idea.action)}`}
                          className={`rounded-lg border px-3 py-2.5 ${actionTone(String(idea.action))}`}
                        >
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <p className="font-semibold">
                              {String(idea.action)} · Ticker {ticker}
                            </p>
                            <p className="text-xs tabular-nums">
                              RS {fmtPct(idea.relative_strength_pct)} · conf {fmtNum(idea.confidence_pct, 0)}%
                            </p>
                          </div>
                          <p className="mt-1 text-[11px] opacity-90">
                            vs base <span className="font-medium">{baseT}</span>
                            {idea.sl_pct != null && idea.tp_pct != null && (
                              <>
                                {' · '}
                                <span className="font-semibold">%SL {fmtNum(idea.sl_pct, 2)}%</span>
                                {' · '}
                                <span className="font-semibold">%TP {fmtNum(idea.tp_pct, 2)}%</span>
                                {idea.rr_ratio != null && <> · R:R {fmtNum(idea.rr_ratio, 1)}</>}
                              </>
                            )}
                          </p>
                          {(idea.entry_price != null || idea.stop_price != null || idea.target_price != null) && (
                            <p className="mt-0.5 text-[11px] tabular-nums opacity-80">
                              Entry {fmtNum(idea.entry_price, 2)}
                              {idea.stop_price != null && <> · SL {fmtNum(idea.stop_price, 2)}</>}
                              {idea.target_price != null && <> · TP {fmtNum(idea.target_price, 2)}</>}
                            </p>
                          )}
                          <p className="mt-1 text-xs opacity-90">{String(idea.thesis ?? '')}</p>
                          {Array.isArray(idea.reasons) && (idea.reasons as string[]).length > 0 && (
                            <ul className="mt-1.5 space-y-0.5">
                              {(idea.reasons as string[]).slice(0, 3).map((r) => (
                                <li key={r} className="text-[11px] opacity-80">· {r}</li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              <div className="overflow-x-auto rounded-lg border border-slate-800/60">
                <table className="min-w-full text-left text-xs text-slate-300">
                  <thead className="bg-slate-950/60 text-[11px] uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Ticker</th>
                      <th className="px-3 py-2">vs base</th>
                      <th className="px-3 py-2">RS %</th>
                      <th className="px-3 py-2">Compare %</th>
                      <th className="px-3 py-2">Base %</th>
                      <th className="px-3 py-2">CRS slope</th>
                      <th className="px-3 py-2">Trend</th>
                      <th className="px-3 py-2">Idea</th>
                      <th className="px-3 py-2">%SL</th>
                      <th className="px-3 py-2">%TP</th>
                      <th className="px-3 py-2">Conf</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...stronger, ...weaker, ...((data.inline as Row[]) ?? []), ...rows.filter((r) => r.status === 'ERROR')].map((row) => {
                      const trade = (row.trade as Row | undefined) ?? {}
                      const sym = String(row.symbol)
                      const sl = trade.sl_pct ?? row.sl_pct
                      const tp = trade.tp_pct ?? row.tp_pct
                      return (
                        <tr
                          key={sym}
                          className={`cursor-pointer border-t border-slate-800/50 hover:bg-slate-900/50 ${selectedPeer === sym ? 'bg-slate-900/70' : ''}`}
                          onClick={() => setSelectedPeer(sym)}
                        >
                          <td className="px-3 py-2 font-mono text-slate-100">{sym}</td>
                          <td className={`px-3 py-2 font-medium ${statusTone(String(row.status))}`}>
                            {String(row.status ?? '—')}
                          </td>
                          <td className={`px-3 py-2 tabular-nums font-medium ${Number(row.relative_strength_pct) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                            {fmtPct(row.relative_strength_pct)}
                          </td>
                          <td className="px-3 py-2 tabular-nums">{fmtPct(row.compare_return_pct ?? row.peer_return_pct)}</td>
                          <td className="px-3 py-2 tabular-nums">{fmtPct(row.base_return_pct)}</td>
                          <td className="px-3 py-2 tabular-nums">{fmtPct(row.crs_slope_pct)}</td>
                          <td className="px-3 py-2">{String((row.peer_trend as Row | undefined)?.bias ?? '—')}</td>
                          <td className="px-3 py-2">
                            <span className={`rounded border px-1.5 py-0.5 text-[10px] ${actionTone(String(trade.action ?? 'WAIT'))}`}>
                              {String(trade.action ?? (row.error ? 'ERR' : 'WAIT'))}
                            </span>
                          </td>
                          <td className="px-3 py-2 tabular-nums">{sl != null ? `${fmtNum(sl, 2)}%` : '—'}</td>
                          <td className="px-3 py-2 tabular-nums">{tp != null ? `${fmtNum(tp, 2)}%` : '—'}</td>
                          <td className="px-3 py-2 tabular-nums">{trade.confidence_pct != null ? `${fmtNum(trade.confidence_pct, 0)}%` : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {chartRow && !chartRow.error && (
                <div>
                  <p className="mb-1 text-sm font-medium text-slate-200">
                    Cumulative return · {String(chartRow.symbol)} vs {String(data.base_symbol)}
                  </p>
                  <p className="text-[11px] text-slate-500">{String(chartRow.plain_english ?? '')}</p>
                  <SpreadChart row={chartRow} base={String(data.base_symbol)} />
                </div>
              )}

              {askContext && (
                <AskAIPanel
                  title="AI View"
                  section="Comparative Strength"
                  context={askContext}
                  defaultQuestion="Which relative long/short has the best risk/reward vs the base, and what invalidates it?"
                />
              )}
            </Card>
          )}
        </>
      )}
    </div>
  )
}
