import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
  Cell,
} from 'recharts'
import {
  apiErrorMessage,
  fetchAdvanceDeclineGraphIndices,
  runAdvanceDeclineGraph,
} from '../../api/client'
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

const AD_HOW_TO = `Advance Decline — How to

How to run
1. Pick asset class: India, US, Crypto, or Commodity.
2. Choose an index / universe (e.g. NIFTY 50, Dow 30, Top 30 Crypto, All Commodities / Energy complex).
3. Set From / To for the daily breadth chart.
4. Leave timeframe on Daily, or pick an intraday TF + session date (optional as-of time).
5. Click Plot Advance / Decline. Wait for constituent candles + (India F&O) options snapshot.
6. Optional: open AI View for a healthy-vs-hollow verdict.

How to read the chart
- A/D ratio > 1 — more stocks rose than fell (green bars). Below 1 = decline-led (red).
- Volume ratio > 1 — more names got busier; below 1 = quiet / thin participation.
- UPTREND + rising strength — breadth improving and decisive.
- RSI — internals hot (>60) or washed out (<40). Mid ~50 is neutral.
- Dashed line at 1.0 = even for A/D and volume ratios; RSI mid = 50.

Healthy vs hollow
- Healthy advance — A/D > 1 and volume ratio > 1 and uptrend (optionally PCR > 1 on India F&O).
- Hollow rally — A/D > 1 but volume ratio < 1 (price up without participation).
- Confirmed selloff — A/D < 1 with volume expanding and downtrend.

Options block (India F&O only)
On Nifty / Bank Nifty / Fin Nifty / Midcap / Next 50 the panel adds PCR (OI & Vol), Call/Put OI, max pain, and OI support/resistance. PCR > 1 with A/D > 1 often confirms a healthier bullish tape; PCR < 0.8 with rising A/D can mean a short-covering / hollow rally. US, Crypto, and Commodity show breadth only.

Pair with
Comparative Strength (who leads the base) · Option Chain (full PCR deep dive) · Market Heatmap (visual constituents).`
type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

