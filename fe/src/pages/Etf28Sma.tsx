import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import {
  apiErrorMessage,
  fetchEtf28SmaUniverse,
  runEtf28SmaScan,
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

const HOW_TO = `How to use ETF 28 SMA Momentum

Source: FIRE in India — ETF 28 SMA Momentum Strategy

1. Pick a universe preset (FIRE curated list, ETF Shop 39, or Combined) or paste tickers.
2. Set total capital — the screen keeps 30% for averaging and splits the rest by max ETF slots.
3. Choose FIFO (sell whole block) or LIFO (sell cheap lots early). Tick "capital exhausted" for aggressive LIFO frees.
4. Optional: paste open lots as CSV lines: SYMBOL,buy_price,amount (one per line) for sell/average advice.
5. Scan near the close (after ~3:15 PM IST). Act on BUY (max 4/day), AVERAGE, SELL / SELL_LOT.
6. Prefer distinct underlyings — avoid two ETFs on the same index. Research only — not advice.`

const OVERVIEW = `ETF 28 SMA Momentum — rules

Capital: 30% averaging reserve; 70% ÷ max ETFs = initial buy size.
Entry: two consecutive closes above 28 SMA → buy on day 2 (max 4 new ETFs/day). Need ≥1 year history.
Exit: two closes below 28 SMA AND profit ≥ 3.14%. If breakdown but below 3.14% → hold.
Fast exit: >18% in ~1 month → sell on first red candle.
Average: fresh 2-day breakout ≥5% below last buy; amount = (fall%/2) × (initial/10).
FIFO = one block; LIFO = book the cheapest lot at +3.14% on a down-close.`

const LAYMAN = `In plain English

Wait for an ETF to close above its 28-day average two days in a row before buying.
Only sell after it closes below that average twice — and only if you already have at least ~3.14% profit.
If it crashes, don’t catch the knife: wait for another two-day breakout that is at least 5% cheaper, then average with a sized amount.
If price rockets >18% in a month, don’t wait for the slow average — sell on the first down day.`

function fmtInr(v: unknown) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: digits }) : '—'
}

function parseHoldingsText(text: string): Array<{ symbol: string; price: number; amount: number }> {
  const rows: Array<{ symbol: string; price: number; amount: number }> = []
  for (const line of text.split(/\r?\n/)) {
    const raw = line.trim()
    if (!raw || raw.startsWith('#')) continue
    const parts = raw.split(/[,\t ]+/).filter(Boolean)
    if (parts.length < 2) continue
    const symbol = parts[0].replace(/^NSE:/i, '').toUpperCase()
    const price = Number(parts[1])
    const amount = parts[2] != null ? Number(parts[2]) : price
    if (!symbol || !Number.isFinite(price) || price <= 0) continue
    rows.push({ symbol, price, amount: Number.isFinite(amount) && amount > 0 ? amount : price })
  }
  return rows
}

