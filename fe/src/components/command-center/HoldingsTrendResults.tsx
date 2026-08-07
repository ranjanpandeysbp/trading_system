import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Chip } from '../ui/Chip'
import { FormField, Input } from '../ui/Form'
import { DataTable, SortableTh, Td, Th, useSort } from '../ui/Table'
import { StatCard } from '../ui/StatCard'
import { StrategyDataSourceBar } from '../ui/StrategyDataSourceBar'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { CollapsibleScrollSection } from './CollapsibleScrollSection'

export type OverallRow = {
  stock?: string
  sector?: string
  mcap_category?: string
  n_schemes?: number
  n_stocks?: number
  schemes_increasing?: number
  schemes_decreasing?: number
  schemes_stable?: number
  avg_holding_pct?: number
  avg_change_pct?: number
  total_change_pct?: number
  overall_trend?: string
  summary?: string
}

export type PerSchemeRow = {
  scheme_name?: string
  stock?: string
  sector?: string
  first_date?: string
  first_pct?: number
  last_date?: string
  last_pct?: number
  change_pct?: number
  trend?: string
  summary?: string
}

export type RawRow = {
  date?: string
  scheme_name?: string
  stock?: string
  holding_pct?: number
}

export type HoldingsAnalysisResult = {
  error?: string
  dates?: string[]
  overall?: OverallRow[]
  per_scheme?: PerSchemeRow[]
  raw?: RawRow[]
  overall_sector?: OverallRow[]
  per_scheme_sector?: PerSchemeRow[]
  raw_sector?: RawRow[]
  scheme_ids?: Array<number | string>
  snapshot_note?: string
  market?: string
  source?: string
}

type TradeBias = 'LONG' | 'SHORT' | 'WAIT'

type TradeSignal = {
  entity: string
  bias: TradeBias
  reason: string
  avgChange: number
  up: number
  down: number
  nSchemes: number
  trend: string
  sector?: string
}

const SERIES_COLORS = [
  '#38bdf8',
  '#10b981',
  '#f59e0b',
  '#a78bfa',
  '#f472b6',
  '#34d399',
]

const TOP_FUND_LINES = 5

function TableSearchBox({
  value,
  onChange,
  placeholder = 'Search…',
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <div className="relative mb-2 max-w-xs">
      <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="pl-8"
      />
    </div>
  )
}