const INTRADAY_TFS = ['5m', '10m', '15m', '30m', '1h'] as const
const ASSET_OPTIONS: { id: AssetClass; label: string }[] = [
  { id: 'india', label: 'India' },
  { id: 'us', label: 'US' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'commodity', label: 'Commodity' },
]
const DEFAULT_INDEX: Record<AssetClass, string> = {
  india: 'NIFTY 50',
  us: 'Dow 30',
  crypto: 'Top 30 Crypto',
  commodity: 'All Commodities',
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function fmtNum(v: unknown, digits = 0): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function withChartRatio(series: Row[]): Row[] {
  return series.map((row) => {
    const ratio = row.ad_ratio != null ? Number(row.ad_ratio) : null
    const volRatio = row.vol_ratio != null ? Number(row.vol_ratio) : null
    const rsi = row.rsi != null ? Number(row.rsi) : null
    const strength = row.strength != null ? Number(row.strength) : null
    const trendScore = row.trend_score != null ? Number(row.trend_score) : null
    return {
      ...row,
      ad_ratio: ratio != null && Number.isFinite(ratio) ? ratio : null,
      vol_ratio: volRatio != null && Number.isFinite(volRatio) ? volRatio : null,
      rsi: rsi != null && Number.isFinite(rsi) ? rsi : null,
      strength: strength != null && Number.isFinite(strength) ? strength : null,
      /** Map trend_score (-100..100) → 0..100 for overlay on RSI axis (50 = flat) */
      trend_overlay:
        trendScore != null && Number.isFinite(trendScore) ? Math.max(0, Math.min(100, 50 + trendScore / 2)) : null,
    }
  })
}

function AdRatioChart({
  series,
  title,
  xKey = 'label',
}: {
  series: Row[]
  title: string
  xKey?: string
}) {
  const chartData = useMemo(() => withChartRatio(series), [series])
  if (!chartData.length) {
    return <p className="text-sm text-slate-500">No points to chart yet.</p>
  }

  const ratios = chartData
    .flatMap((r) => [Number(r.ad_ratio), Number(r.vol_ratio)])
    .filter((n) => Number.isFinite(n))
  const yMax = Math.min(10, Math.max(2, ...(ratios.length ? ratios : [2]), 1.2))
  const latest = chartData[chartData.length - 1]
  const latestRatio = latest?.ad_ratio != null ? Number(latest.ad_ratio) : null
  const latestVol = latest?.vol_ratio != null ? Number(latest.vol_ratio) : null
  const latestRsi = latest?.rsi != null ? Number(latest.rsi) : null
  const latestStrength = latest?.strength != null ? Number(latest.strength) : null
  const latestTrend = latest?.trend != null ? String(latest.trend) : null
  const latestAdv = latest?.advances != null ? Number(latest.advances) : null
  const latestDec = latest?.declines != null ? Number(latest.declines) : null
  const latestUnch = latest?.unchanged != null ? Number(latest.unchanged) : null

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slate-200">{title}</p>
        <div className="flex flex-wrap gap-3 text-xs text-slate-400">
          {(latestAdv != null || latestDec != null) && (
            <span>
              Adv/Dec:{' '}
              <strong className="text-emerald-300">{fmtNum(latestAdv)}</strong>
              <span className="text-slate-500"> / </span>
              <strong className="text-rose-300">{fmtNum(latestDec)}</strong>
              {latestUnch != null && (
                <span className="text-slate-500"> · flat {fmtNum(latestUnch)}</span>
              )}
            </span>
          )}
          {latestRatio != null && (
            <span>
              A/D:{' '}
              <strong className={latestRatio >= 1 ? 'text-emerald-300' : 'text-rose-300'}>
                {fmtNum(latestRatio, 2)}
              </strong>
            </span>
          )}
          {latestVol != null && (
            <span>
              Vol:{' '}
              <strong className={latestVol >= 1 ? 'text-amber-300' : 'text-slate-400'}>
                {fmtNum(latestVol, 2)}
              </strong>
            </span>
          )}
          {latestTrend != null && (
            <span>
              Trend:{' '}
              <strong
                className={
                  latestTrend === 'UPTREND'
                    ? 'text-sky-300'
                    : latestTrend === 'DOWNTREND'
                      ? 'text-rose-300'
                      : 'text-slate-300'
                }
              >
                {latestTrend}
              </strong>
            </span>
          )}
          {latestStrength != null && (
            <span>
              Strength: <strong className="text-orange-300">{fmtNum(latestStrength, 0)}</strong>
            </span>
          )}
          {latestRsi != null && (
            <span>
              RSI:{' '}
              <strong
                className={
                  latestRsi >= 60 ? 'text-cyan-300' : latestRsi <= 40 ? 'text-fuchsia-300' : 'text-slate-300'
                }
              >
                {fmtNum(latestRsi, 1)}
              </strong>
            </span>
          )}
        </div>
      </div>
      <div className="h-96 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 8, right: 48, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey={xKey} tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={28} />
            <YAxis
              yAxisId="ratio"
              domain={[0, yMax]}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              width={44}
              label={{ value: 'Ratio', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
            />
            <YAxis
              yAxisId="osc"
              orientation="right"
              domain={[0, 100]}
              tick={{ fill: '#64748b', fontSize: 10 }}
              width={40}
              label={{ value: 'RSI / Strength', angle: 90, position: 'insideRight', fill: '#64748b', fontSize: 10 }}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const row = payload[0]?.payload as Row | undefined
                if (!row) return null
                return (
                  <div className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-xs text-slate-200">
                    <p className="mb-1 font-medium text-white">{String(label)}</p>
                    <p>
                      A/D ratio:{' '}
                      <strong className={Number(row.ad_ratio) >= 1 ? 'text-emerald-300' : 'text-rose-300'}>
                        {fmtNum(row.ad_ratio, 2)}
                      </strong>
                      <span className="text-slate-500">
                        {' '}({fmtNum(row.advances)}↑ / {fmtNum(row.declines)}↓)
                      </span>
                    </p>
                    <p>
                      Vol ratio:{' '}
                      <strong className={Number(row.vol_ratio) >= 1 ? 'text-amber-300' : 'text-slate-300'}>
                        {fmtNum(row.vol_ratio, 2)}
                      </strong>
                    </p>
                    <p>
                      Trend:{' '}
                      <strong className="text-sky-300">{String(row.trend ?? '—')}</strong>
                      <span className="text-slate-500"> (score {fmtNum(row.trend_score, 0)})</span>
                    </p>
                    <p>
                      Strength: <strong className="text-orange-300">{fmtNum(row.strength, 0)}</strong>
                      <span className="text-slate-500"> / 100</span>
                    </p>
                    <p>
                      RSI: <strong className="text-cyan-300">{fmtNum(row.rsi, 1)}</strong>
                      {row.pct_uptrend != null && (
                        <span className="text-slate-500"> · {fmtNum(row.pct_uptrend, 0)}% above EMA</span>
                      )}
                    </p>
                  </div>
                )
              }}
            />
            <Legend />
            <ReferenceLine
              yAxisId="ratio"
              y={1}
              stroke="#94a3b8"
              strokeDasharray="4 4"
              label={{ value: '1.0 even', fill: '#94a3b8', fontSize: 10, position: 'insideTopRight' }}
            />
            <ReferenceLine yAxisId="osc" y={50} stroke="#475569" strokeDasharray="3 3" />
            <Bar yAxisId="ratio" dataKey="ad_ratio" name="A/D ratio" fill="#34d399" radius={[3, 3, 0, 0]}>
              {chartData.map((row, i) => {
                const r = Number(row.ad_ratio)
                const bullish = Number.isFinite(r) && r >= 1
                return (
                  <Cell
                    key={`${String(row[xKey])}-${i}`}
                    fill={bullish ? '#34d399' : '#f87171'}
                    fillOpacity={0.45}
                  />
                )
              })}
            </Bar>
            <Line
              yAxisId="ratio"
              type="monotone"
              dataKey="ad_ratio"
              name="A/D trend"
              stroke="#a78bfa"
              strokeWidth={2}
              dot={{ r: 2, fill: '#c4b5fd' }}
              connectNulls
              legendType="line"
            />
            <Line
              yAxisId="ratio"
              type="monotone"
              dataKey="vol_ratio"
              name="Volume ratio"
              stroke="#fbbf24"
              strokeWidth={2}
              dot={{ r: 2, fill: '#fcd34d' }}
              connectNulls
              legendType="line"
            />
            <Line
              yAxisId="osc"
              type="monotone"
              dataKey="rsi"
              name="RSI"
              stroke="#22d3ee"
              strokeWidth={2}
              dot={false}
              connectNulls
              legendType="line"
            />
            <Line
              yAxisId="osc"
              type="monotone"
              dataKey="strength"
              name="Strength"
              stroke="#fb923c"
              strokeWidth={2}
              dot={false}
              connectNulls
              legendType="line"
            />
            <Line
              yAxisId="osc"
              type="monotone"
              dataKey="trend_overlay"
              name="Trend score"
              stroke="#38bdf8"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              connectNulls
              legendType="line"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-slate-500">
        Left axis: A/D (green/red + violet) and volume ratio (amber). Right axis: RSI (cyan), strength (orange),
        trend score (sky, 50 = flat). Uptrend + rising strength + RSI recovering from &lt;40 supports a healthier advance.
      </p>
    </div>
  )
}