function ActionBadge({ action }: { action: string }) {
  const a = action.toUpperCase()
  const cls =
    a === 'BUY' || a === 'AVERAGE'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : a === 'SELL' || a === 'SELL_LOT'
        ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
        : a === 'HOLD' || a === 'WATCH'
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
          : a === 'BUY_DEFERRED'
            ? 'border-sky-500/40 bg-sky-500/10 text-sky-300'
            : 'border-slate-700/60 bg-slate-800/40 text-slate-400'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${cls}`}>
      {a}
    </span>
  )
}

function ResultCard({ result, index, showCharts }: { result: Row; index: number; showCharts: boolean }) {
  const [open, setOpen] = useState(index < 5 || Boolean(result.take_trade))
  const metrics = (result.metrics as Row | undefined) ?? {}
  const checks = (result.checks as Row[] | undefined) ?? []
  const lotsAdvice = (result.lots_advice as Row[] | undefined) ?? []
  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const series = useMemo<VpSeries[]>(
    () => (result.chart_series as VpSeries[] | undefined) ?? [{ key: 'sma28', label: 'SMA28', color: '#38bdf8' }],
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
        {result.ltp != null && <span className="text-sm text-slate-400">₹{fmtNum(result.ltp)}</span>}
        <ActionBadge action={String(result.action ?? 'WAIT')} />
        {metrics.pct_vs_sma != null && (
          <span className="text-xs text-slate-400">vs SMA28 {fmtNum(metrics.pct_vs_sma)}%</span>
        )}
        {metrics.pnl_pct != null && (
          <span className="text-xs text-slate-300">P&L {fmtNum(metrics.pnl_pct)}%</span>
        )}
        {metrics.suggested_amount != null && (
          <span className="text-xs text-emerald-300">
            Size {fmtInr(metrics.suggested_amount)}
            {metrics.suggested_qty != null ? ` · ${String(metrics.suggested_qty)} qty` : ''}
          </span>
        )}
        {result.buy_priority != null && (
          <span className="text-xs text-sky-300">Buy #{String(result.buy_priority)}</span>
        )}
        {result.error != null && <span className="text-xs text-amber-400">{String(result.error)}</span>}
      </button>
      {open && !result.error && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          {result.reason != null && (
            <p className="text-sm leading-relaxed text-slate-300">{String(result.reason)}</p>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {metrics.sma28 != null && (
              <span>
                SMA28: <strong className="text-slate-300">₹{fmtNum(metrics.sma28)}</strong>
              </span>
            )}
            {metrics.days_above_sma != null && (
              <span>
                Above: <strong className="text-slate-300">{String(metrics.days_above_sma)}d</strong>
              </span>
            )}
            {metrics.days_below_sma != null && (
              <span>
                Below: <strong className="text-slate-300">{String(metrics.days_below_sma)}d</strong>
              </span>
            )}
            {metrics.month_pct != null && (
              <span>
                ~1m: <strong className="text-slate-300">{fmtNum(metrics.month_pct)}%</strong>
              </span>
            )}
            {metrics.suggested_amount != null && (
              <span>
                Size: <strong className="text-emerald-300">{fmtInr(metrics.suggested_amount)}</strong>
              </span>
            )}
            {metrics.suggested_qty != null && (
              <span>
                Qty: <strong className="text-emerald-300">{String(metrics.suggested_qty)}</strong>
                {metrics.approx_cost != null ? (
                  <span className="text-slate-500"> (≈{fmtInr(metrics.approx_cost)})</span>
                ) : null}
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
          {lotsAdvice.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-slate-400">LIFO lots</p>
              {lotsAdvice.map((lot) => (
                <div
                  key={`${lot.lot_index}-${lot.buy_price}`}
                  className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                    lot.sell
                      ? 'border-rose-500/30 bg-rose-500/5 text-rose-200'
                      : 'border-slate-800/80 bg-slate-950/40 text-slate-400'
                  }`}
                >
                  Lot @ ₹{fmtNum(lot.buy_price)} · P&L {fmtNum(lot.pnl_pct)}%
                  {lot.is_latest ? ' · latest' : ''} — {String(lot.reason)}
                </div>
              ))}
            </div>
          )}
          {showCharts && chartData.length > 0 && (
            <VolumeProfileChart chartData={chartData} series={series} levels={levels} />
          )}
          {result.ai_context != null && (
            <AskAIPanel
              context={String(result.ai_context)}
              section={`etf-28-sma/${String(result.ticker ?? '')}`}
            />
          )}
        </div>
      )}
    </div>
  )
}

