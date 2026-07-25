import { useMemo, useState } from 'react'
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
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Chip } from '../ui/Chip'
import { FormField } from '../ui/Form'
import { DataTable, SortableTh, Td, Th, useSort } from '../ui/Table'
import { StatCard } from '../ui/StatCard'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'

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

const TREND_COLORS = [
  '#10b981', '#06b6d4', '#60a5fa', '#a78bfa', '#f59e0b',
  '#ef4444', '#f472b6', '#34d399', '#818cf8', '#fb923c',
]

function fmtPct(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

function trendBadge(trend: string | undefined) {
  const t = (trend ?? '').toUpperCase()
  if (t === 'INCREASING') return <span className="text-emerald-400">Increasing</span>
  if (t === 'DECREASING') return <span className="text-rose-400">Decreasing</span>
  if (t === 'MIXED') return <span className="text-amber-400">Mixed</span>
  return <span className="text-slate-400">Stable</span>
}

function HoldingTrendChart({
  raw,
  entity,
  height = 280,
  yTitle = 'Holding %',
}: {
  raw: RawRow[]
  entity: string
  height?: number
  yTitle?: string
}) {
  const { schemes, chartData } = useMemo(() => {
    const sub = raw.filter((r) => r.stock === entity)
    const schemeNames = [...new Set(sub.map((r) => String(r.scheme_name ?? '')).filter(Boolean))]
    const byDate = new Map<string, Record<string, string | number>>()
    for (const r of sub) {
      const d = String(r.date ?? '').slice(0, 10)
      if (!d) continue
      const row = byDate.get(d) ?? { date: d }
      if (r.scheme_name != null && r.holding_pct != null) {
        row[String(r.scheme_name)] = Number(r.holding_pct)
      }
      byDate.set(d, row)
    }
    const points = [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)))
    return { schemes: schemeNames, chartData: points }
  }, [raw, entity])

  if (!chartData.length || !schemes.length) {
    return <p className="text-xs text-slate-500">No holding series for {entity}.</p>
  }

  return (
    <div style={{ height }} className="w-full">
      <p className="mb-1 text-xs font-medium text-slate-300">{entity}</p>
      <ResponsiveContainer width="100%" height="90%">
        <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            label={{ value: yTitle, angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8 }}
            labelStyle={{ color: '#e2e8f0' }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {schemes.map((name, i) => (
            <Line
              key={name}
              type="monotone"
              dataKey={name}
              stroke={TREND_COLORS[i % TREND_COLORS.length]}
              strokeWidth={2}
              dot={{ r: 3 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
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

  const topUp = sorted.filter((r) => Number(r.avg_change_pct) > 0).slice(0, 10)
  const topDown = [...sorted]
    .filter((r) => Number(r.avg_change_pct) < 0)
    .sort((a, b) => Number(a.avg_change_pct) - Number(b.avg_change_pct))
    .slice(0, 10)
  const movers = [
    ...topUp.slice(0, 3).map((r) => r._entity),
    ...topDown.slice(0, 3).map((r) => r._entity),
  ].filter(Boolean)

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
    <div className="space-y-6">
      {renderTable(topUp, `Top ${entityLabel.toLowerCase()} increases`)}
      {renderTable(topDown, `Top ${entityLabel.toLowerCase()} decreases`)}

      <div>
        <button type="button" className="mb-2 text-sm font-semibold text-slate-200 hover:text-white" onClick={() => setShowFull((v) => !v)}>
          {showFull ? '▾' : '▸'} Full {entityLabel.toLowerCase()} summary — {overall.length}
        </button>
        {showFull && renderTable(sorted)}
      </div>

      <div>
        <button type="button" className="mb-2 text-sm font-semibold text-slate-200 hover:text-white" onClick={() => setShowPerFund((v) => !v)}>
          {showPerFund ? '▾' : '▸'} Per-{fundNoun.replace(/s$/i, '')} breakdown
        </button>
        {showPerFund && (
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
                {mode === 'stock' && <Th></Th>}
              </tr>
            </thead>
            <tbody>
              {perSort.sorted.map((r, i) => (
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
        )}
      </div>

      {allEntities.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">{entityLabel} holding % over time</h4>
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
          {movers.length > 0 && (
            <div className="mt-6 space-y-4">
              <p className="text-xs text-slate-500">Biggest movers</p>
              {movers.map((ent) => (
                <HoldingTrendChart key={ent} raw={raw} entity={ent} height={220} yTitle={yTitle} />
              ))}
            </div>
          )}
        </div>
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
  /** MF holdings return company names — resolve to NSE symbols when adding. */
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