function fmtPct(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

function shortFundLabel(name: string, max = 28): string {
  const s = name.replace(/\s+/g, ' ').trim()
  if (s.length <= max) return s
  return `${s.slice(0, max - 1)}…`
}

function trendBadge(trend: string | undefined) {
  const t = (trend ?? '').toUpperCase()
  if (t === 'INCREASING') return <span className="text-emerald-400">Increasing</span>
  if (t === 'DECREASING') return <span className="text-rose-400">Decreasing</span>
  if (t === 'MIXED') return <span className="text-amber-400">Mixed</span>
  return <span className="text-slate-400">Stable</span>
}

function biasBadge(bias: TradeBias) {
  if (bias === 'LONG') {
    return (
      <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-300">
        LONG
      </span>
    )
  }
  if (bias === 'SHORT') {
    return (
      <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-xs font-semibold text-rose-300">
        SHORT
      </span>
    )
  }
  return (
    <span className="rounded-md bg-slate-500/20 px-2 py-0.5 text-xs font-semibold text-slate-300">
      WAIT
    </span>
  )
}

/** Institutional flow → trade bias from stake changes across funds. */
export function deriveTradeSignal(
  row: OverallRow,
  mode: 'stock' | 'sector',
): TradeSignal {
  const entity = String(mode === 'stock' ? row.stock : row.sector ?? '')
  const up = Number(row.schemes_increasing ?? 0)
  const down = Number(row.schemes_decreasing ?? 0)
  const nSchemes = Number(row.n_schemes ?? up + down + Number(row.schemes_stable ?? 0))
  const avgChange = Number(row.avg_change_pct ?? 0)
  const trend = String(row.overall_trend ?? 'STABLE').toUpperCase()
  const noun = mode === 'stock' ? 'stock' : 'sector'
  const fundWord = nSchemes === 1 ? 'fund' : 'funds'

  let bias: TradeBias = 'WAIT'
  let reason: string

  const net = up - down
  const strongUp = trend === 'INCREASING' && avgChange > 0.02 && up >= down && up > 0
  const strongDown = trend === 'DECREASING' && avgChange < -0.02 && down >= up && down > 0
  const mildUp = avgChange > 0.05 && net >= 1
  const mildDown = avgChange < -0.05 && net <= -1

  if (strongUp || (mildUp && trend !== 'DECREASING')) {
    bias = 'LONG'
    reason =
      `Funds are accumulating this ${noun}: ${up}/${nSchemes || '—'} ${fundWord} raised stake ` +
      `(avg Δ ${fmtPct(avgChange, 3)}%). Institutional buying often supports a long bias.`
  } else if (strongDown || (mildDown && trend !== 'INCREASING')) {
    bias = 'SHORT'
    reason =
      `Funds are reducing this ${noun}: ${down}/${nSchemes || '—'} ${fundWord} cut stake ` +
      `(avg Δ ${fmtPct(avgChange, 3)}%). Distribution pressure favors a short / avoid bias.`
  } else if (trend === 'MIXED' || (up > 0 && down > 0 && Math.abs(avgChange) < 0.05)) {
    bias = 'WAIT'
    reason =
      `Mixed flow (${up} ↑ / ${down} ↓, avg Δ ${fmtPct(avgChange, 3)}%). ` +
      `No clear institutional consensus — wait for a cleaner stake trend.`
  } else {
    bias = 'WAIT'
    reason =
      `Stake change is small or stable (avg Δ ${fmtPct(avgChange, 3)}%, trend ${trend.toLowerCase()}). ` +
      `No strong long/short edge from holdings alone.`
  }

  return {
    entity,
    bias,
    reason,
    avgChange,
    up,
    down,
    nSchemes,
    trend,
    sector: row.sector,
  }
}

function HoldingTrendChart({
  raw,
  entity,
  height = 300,
  yTitle = 'Holding %',
}: {
  raw: RawRow[]
  entity: string
  height?: number
  yTitle?: string
}) {
  const { chartData, seriesKeys, seriesMeta } = useMemo(() => {
    const sub = raw.filter((r) => r.stock === entity)
    if (!sub.length) {
      return {
        chartData: [] as Record<string, string | number>[],
        seriesKeys: [] as string[],
        seriesMeta: [] as { key: string; label: string; color: string }[],
      }
    }

    const latestByFund = new Map<string, { date: string; pct: number }>()
    for (const r of sub) {
      const name = String(r.scheme_name ?? '').trim()
      const d = String(r.date ?? '').slice(0, 10)
      if (!name || !d || r.holding_pct == null) continue
      const prev = latestByFund.get(name)
      if (!prev || d >= prev.date) {
        latestByFund.set(name, { date: d, pct: Number(r.holding_pct) })
      }
    }
    const ranked = [...latestByFund.entries()]
      .sort((a, b) => b[1].pct - a[1].pct)
      .slice(0, TOP_FUND_LINES)
    const topFunds = ranked.map(([name]) => name)
    const fundKey = new Map(topFunds.map((name, i) => [name, `f${i + 1}`]))

    const byDate = new Map<string, { sum: number; n: number; funds: Record<string, number> }>()
    for (const r of sub) {
      const d = String(r.date ?? '').slice(0, 10)
      if (!d || r.holding_pct == null) continue
      const bucket = byDate.get(d) ?? { sum: 0, n: 0, funds: {} }
      const pct = Number(r.holding_pct)
      bucket.sum += pct
      bucket.n += 1
      const name = String(r.scheme_name ?? '').trim()
      const key = fundKey.get(name)
      if (key) bucket.funds[key] = pct
      byDate.set(d, bucket)
    }

    const points = [...byDate.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([date, b]) => ({
        date,
        avg: b.n ? Number((b.sum / b.n).toFixed(4)) : 0,
        ...b.funds,
      }))

    const meta = [
      { key: 'avg', label: `Avg across ${latestByFund.size} fund(s)`, color: SERIES_COLORS[0] },
      ...topFunds.map((name, i) => ({
        key: `f${i + 1}`,
        label: shortFundLabel(name),
        color: SERIES_COLORS[(i + 1) % SERIES_COLORS.length],
      })),
    ]

    return {
      chartData: points,
      seriesKeys: meta.map((m) => m.key),
      seriesMeta: meta,
    }
  }, [raw, entity])

  if (!chartData.length) {
    return <p className="text-xs text-slate-500">No holding series for {entity}.</p>
  }

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slate-100">{entity}</p>
        <p className="text-[11px] text-slate-500">
          Avg line + top {Math.min(TOP_FUND_LINES, Math.max(0, seriesKeys.length - 1))} funds by latest weight
        </p>
      </div>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={28} />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              width={44}
              label={{ value: yTitle, angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#e2e8f0' }}
              formatter={(value, name) => {
                const meta = seriesMeta.find((m) => m.key === name)
                const label = meta?.label ?? String(name)
                const n = typeof value === 'number' ? value : Number(value)
                return [Number.isFinite(n) ? `${n.toFixed(3)}%` : String(value), label]
              }}
            />
            {seriesMeta.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.key}
                stroke={s.color}
                strokeWidth={s.key === 'avg' ? 2.5 : 1.5}
                strokeOpacity={s.key === 'avg' ? 1 : 0.85}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">
        {seriesMeta.map((s) => (
          <li key={s.key} className="inline-flex max-w-full items-center gap-1.5">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: s.color }} />
            <span className={s.key === 'avg' ? 'font-medium text-slate-200' : 'truncate'} title={s.label}>
              {s.label}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function TradeSignalSummary({
  overall,
  mode,
  fundNoun,
  marketType,
  resolveName,
}: {
  overall: OverallRow[]
  mode: 'stock' | 'sector'
  fundNoun: string
  marketType: WatchlistMarket
  resolveName?: boolean
}) {
  const [open, setOpen] = useState(true)
  const [search, setSearch] = useState('')
  const signals = useMemo(
    () =>
      overall
        .map((r) => deriveTradeSignal(r, mode))
        .filter((s) => s.entity)
        .sort((a, b) => {
          const rank = (x: TradeBias) => (x === 'LONG' ? 0 : x === 'SHORT' ? 1 : 2)
          const d = rank(a.bias) - rank(b.bias)
          if (d !== 0) return d
          return Math.abs(b.avgChange) - Math.abs(a.avgChange)
        }),
    [overall, mode],
  )

  const longs = signals.filter((s) => s.bias === 'LONG').length
  const shorts = signals.filter((s) => s.bias === 'SHORT').length
  const waits = signals.filter((s) => s.bias === 'WAIT').length

  const filteredSignals = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return signals
    return signals.filter((s) => s.entity.toLowerCase().includes(q) || (s.sector ?? '').toLowerCase().includes(q))
  }, [signals, search])

  const { sorted, sortKey, sortDir, handleSort } = useSort(filteredSignals, {
    entity: (r) => r.entity,
    bias: (r) => r.bias,
    avg: (r) => r.avgChange,
    up: (r) => r.up,
    down: (r) => r.down,
    trend: (r) => r.trend,
  }, 'bias', 'asc')

  if (!signals.length) return null

  return (
    <CollapsibleScrollSection
      title={`Trade bias from ${fundNoun.toLowerCase()} stake changes`}
      subtitle={`${longs} long · ${shorts} short · ${waits} wait · scroll inside`}
      open={open}
      onToggle={() => setOpen((v) => !v)}
      maxHeightClass="max-h-80"
    >
      <div className="mb-2 text-xs text-slate-500">
        LONG = funds accumulating · SHORT = funds distributing · WAIT = mixed/flat.
      </div>
      <TableSearchBox value={search} onChange={setSearch} placeholder={`Search ${mode === 'stock' ? 'stock' : 'sector'}…`} />
      <DataTable minWidth={920}>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'entity'} direction={sortDir} onSort={() => handleSort('entity')}>
              {mode === 'stock' ? 'Stock' : 'Sector'}
            </SortableTh>
            <SortableTh active={sortKey === 'bias'} direction={sortDir} onSort={() => handleSort('bias')}>
              Bias
            </SortableTh>
            <SortableTh active={sortKey === 'avg'} direction={sortDir} onSort={() => handleSort('avg')}>
              Avg Δ %
            </SortableTh>
            <SortableTh active={sortKey === 'up'} direction={sortDir} onSort={() => handleSort('up')}>
              ↑ Funds
            </SortableTh>
            <SortableTh active={sortKey === 'down'} direction={sortDir} onSort={() => handleSort('down')}>
              ↓ Funds
            </SortableTh>
            <SortableTh active={sortKey === 'trend'} direction={sortDir} onSort={() => handleSort('trend')}>
              Trend
            </SortableTh>
            <Th>Reasoning</Th>
            {mode === 'stock' && <Th></Th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => (
            <tr key={s.entity} className="border-t border-slate-800/80 align-top">
              <Td className="font-medium text-slate-100">
                {s.entity}
                {mode === 'stock' && s.sector ? (
                  <div className="text-[11px] font-normal text-slate-500">{s.sector}</div>
                ) : null}
              </Td>
              <Td>{biasBadge(s.bias)}</Td>
              <Td className={s.avgChange > 0 ? 'text-emerald-400' : s.avgChange < 0 ? 'text-rose-400' : ''}>
                {fmtPct(s.avgChange, 3)}
              </Td>
              <Td className="text-emerald-400">{s.up}</Td>
              <Td className="text-rose-400">{s.down}</Td>
              <Td>{trendBadge(s.trend)}</Td>
              <Td className="max-w-md text-xs leading-relaxed text-slate-400">{s.reason}</Td>
              {mode === 'stock' && (
                <Td>
                  <AddToWatchlistButton
                    ticker={s.entity}
                    displayName={s.entity}
                    notes={`Holdings bias ${s.bias} · ${s.trend} · avg Δ ${fmtPct(s.avgChange, 3)}%`}
                    marketType={marketType}
                    resolveName={resolveName}
                    compact
                  />
                </Td>
              )}
            </tr>
          ))}
        </tbody>
      </DataTable>
    </CollapsibleScrollSection>
  )
}

function EntityPanel({
  overall,
  perScheme,
  raw,
  mode,
  fundNoun,
  marketType,
  resolveName,
}: {
  overall: OverallRow[]
  perScheme: PerSchemeRow[]
  raw: RawRow[]
  mode: 'stock' | 'sector'
  fundNoun: string
  marketType: WatchlistMarket
  resolveName?: boolean
}) {
  const entityLabel = mode === 'stock' ? 'Stock' : 'Sector'
  const yTitle = mode === 'stock' ? 'Holding %' : 'Sector weight %'
  const showAvgHolding = overall.some((r) => r.avg_holding_pct != null)
  const showNStocks = mode === 'sector'

  const rows = overall.map((r) => ({
    ...r,
    _entity: String(mode === 'stock' ? r.stock : r.sector ?? ''),
  }))

  const { sorted, sortKey, sortDir, handleSort } = useSort(rows, {
    entity: (r) => r._entity,
    sector: (r) => r.sector,
    mcap: (r) => r.mcap_category,
    n_stocks: (r) => r.n_stocks,
    n_schemes: (r) => r.n_schemes,
    avg_hold: (r) => r.avg_holding_pct,
    up: (r) => r.schemes_increasing,
    down: (r) => r.schemes_decreasing,
    avg: (r) => r.avg_change_pct,
    total: (r) => r.total_change_pct,
    trend: (r) => r.overall_trend,
  }, 'avg', 'desc')

  const [chartEntity, setChartEntity] = useState(rows[0]?._entity ?? '')
  const [showFull, setShowFull] = useState(false)
  const [showPerFund, setShowPerFund] = useState(false)
  const [topOpen, setTopOpen] = useState(true)
  const [chartOpen, setChartOpen] = useState(true)
  const [fullSearch, setFullSearch] = useState('')
  const [perSearch, setPerSearch] = useState('')

  const topUp = sorted.filter((r) => Number(r.avg_change_pct) > 0).slice(0, 10)
  const topDown = [...sorted]
    .filter((r) => Number(r.avg_change_pct) < 0)
    .sort((a, b) => Number(a.avg_change_pct) - Number(b.avg_change_pct))
    .slice(0, 10)

  let allEntities = rows.map((r) => r._entity).filter(Boolean).sort()
  if (mode === 'sector') {
    const known = allEntities.filter((e) => !['—', 'nan', 'None', ''].includes(e))
    if (known.length) allEntities = known
  }

  const perSort = useSort(perScheme, {
    fund: (r) => r.scheme_name,
    entity: (r) => (mode === 'stock' ? r.stock : r.sector),
    sector: (r) => r.sector,
    change: (r) => r.change_pct,
    trend: (r) => r.trend,
  }, 'change', 'desc')

  const filteredFullSorted = useMemo(() => {
    const q = fullSearch.trim().toLowerCase()
    if (!q) return sorted
    return sorted.filter(
      (r) => r._entity.toLowerCase().includes(q) || (r.sector ?? '').toLowerCase().includes(q),
    )
  }, [sorted, fullSearch])

  const filteredPerSorted = useMemo(() => {
    const q = perSearch.trim().toLowerCase()
    if (!q) return perSort.sorted
    return perSort.sorted.filter((r) => {
      const entity = String(mode === 'stock' ? r.stock : r.sector ?? '')
      return (
        entity.toLowerCase().includes(q) ||
        (r.scheme_name ?? '').toLowerCase().includes(q) ||
        (r.sector ?? '').toLowerCase().includes(q)
      )
    })
  }, [perSort.sorted, perSearch, mode])

  const renderTable = (tableRows: typeof sorted, title?: string) => {
    if (!tableRows.length) {
      return (
        <div>
          {title ? <h4 className="mb-2 text-sm font-semibold text-white">{title}</h4> : null}
          <p className="text-xs text-slate-500">No rows.</p>
        </div>
      )
    }
    return (
      <div>
        {title ? <h4 className="mb-2 text-sm font-semibold text-white">{title}</h4> : null}
        <DataTable minWidth={showAvgHolding || showNStocks ? 960 : 860}>
          <thead>
            <tr>
              <SortableTh active={sortKey === 'entity'} direction={sortDir} onSort={() => handleSort('entity')}>{entityLabel}</SortableTh>
              {mode === 'stock' && (
                <>
                  <SortableTh active={sortKey === 'sector'} direction={sortDir} onSort={() => handleSort('sector')}>Sector</SortableTh>
                  <SortableTh active={sortKey === 'mcap'} direction={sortDir} onSort={() => handleSort('mcap')}>Mcap</SortableTh>
                </>
              )}
              {showNStocks && (
                <SortableTh active={sortKey === 'n_stocks'} direction={sortDir} onSort={() => handleSort('n_stocks')}># Stocks</SortableTh>
              )}
              <SortableTh active={sortKey === 'n_schemes'} direction={sortDir} onSort={() => handleSort('n_schemes')}># {fundNoun}</SortableTh>
              {showAvgHolding && (
                <SortableTh active={sortKey === 'avg_hold'} direction={sortDir} onSort={() => handleSort('avg_hold')}>
                  {mode === 'stock' ? 'Avg Holding %' : 'Avg Sector Weight %'}
                </SortableTh>
              )}
              <SortableTh active={sortKey === 'up'} direction={sortDir} onSort={() => handleSort('up')}>↑ {fundNoun}</SortableTh>
              <SortableTh active={sortKey === 'down'} direction={sortDir} onSort={() => handleSort('down')}>↓ {fundNoun}</SortableTh>
              <SortableTh active={sortKey === 'avg'} direction={sortDir} onSort={() => handleSort('avg')}>Avg Δ %</SortableTh>
              <SortableTh active={sortKey === 'total'} direction={sortDir} onSort={() => handleSort('total')}>Total Δ %</SortableTh>
              <SortableTh active={sortKey === 'trend'} direction={sortDir} onSort={() => handleSort('trend')}>Trend</SortableTh>
              {mode === 'stock' && <Th></Th>}
            </tr>
          </thead>
          <tbody>
            {tableRows.map((r) => (
              <tr key={r._entity} className="border-t border-slate-800/80">
                <Td className="font-medium text-slate-100">{r._entity}</Td>
                {mode === 'stock' && (
                  <>
                    <Td>{r.sector ?? '—'}</Td>
                    <Td>{r.mcap_category ?? '—'}</Td>
                  </>
                )}
                {showNStocks && <Td>{r.n_stocks ?? '—'}</Td>}
                <Td>{r.n_schemes ?? '—'}</Td>
                {showAvgHolding && <Td>{fmtPct(r.avg_holding_pct, 3)}</Td>}
                <Td className="text-emerald-400">{r.schemes_increasing ?? '—'}</Td>
                <Td className="text-rose-400">{r.schemes_decreasing ?? '—'}</Td>
                <Td className={Number(r.avg_change_pct) > 0 ? 'text-emerald-400' : Number(r.avg_change_pct) < 0 ? 'text-rose-400' : ''}>
                  {fmtPct(r.avg_change_pct, 3)}
                </Td>
                <Td>{fmtPct(r.total_change_pct, 3)}</Td>
                <Td>{trendBadge(r.overall_trend)}</Td>
                {mode === 'stock' && (
                  <Td>
                    <AddToWatchlistButton
                      ticker={r._entity}
                      displayName={r._entity}
                      notes={`MF/ETF holdings · ${r.sector ?? ''} · ${r.overall_trend ?? ''}`.trim()}
                      marketType={marketType}
                      resolveName={resolveName}
                      compact
                    />
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </DataTable>
      </div>
    )
  }

  if (!overall.length) {
    return <p className="text-sm text-slate-500">No {entityLabel.toLowerCase()}-level holdings to summarize.</p>
  }

  return (
    <div className="space-y-3">
      <TradeSignalSummary
        overall={overall}
        mode={mode}
        fundNoun={fundNoun}
        marketType={marketType}
        resolveName={resolveName}
      />

      <CollapsibleScrollSection
        title={`Top ${entityLabel.toLowerCase()} movers`}
        subtitle={`${topUp.length} increases · ${topDown.length} decreases`}
        open={topOpen}
        onToggle={() => setTopOpen((v) => !v)}
        maxHeightClass="max-h-72"
      >
        <div className="space-y-4">
          {renderTable(topUp, `Top ${entityLabel.toLowerCase()} increases`)}
          {renderTable(topDown, `Top ${entityLabel.toLowerCase()} decreases`)}
        </div>
      </CollapsibleScrollSection>

      <CollapsibleScrollSection
        title={`Full ${entityLabel.toLowerCase()} summary — ${overall.length}`}
        subtitle="Collapsed by default · expand to scroll all rows"
        open={showFull}
        onToggle={() => setShowFull((v) => !v)}
        maxHeightClass="max-h-80"
      >
        <TableSearchBox value={fullSearch} onChange={setFullSearch} placeholder={`Search ${entityLabel.toLowerCase()}…`} />
        {renderTable(filteredFullSorted)}
      </CollapsibleScrollSection>

      <CollapsibleScrollSection
        title={`Per-${fundNoun.replace(/s$/i, '')} breakdown — ${perScheme.length}`}
        subtitle="Collapsed by default"
        open={showPerFund}
        onToggle={() => setShowPerFund((v) => !v)}
        maxHeightClass="max-h-80"
      >
        <TableSearchBox
          value={perSearch}
          onChange={setPerSearch}
          placeholder={`Search ${entityLabel.toLowerCase()} or ${fundNoun.replace(/s$/i, '').toLowerCase()}…`}
        />
        <DataTable minWidth={900}>
          <thead>
            <tr>
              <SortableTh active={perSort.sortKey === 'fund'} direction={perSort.sortDir} onSort={() => perSort.handleSort('fund')}>{fundNoun.replace(/s$/i, '')}</SortableTh>
              <SortableTh active={perSort.sortKey === 'entity'} direction={perSort.sortDir} onSort={() => perSort.handleSort('entity')}>{entityLabel}</SortableTh>
              {mode === 'stock' && (
                <SortableTh active={perSort.sortKey === 'sector'} direction={perSort.sortDir} onSort={() => perSort.handleSort('sector')}>Sector</SortableTh>
              )}
              <Th>From</Th>
              <Th>From %</Th>
              <Th>To</Th>
              <Th>To %</Th>
              <SortableTh active={perSort.sortKey === 'change'} direction={perSort.sortDir} onSort={() => perSort.handleSort('change')}>Δ %</SortableTh>
              <SortableTh active={perSort.sortKey === 'trend'} direction={perSort.sortDir} onSort={() => perSort.handleSort('trend')}>Trend</SortableTh>
              <Th>Summary</Th>
              {mode === 'stock' && <Th></Th>}
            </tr>
          </thead>
          <tbody>
            {filteredPerSorted.map((r, i) => (
              <tr key={`${r.scheme_name}-${mode === 'stock' ? r.stock : r.sector}-${i}`} className="border-t border-slate-800/80">
                <Td>{r.scheme_name ?? '—'}</Td>
                <Td className="font-medium text-slate-100">{(mode === 'stock' ? r.stock : r.sector) ?? '—'}</Td>
                {mode === 'stock' && <Td>{r.sector ?? '—'}</Td>}
                <Td>{String(r.first_date ?? '').slice(0, 10) || '—'}</Td>
                <Td>{fmtPct(r.first_pct, 3)}</Td>
                <Td>{String(r.last_date ?? '').slice(0, 10) || '—'}</Td>
                <Td>{fmtPct(r.last_pct, 3)}</Td>
                <Td className={Number(r.change_pct) > 0 ? 'text-emerald-400' : Number(r.change_pct) < 0 ? 'text-rose-400' : ''}>
                  {fmtPct(r.change_pct, 3)}
                </Td>
                <Td>{trendBadge(r.trend)}</Td>
                <Td className="max-w-xs text-xs leading-relaxed text-slate-400">{r.summary ?? '—'}</Td>
                {mode === 'stock' && r.stock && (
                  <Td>
                    <AddToWatchlistButton
                      ticker={String(r.stock)}
                      displayName={String(r.stock)}
                      notes={`From ${r.scheme_name ?? 'fund'} · ${r.trend ?? ''}`}
                      marketType={marketType}
                      resolveName={resolveName}
                      compact
                    />
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </DataTable>
      </CollapsibleScrollSection>

      {allEntities.length > 0 && (
        <CollapsibleScrollSection
          title={`${entityLabel} holding % over time`}
          subtitle={`Avg + top ${TOP_FUND_LINES} funds · pick a ${entityLabel.toLowerCase()}`}
          open={chartOpen}
          onToggle={() => setChartOpen((v) => !v)}
          scroll={false}
        >
          <FormField label={`Pick a ${entityLabel.toLowerCase()} to chart`}>
            <select
              className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={chartEntity || allEntities[0]}
              onChange={(e) => setChartEntity(e.target.value)}
            >
              {allEntities.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </FormField>
          <div className="mt-3">
            <HoldingTrendChart raw={raw} entity={chartEntity || allEntities[0]} yTitle={yTitle} />
          </div>
        </CollapsibleScrollSection>
      )}
    </div>
  )
}

export function HoldingsTrendResults({
  data,
  fundNoun = 'Funds',
  askSection,
  askTitle,
  marketType = 'india',
  resolveName = false,
}: {
  data: HoldingsAnalysisResult
  fundNoun?: string
  askSection: string
  askTitle: string
  marketType?: WatchlistMarket
  resolveName?: boolean
}) {
  const [view, setView] = useState<'stock' | 'sector'>('stock')
  const dates = data.dates ?? []
  const overall = data.overall ?? []
  const overallSector = data.overall_sector ?? []
  const sectorUseful =
    overallSector.length > 0 &&
    !(overallSector.length === 1 && ['—', 'nan', ''].includes(String(overallSector[0]?.sector ?? '')))

  const askContext = buildAskContext(askTitle, data)
  const nSectors = sectorUseful
    ? new Set(overallSector.map((r) => r.sector).filter(Boolean)).size
    : 0

  return (
    <div className="space-y-6">
      <StrategyDataSourceBar data={data as unknown as Record<string, unknown>} assetClass="india" />
      {data.snapshot_note && (
        <p className="rounded-lg border border-slate-700/80 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
          {data.snapshot_note}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-4">
        <StatCard label={`${fundNoun} analyzed`} value={data.scheme_ids?.length ?? 0} />
        <StatCard label="Snapshots" value={`${dates.length} period(s)`} />
        <StatCard label="Stocks tracked" value={overall.length} />
        <StatCard label="Sectors tracked" value={nSectors} />
      </div>
      {dates.length >= 1 && (
        <p className="text-xs text-slate-500">
          Date range: <span className="text-slate-300">{dates[0]}</span>
          {dates.length > 1 && (
            <>
              {' → '}
              <span className="text-slate-300">{dates[dates.length - 1]}</span>
            </>
          )}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <Chip selected={view === 'stock'} onClick={() => setView('stock')}>Stock-wise</Chip>
        <Chip selected={view === 'sector'} onClick={() => setView('sector')}>Sector-wise</Chip>
      </div>

      {view === 'stock' ? (
        <EntityPanel
          overall={overall}
          perScheme={data.per_scheme ?? []}
          raw={data.raw ?? []}
          mode="stock"
          fundNoun={fundNoun}
          marketType={marketType}
          resolveName={resolveName}
        />
      ) : sectorUseful ? (
        <EntityPanel
          overall={overallSector}
          perScheme={data.per_scheme_sector ?? []}
          raw={data.raw_sector ?? []}
          mode="sector"
          fundNoun={fundNoun}
          marketType={marketType}
        />
      ) : (
        <p className="text-sm text-slate-500">
          Sector breakdown is unavailable for this run (no sector labels on holdings). Stock-wise view still works.
        </p>
      )}

      {askContext && <AskAIPanel context={askContext} section={askSection} />}
    </div>
  )
}