export default function Etf28Sma() {
  const [preset, setPreset] = useState('FIRE 28 SMA — curated list')
  const [customTickers, setCustomTickers] = useState('')
  const [totalCapital, setTotalCapital] = useState(500_000)
  const [reservePct, setReservePct] = useState(30)
  const [maxEtfs, setMaxEtfs] = useState(20)
  const [maxBuys, setMaxBuys] = useState(4)
  const [sellMode, setSellMode] = useState<'FIFO' | 'LIFO'>('FIFO')
  const [capitalExhausted, setCapitalExhausted] = useState(false)
  const [holdingsText, setHoldingsText] = useState('')
  const [filter, setFilter] = useState<'all' | 'actionable' | 'buy' | 'sell' | 'average' | 'hold'>('all')
  const [showCharts, setShowCharts] = useState(false)
  const [error, setError] = useState('')

  const universeQ = useQuery({
    queryKey: ['etf-28-sma-universe'],
    queryFn: fetchEtf28SmaUniverse,
    staleTime: 60_000,
  })

  const presets = universeQ.data?.presets ?? {
    'FIRE 28 SMA — curated list': [],
    'ETF Shop 4.0 — 39 distinct': [],
    'Combined (FIRE + ETF Shop)': [],
  }

  const buildPayload = useCallback(() => {
    const custom = customTickers
      .split(/[\s,;]+/)
      .map((t) => t.replace(/^NSE:/i, '').trim().toUpperCase())
      .filter(Boolean)
    return {
      preset: custom.length ? null : preset,
      tickers: custom,
      total_capital: totalCapital,
      averaging_reserve_pct: reservePct,
      max_etfs: maxEtfs,
      max_new_buys_per_day: maxBuys,
      sell_mode: sellMode,
      capital_exhausted: capitalExhausted,
      holdings: parseHoldingsText(holdingsText),
    }
  }, [
    customTickers,
    preset,
    totalCapital,
    reservePct,
    maxEtfs,
    maxBuys,
    sellMode,
    capitalExhausted,
    holdingsText,
  ])

  const runMut = useMutation({
    mutationFn: () => runEtf28SmaScan(buildPayload()),
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Row | undefined
  const capital = (data?.capital_plan as Row | undefined) ?? undefined
  const summary = (data?.summary as Row | undefined) ?? undefined
  const results = (data?.results as Row[] | undefined) ?? []
  const askContext = data ? buildAskContext('ETF 28 SMA', data) : ''

  const filtered = useMemo(() => {
    if (filter === 'all') return results
    if (filter === 'actionable') return results.filter((r) => r.take_trade)
    if (filter === 'buy') return results.filter((r) => ['BUY', 'BUY_DEFERRED'].includes(String(r.action)))
    if (filter === 'sell') return results.filter((r) => ['SELL', 'SELL_LOT'].includes(String(r.action)))
    if (filter === 'average') return results.filter((r) => r.action === 'AVERAGE')
    if (filter === 'hold') return results.filter((r) => ['HOLD', 'WATCH'].includes(String(r.action)))
    return results
  }, [results, filter])

  const presetCount = presets[preset]?.length ?? 0

  return (
    <div>
      <PageHeader
        title="ETF 28 SMA"
        description="FIRE momentum — 28 SMA two-close entry/exit · 3.14% floor · 5% average-down · FIFO/LIFO"
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
          Universe sourced from the FIRE curated list and{' '}
          <Link to="/etf-ta-in" className="text-sky-400 hover:underline">
            ETF Shop (ETF TA IN)
          </Link>
          . Execute near the close after ~3:15 PM IST.
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
            placeholder="NIFTYBEES BANKBEES GOLDBEES …"
            value={customTickers}
            onChange={(e) => setCustomTickers(e.target.value)}
          />
        </FormField>

        <div className="mt-4 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Total capital (₹)">
            <Input
              type="number"
              min={10000}
              value={totalCapital}
              onChange={(e) => setTotalCapital(Number(e.target.value) || 500_000)}
            />
          </FormField>
          <FormField label="Averaging reserve %">
            <Input
              type="number"
              min={0}
              max={90}
              value={reservePct}
              onChange={(e) => setReservePct(Number(e.target.value) || 30)}
            />
          </FormField>
          <FormField label="Max ETFs (slots)">
            <Input
              type="number"
              min={1}
              max={80}
              value={maxEtfs}
              onChange={(e) => setMaxEtfs(Number(e.target.value) || 20)}
            />
          </FormField>
          <FormField label="Max new buys / day">
            <Input
              type="number"
              min={1}
              max={10}
              value={maxBuys}
              onChange={(e) => setMaxBuys(Number(e.target.value) || 4)}
            />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={sellMode === 'FIFO'} onClick={() => setSellMode('FIFO')}>
            FIFO (sell all)
          </Chip>
          <Chip selected={sellMode === 'LIFO'} onClick={() => setSellMode('LIFO')}>
            LIFO (lot booking)
          </Chip>
          <Chip selected={capitalExhausted} onClick={() => setCapitalExhausted((v) => !v)}>
            Capital exhausted
          </Chip>
          <Chip selected={showCharts} onClick={() => setShowCharts((v) => !v)}>
            Charts
          </Chip>
        </div>

        <div className="mt-4">
          <FormField label="Open lots (optional) — SYMBOL,buy_price,amount per line">
            <Textarea
              rows={3}
              placeholder={'NIFTYBEES,250,15000\nBANKBEES,480,15000'}
              value={holdingsText}
              onChange={(e) => setHoldingsText(e.target.value)}
            />
          </FormField>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || universeQ.isLoading}>
            {runMut.isPending
              ? 'Scanning…'
              : `Scan ETF 28 SMA (${customTickers.trim() ? 'custom' : presetCount || '…'} ETFs)`}
          </Button>
          <a
            href="https://www.youtube.com/@FIREinIndia"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-sky-300"
          >
            FIRE in India <ExternalLink size={12} />
          </a>
        </div>
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Checking 28 SMA two-close setups, averages, FIFO/LIFO exits…" />}

      {data && !runMut.isPending && (
        <>
          {capital && (
            <Card className="mb-4">
              <p className="mb-2 text-sm font-medium text-slate-200">Capital plan</p>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <p className="text-xs text-slate-500">Initial pool (70%)</p>
                  <p className="text-lg font-semibold text-white">{fmtInr(capital.initial_pool)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Averaging reserve</p>
                  <p className="text-lg font-semibold text-amber-200">{fmtInr(capital.averaging_reserve)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Initial buy / ETF</p>
                  <p className="text-lg font-semibold text-emerald-300">{fmtInr(capital.initial_buy_amount)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">1/10th (avg unit)</p>
                  <p className="text-lg font-semibold text-slate-200">{fmtInr(capital.tenth_of_initial)}</p>
                </div>
              </div>
              <p className="mt-2 text-xs text-slate-500">{String(capital.note ?? '')}</p>
            </Card>
          )}

          {summary && (
            <Card className="mb-4">
              <div className="mb-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-200">
                  {String(summary.buy ?? 0)} buy
                </span>
                <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-amber-200">
                  {String(summary.average ?? 0)} average
                </span>
                <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-rose-200">
                  {String(summary.sell ?? 0)} sell
                </span>
                <span className="rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-400">
                  {String(summary.hold ?? 0)} hold · {String(summary.watch ?? 0)} watch
                </span>
                {Number(summary.buy_deferred) > 0 && (
                  <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-xs text-sky-200">
                    {String(summary.buy_deferred)} deferred (max {maxBuys}/day)
                  </span>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {(
                  [
                    ['all', 'All'],
                    ['actionable', 'Actionable'],
                    ['buy', 'Buys'],
                    ['average', 'Averages'],
                    ['sell', 'Sells'],
                    ['hold', 'Hold/Watch'],
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

          {askContext && <AskAIPanel context={askContext} section="etf-28-sma" />}
        </>
      )}
    </div>
  )
}