export function AdvanceDeclineGraphPanel() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [indexName, setIndexName] = useState(DEFAULT_INDEX.india)
  const [fromDate, setFromDate] = useState(isoDaysAgo(30))
  const [toDate, setToDate] = useState(todayIso())
  const [timeframe, setTimeframe] = useState('1d')
  const [sessionDate, setSessionDate] = useState(todayIso())
  const [asOfTime, setAsOfTime] = useState('')
  const [showHow, setShowHow] = useState(false)

  const indicesQuery = useQuery({
    queryKey: ['advance-decline-graph-indices', assetClass],
    queryFn: () => fetchAdvanceDeclineGraphIndices(assetClass),
    staleTime: 60_000,
  })

  useEffect(() => {
    const names = indicesQuery.data?.index_names ?? []
    if (!names.length) return
    if (indicesQuery.data?.asset_class && indicesQuery.data.asset_class !== assetClass) return
    if (!names.includes(indexName)) {
      setIndexName(names[0] ?? DEFAULT_INDEX[assetClass])
    }
  }, [assetClass, indicesQuery.data, indexName])

  const tzHint =
    assetClass === 'us' || assetClass === 'commodity'
      ? 'ET'
      : assetClass === 'crypto'
        ? 'UTC'
        : 'IST'

  const runMut = useMutation({
    mutationFn: () =>
      runAdvanceDeclineGraph({
        asset_class: assetClass,
        index_name: indexName,
        from_date: fromDate,
        to_date: toDate,
        timeframe,
        session_date: timeframe !== '1d' ? sessionDate || toDate : undefined,
        as_of_time: timeframe !== '1d' && asOfTime.trim() ? asOfTime.trim() : undefined,
      }),
  })

  const data = runMut.data as Row | undefined
  const daily = useMemo(() => ((data?.daily as Row[]) ?? []), [data])
  const intraday = useMemo(() => ((data?.intraday as Row[]) ?? []), [data])
  const latest = (data?.latest as Row | undefined) ?? null
  const isIntraday = timeframe !== '1d'
  const askContext = data ? buildAskContext('Advance Decline Graph', data) : ''

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-relaxed text-slate-300">
              Multi-asset breadth: pick <strong className="text-white">India / US / Crypto / Commodity</strong>, an index universe,
              and a date range to plot <strong className="text-white">advances vs declines</strong> across constituents.
              For India F&O indices (Nifty / Bank Nifty / Fin Nifty / Midcap / Next 50), the run also pulls a live{' '}
              <strong className="text-white">options PCR / OI / max-pain</strong> snapshot.
              Commodity baskets mix Yahoo futures with related liquid equities/ETFs. Choose an intraday timeframe to also see breadth{' '}
              <strong className="text-white">within a session</strong> — each bar until the optional as-of time ({tzHint}).
            </p>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              Charts show <strong className="text-slate-400">A/D ratio</strong>,{' '}
              <strong className="text-slate-400">volume ratio</strong>, plus{' '}
              <strong className="text-slate-400">trend</strong>, <strong className="text-slate-400">strength</strong>, and{' '}
              <strong className="text-slate-400">RSI</strong> of market internals. Both ratios above 1 with an uptrend
              and rising strength = healthier move.
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
          <HowToBox copyText={AD_HOW_TO} className="space-y-3">
            <div>
              <p className="mb-1.5 font-medium text-slate-200">How to run</p>
              <ol className="list-decimal space-y-1 pl-4">
                <li>Pick asset class: <span className="text-slate-300">India</span>, <span className="text-slate-300">US</span>, <span className="text-slate-300">Crypto</span>, or <span className="text-slate-300">Commodity</span>.</li>
                <li>Choose an index / universe (e.g. NIFTY 50, Dow 30, Top 30 Crypto, All Commodities / Energy complex).</li>
                <li>Set <span className="text-slate-300">From / To</span> for the daily breadth chart.</li>
                <li>Leave timeframe on <span className="text-slate-300">Daily</span>, or pick an intraday TF + session date (optional as-of time in {tzHint}).</li>
                <li>Click <span className="text-slate-300">Plot Advance / Decline</span>. Wait for constituent candles + (India F&O) options snapshot.</li>
                <li>Optional: open <span className="text-slate-300">AI View</span> for a healthy-vs-hollow verdict.</li>
              </ol>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">How to read the chart</p>
              <ul className="list-disc space-y-1 pl-4">
                <li><span className="text-emerald-300">A/D ratio &gt; 1</span> — more stocks rose than fell (green bars). Below 1 = decline-led (red).</li>
                <li><span className="text-amber-300">Volume ratio &gt; 1</span> — more names got busier; below 1 = quiet / thin participation.</li>
                <li><span className="text-sky-300">UPTREND</span> + rising <span className="text-orange-300">strength</span> — breadth improving and decisive.</li>
                <li><span className="text-cyan-300">RSI</span> — internals hot (&gt;60) or washed out (&lt;40). Mid ~50 is neutral.</li>
                <li>Dashed line at <span className="text-slate-300">1.0</span> = even for A/D and volume ratios; RSI mid = 50.</li>
              </ul>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">Healthy vs hollow</p>
              <ul className="list-disc space-y-1 pl-4">
                <li><span className="text-emerald-300">Healthy advance</span> — A/D &gt; 1 <strong>and</strong> volume ratio &gt; 1 <strong>and</strong> uptrend (optionally PCR &gt; 1 on India F&O).</li>
                <li><span className="text-rose-300">Hollow rally</span> — A/D &gt; 1 but volume ratio &lt; 1 (price up without participation).</li>
                <li><span className="text-rose-300">Confirmed selloff</span> — A/D &lt; 1 with volume expanding and downtrend.</li>
              </ul>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">Options block (India F&O only)</p>
              <p>
                On Nifty / Bank Nifty / Fin Nifty / Midcap / Next 50 the panel adds PCR (OI &amp; Vol), Call/Put OI,
                max pain, and OI support/resistance. PCR &gt; 1 with A/D &gt; 1 often confirms a healthier bullish tape;
                PCR &lt; 0.8 with rising A/D can mean a short-covering / hollow rally. US, Crypto, and Commodity show breadth only.
              </p>
            </div>
            <div>
              <p className="mb-1.5 font-medium text-slate-200">Pair with</p>
              <p>
                <span className="text-slate-300">Comparative Strength</span> (who leads the base) ·{' '}
                <span className="text-slate-300">Option Chain</span> (full PCR deep dive) ·{' '}
                <span className="text-slate-300">Market Heatmap</span> (visual constituents).
              </p>
            </div>
          </HowToBox>
        )}

        <div className="mb-4 flex flex-wrap gap-2">
          {ASSET_OPTIONS.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setIndexName(DEFAULT_INDEX[ac.id])
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <div className="grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Index / universe">
            <Select value={indexName} onChange={(e) => setIndexName(e.target.value)}>
              {(indicesQuery.data?.index_names ?? [indexName]).map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </Select>
          </FormField>
          <FormField label="From date">
            <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          </FormField>
          <FormField label="To date">
            <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          </FormField>
          <FormField label="Timeframe">
            <Select
              value={timeframe}
              onChange={(e) => {
                const v = e.target.value
                setTimeframe(v)
                if (v !== '1d' && !sessionDate) setSessionDate(toDate)
              }}
            >
              <option value="1d">Daily (per session)</option>
              {INTRADAY_TFS.map((tf) => (
                <option key={tf} value={tf}>{tf} intraday</option>
              ))}
            </Select>
          </FormField>
          {isIntraday && (
            <>
              <FormField label={`Session date (intraday, ${tzHint})`}>
                <Input type="date" value={sessionDate} onChange={(e) => setSessionDate(e.target.value)} />
              </FormField>
              <FormField label={`As of time ${tzHint} (optional)`}>
                <Input
                  type="time"
                  value={asOfTime}
                  onChange={(e) => setAsOfTime(e.target.value)}
                  placeholder={`HH:MM ${tzHint}`}
                />
              </FormField>
            </>
          )}
        </div>

        <div className="mt-4">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !fromDate || !toDate || !indexName}
          >
            {runMut.isPending ? 'Building A/D graph…' : 'Plot Advance / Decline'}
          </Button>
        </div>

        {runMut.isError && (
          <div className="mt-3">
            <Alert type="error">{apiErrorMessage(runMut.error)}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Fetching constituent candles and computing breadth…" />}

      {data && !runMut.isPending && (
        <>
          {Boolean(data.error) && <Alert type="error">{String(data.error)}</Alert>}
          {Boolean(data.warning) && (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
              {String(data.warning)}
            </p>
          )}

          {!data.error && (
            <Card className="space-y-4">
              <StrategyDataSourceBar data={data} assetClass={assetClass} />
              {(() => {
                const outcome = (data.outcome_layman as Row | undefined) ?? null
                const howTo = (outcome?.how_to_read as string[] | undefined) ?? []
                return (
                  <div className="rounded-xl border border-slate-700/50 bg-slate-950/40 px-3 py-3 text-sm leading-relaxed text-slate-300">
                    <p className="font-medium text-slate-100">Results in plain English</p>
                    {outcome?.headline != null && (
                      <p className="mt-2 text-base font-semibold text-white">{String(outcome.headline)}</p>
                    )}
                    <p className="mt-2 text-xs text-slate-400">
                      {String(outcome?.summary ?? data.plain_english ?? '')}
                    </p>
                    {outcome?.combo_line != null && (
                      <p className="mt-2 text-xs leading-relaxed text-amber-200/90">
                        <span className="font-medium text-amber-200">Price + volume: </span>
                        {String(outcome.combo_line)}
                      </p>
                    )}
                    {outcome?.what_it_means != null && (
                      <p className="mt-2 text-xs leading-relaxed text-violet-200/90">
                        <span className="font-medium text-violet-200">What it means: </span>
                        {String(outcome.what_it_means)}
                      </p>
                    )}
                    {howTo.length > 0 && (
                      <ul className="mt-2 space-y-0.5 border-t border-slate-800/60 pt-2">
                        {howTo.map((line) => (
                          <li key={line} className="text-xs text-slate-500">· {line}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )
              })()}

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 2xl:grid-cols-9">
                <StatCard label="Universe" value={fmtNum(data.universe_size)} />
                <StatCard
                  label="Advances"
                  value={latest?.advances != null ? fmtNum(latest.advances) : '—'}
                  trend="up"
                />
                <StatCard
                  label="Declines"
                  value={latest?.declines != null ? fmtNum(latest.declines) : '—'}
                  trend="down"
                />
                <StatCard
                  label="Unchanged"
                  value={latest?.unchanged != null ? fmtNum(latest.unchanged) : '—'}
                />
                <StatCard
                  label="Latest A/D ratio"
                  value={latest?.ad_ratio != null ? fmtNum(latest.ad_ratio, 2) : '—'}
                />
                <StatCard
                  label="Latest vol ratio"
                  value={latest?.vol_ratio != null ? fmtNum(latest.vol_ratio, 2) : '—'}
                />
                <StatCard
                  label="Trend"
                  value={latest?.trend != null ? String(latest.trend) : '—'}
                  trend={
                    String(latest?.trend) === 'UPTREND'
                      ? 'up'
                      : String(latest?.trend) === 'DOWNTREND'
                        ? 'down'
                        : 'neutral'
                  }
                />
                <StatCard
                  label="Strength"
                  value={latest?.strength != null ? fmtNum(latest.strength, 0) : '—'}
                />
                <StatCard
                  label="RSI"
                  value={latest?.rsi != null ? fmtNum(latest.rsi, 1) : '—'}
                />
              </div>

              {(() => {
                const opts = (data.options as Row | undefined) ?? null
                if (!opts) return null
                if (!opts.available) {
                  return assetClass === 'india' ? (
                    <p className="text-xs text-slate-500">
                      Options: {String(opts.reason ?? 'not available for this universe.')}
                    </p>
                  ) : null
                }
                const bias = opts.bias != null ? String(opts.bias) : '—'
                const pcr = opts.pcr_oi != null ? Number(opts.pcr_oi) : null
                return (
                  <div className="space-y-3 rounded-xl border border-sky-500/20 bg-sky-500/5 px-3 py-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="text-sm font-medium text-slate-100">
                        Options snapshot · {String(opts.oc_symbol ?? '')}
                        {opts.current_expiry != null && (
                          <span className="ml-2 text-xs font-normal text-slate-500">
                            expiry {String(opts.current_expiry)}
                          </span>
                        )}
                      </p>
                      <span
                        className={
                          bias === 'BULLISH'
                            ? 'text-xs font-semibold text-emerald-300'
                            : bias === 'BEARISH'
                              ? 'text-xs font-semibold text-rose-300'
                              : 'text-xs font-semibold text-slate-400'
                        }
                      >
                        {bias}
                        {opts.trade_signal != null && ` · ${String(opts.trade_signal)}`}
                        {opts.confidence_pct != null && ` (${fmtNum(opts.confidence_pct, 0)}%)`}
                      </span>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                      <StatCard
                        label="PCR (OI)"
                        value={pcr != null ? fmtNum(pcr, 2) : '—'}
                        trend={pcr != null ? (pcr >= 1 ? 'up' : 'down') : 'neutral'}
                      />
                      <StatCard
                        label="PCR (Vol)"
                        value={opts.pcr_vol != null ? fmtNum(opts.pcr_vol, 2) : '—'}
                      />
                      <StatCard
                        label="Call OI"
                        value={opts.total_call_oi != null ? fmtNum(opts.total_call_oi, 0) : '—'}
                      />
                      <StatCard
                        label="Put OI"
                        value={opts.total_put_oi != null ? fmtNum(opts.total_put_oi, 0) : '—'}
                      />
                      <StatCard
                        label="Max Pain"
                        value={opts.max_pain != null ? fmtNum(opts.max_pain, 0) : '—'}
                      />
                      <StatCard
                        label="S / R (OI)"
                        value={
                          opts.support != null || opts.resistance != null
                            ? `${opts.support != null ? fmtNum(opts.support, 0) : '—'} / ${opts.resistance != null ? fmtNum(opts.resistance, 0) : '—'}`
                            : '—'
                        }
                      />
                    </div>
                    {opts.plain_english != null && (
                      <p className="text-xs text-slate-400">{String(opts.plain_english)}</p>
                    )}
                    {(data.outcome_layman as Row | undefined)?.options_line != null && (
                      <p className="text-xs text-sky-200/90">
                        {String((data.outcome_layman as Row).options_line)}
                      </p>
                    )}
                  </div>
                )
              })()}

              <AdRatioChart
                series={daily}
                title={`A/D + Volume ratio — ${String(data.index_name)} (${fromDate} → ${toDate})`}
                xKey="date"
              />

              {isIntraday && (
                <AdRatioChart
                  series={intraday}
                  title={`Intraday A/D + Volume (${timeframe}) — ${String(data.session_date ?? sessionDate)} ${String(data.timezone ?? tzHint)}${data.as_of_time ? ` until ${String(data.as_of_time)}` : ''}`}
                  xKey="label"
                />
              )}

              {isIntraday && !intraday.length && (
                <p className="text-sm text-amber-400/90">
                  No intraday bars for that session/timeframe yet — try another session date or a coarser TF.
                </p>
              )}
            </Card>
          )}

          {askContext && (
            <AskAIPanel
              title="AI View"
              section="command-center/advance-decline-graph"
              context={askContext}
              defaultQuestion="Given this advance/decline breadth plus the options PCR/OI/max-pain snapshot, is the market advance healthy or hollow, and what would invalidate that view?"
            />
          )}
        </>
      )}
    </div>
  )
}
