import { StatCard } from '../ui/StatCard'
import { DataTable, Td, SortableTh, useSort } from '../ui/Table'
import { Alert } from '../ui/Feedback'
import { Card } from '../ui/Card'

type Row = Record<string, unknown>

function fmtPct(n?: number | null, digits = 2) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const v = Number(n)
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}%`
}

function fmtCr(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`
}

function fmtPrice(n?: number | null, currency = '₹') {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return `${currency}${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function pctClass(v?: number | null) {
  if (v == null) return 'text-slate-400'
  return Number(v) >= 0 ? 'text-emerald-400' : 'text-rose-400'
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">{children}</h3>
}

export function MoversTable({ gainers, losers, emptyMessage = 'No mover data' }: { gainers?: Row[]; losers?: Row[]; emptyMessage?: string }) {
  const g = gainers ?? []
  const l = losers ?? []
  const moverAccessors = {
    symbol: (r: Row) => String(r.symbol ?? ''),
    pct: (r: Row) => Number(r.pct),
    last: (r: Row) => Number(r.last),
  }
  const gainersSort = useSort(g, moverAccessors)
  const losersSort = useSort(l, moverAccessors)
  if (!g.length && !l.length) {
    return <p className="text-sm text-slate-500">{emptyMessage}</p>
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="min-w-0">
        <h4 className="mb-2 text-sm font-medium text-emerald-400">Gainers</h4>
        <DataTable>
          <thead><tr>
            <SortableTh active={gainersSort.sortKey === 'symbol'} direction={gainersSort.sortDir} onSort={() => gainersSort.handleSort('symbol')}>Symbol</SortableTh>
            <SortableTh active={gainersSort.sortKey === 'pct'} direction={gainersSort.sortDir} onSort={() => gainersSort.handleSort('pct')}>%</SortableTh>
            <SortableTh active={gainersSort.sortKey === 'last'} direction={gainersSort.sortDir} onSort={() => gainersSort.handleSort('last')}>Last</SortableTh>
          </tr></thead>
          <tbody>
            {g.length === 0 ? (
              <tr><td colSpan={3} className="whitespace-nowrap border-b border-slate-800/40 px-3 py-2.5 text-xs text-slate-500 sm:px-4 sm:py-3 sm:text-sm">No gainers</td></tr>
            ) : gainersSort.sorted.map((r) => (
              <tr key={String(r.symbol)}>
                <Td>{String(r.symbol)}</Td>
                <Td className="text-emerald-400">{fmtPct(Number(r.pct))}</Td>
                <Td>{fmtPrice(Number(r.last))}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </div>
      <div className="min-w-0">
        <h4 className="mb-2 text-sm font-medium text-rose-400">Losers</h4>
        <DataTable>
          <thead><tr>
            <SortableTh active={losersSort.sortKey === 'symbol'} direction={losersSort.sortDir} onSort={() => losersSort.handleSort('symbol')}>Symbol</SortableTh>
            <SortableTh active={losersSort.sortKey === 'pct'} direction={losersSort.sortDir} onSort={() => losersSort.handleSort('pct')}>%</SortableTh>
            <SortableTh active={losersSort.sortKey === 'last'} direction={losersSort.sortDir} onSort={() => losersSort.handleSort('last')}>Last</SortableTh>
          </tr></thead>
          <tbody>
            {l.length === 0 ? (
              <tr><td colSpan={3} className="whitespace-nowrap border-b border-slate-800/40 px-3 py-2.5 text-xs text-slate-500 sm:px-4 sm:py-3 sm:text-sm">No losers</td></tr>
            ) : losersSort.sorted.map((r) => (
              <tr key={String(r.symbol)}>
                <Td>{String(r.symbol)}</Td>
                <Td className="text-rose-400">{fmtPct(Number(r.pct))}</Td>
                <Td>{fmtPrice(Number(r.last))}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </div>
    </div>
  )
}

export function TomorrowOutlookPanel({ data }: { data: Row }) {
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  const drivers = (data.drivers as string[]) ?? []
  const explanation = String(data.explanation ?? '').replace(/<[^>]+>/g, '')
  const score = Number(data.score ?? 0)
  const borderColor = String(data.border_color ?? '#334155')
  const color = String(data.color ?? '#10b981')

  return (
    <div className="space-y-4">
      <div
        className="rounded-2xl border px-4 py-5 sm:px-6"
        style={{
          borderColor,
          background: `linear-gradient(135deg, ${color}22, transparent)`,
        }}
      >
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Tomorrow&apos;s Market</p>
        <p className="mt-1 text-xl font-bold text-white sm:text-2xl">
          {String(data.emoji ?? '')} {String(data.label ?? data.verdict ?? 'Outlook')}
        </p>
        <div className="mt-3 flex flex-wrap gap-3 text-sm">
          <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
            Score: <strong className={score >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{score > 0 ? '+' : ''}{score}</strong>
          </span>
          <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
            Confidence: <strong>{String(data.confidence ?? '—')}</strong>
          </span>
          <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
            Verdict: <strong>{String(data.verdict ?? '—')}</strong>
          </span>
        </div>
        {explanation && <p className="mt-4 text-sm leading-relaxed text-slate-300">{explanation}</p>}
      </div>
      {drivers.length > 0 && (
        <div>
          <SectionTitle>Key drivers</SectionTitle>
          <ul className="mt-2 space-y-1.5 text-sm text-slate-300">
            {drivers.map((d) => <li key={d} className="flex gap-2"><span className="text-slate-500">•</span>{d}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

export function IntelligencePanel({ data }: { data: Row }) {
  const marketData = (data.market_data as Record<string, { price?: number; pct?: number; day_high?: number; day_low?: number }>) ?? {}
  const sentiment = data.market_sentiment as Row | undefined
  const optSent = data.sentiment as Row | undefined
  const fiiDii = data.fii_dii_data as Row | undefined
  const options = data.option_data as Row | undefined
  const srMap = (data.index_sr_map as Record<string, { s1?: number; s2?: number; r1?: number; r2?: number }>) ?? {}
  const turnover = data.turnover_delivery_data as Row | undefined
  const news = (data.news_articles as Row[]) ?? []
  const events = (data.india_events as Row[]) ?? []
  const optReasons = (optSent?.reasons as string[]) ?? []
  const signals = (sentiment?.signals as string[]) ?? []

  const fiiNet = Number((fiiDii?.fii as Row)?.net_cr)
  const diiNet = Number((fiiDii?.dii as Row)?.net_cr)

  const srRows = Object.entries(srMap).map(([name, sr]) => ({ name, ...sr }))
  const srSort = useSort(srRows, {
    name: (r) => r.name,
    s1: (r) => r.s1,
    s2: (r) => r.s2,
    r1: (r) => r.r1,
    r2: (r) => r.r2,
  })

  return (
    <div className="space-y-6">
      {data.tomorrow_outlook != null ? (
        <TomorrowOutlookPanel data={data.tomorrow_outlook as Row} />
      ) : null}
      {sentiment && (
        <div
          className="rounded-2xl border px-4 py-4 sm:px-5"
          style={{
            borderColor: String(sentiment.border_color ?? '#334155'),
            background: `linear-gradient(135deg, ${String(sentiment.color ?? '#10b981')}18, transparent)`,
          }}
        >
          <p className="text-lg font-semibold text-white">
            {String(sentiment.emoji ?? '')} Today&apos;s Market: {String(sentiment.label ?? sentiment.verdict)}
          </p>
          {signals.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm text-slate-300">
              {signals.map((s) => <li key={s}>{s}</li>)}
            </ul>
          )}
        </div>
      )}

      <div>
        <SectionTitle>Indian Markets</SectionTitle>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Object.entries(marketData).map(([name, q]) => (
            <div key={name} className="rounded-xl border border-slate-800/60 bg-slate-800/30 p-3">
              <p className="truncate text-xs text-slate-500">{name}</p>
              <p className="text-lg font-semibold tabular-nums text-white">{fmtPrice(q.price, name.includes('USD') || name.includes('Yield') ? '' : '₹')}</p>
              <p className={`text-sm tabular-nums ${pctClass(q.pct)}`}>{fmtPct(q.pct)}</p>
              {q.day_high != null && q.day_low != null && (
                <p className="mt-1 text-xs text-slate-500">H {fmtPrice(q.day_high)} · L {fmtPrice(q.day_low)}</p>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="FII Net" value={fmtCr(fiiNet)} trend={fiiNet >= 0 ? 'up' : 'down'} />
        <StatCard label="DII Net" value={fmtCr(diiNet)} trend={diiNet >= 0 ? 'up' : 'down'} />
        <StatCard label="PCR (OI)" value={options?.pcr_oi != null ? Number(options.pcr_oi).toFixed(2) : '—'} trend={Number(options?.pcr_oi) >= 1 ? 'up' : 'down'} />
        <StatCard label="Max Pain" value={options?.max_pain != null ? fmtPrice(Number(options.max_pain)) : '—'} />
      </div>

      {optSent && (
        <Card className="!p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-white">Options Sentiment</span>
            <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs text-emerald-300">{String(optSent.verdict ?? '')}</span>
          </div>
          {optReasons.length > 0 && (
            <ul className="mt-3 space-y-2 text-sm text-slate-300">
              {optReasons.slice(0, 5).map((r) => (
                <li key={r} className="leading-relaxed" dangerouslySetInnerHTML={{ __html: r.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>') }} />
              ))}
            </ul>
          )}
        </Card>
      )}

      {Object.keys(srMap).length > 0 && (
        <div>
          <SectionTitle>Index Support / Resistance</SectionTitle>
          <div className="mt-3 overflow-x-auto">
            <DataTable>
              <thead>
                <tr>
                  <SortableTh active={srSort.sortKey === 'name'} direction={srSort.sortDir} onSort={() => srSort.handleSort('name')}>Index</SortableTh>
                  <SortableTh active={srSort.sortKey === 's1'} direction={srSort.sortDir} onSort={() => srSort.handleSort('s1')}>S1</SortableTh>
                  <SortableTh active={srSort.sortKey === 's2'} direction={srSort.sortDir} onSort={() => srSort.handleSort('s2')}>S2</SortableTh>
                  <SortableTh active={srSort.sortKey === 'r1'} direction={srSort.sortDir} onSort={() => srSort.handleSort('r1')}>R1</SortableTh>
                  <SortableTh active={srSort.sortKey === 'r2'} direction={srSort.sortDir} onSort={() => srSort.handleSort('r2')}>R2</SortableTh>
                </tr>
              </thead>
              <tbody>
                {srSort.sorted.map((sr) => (
                  <tr key={sr.name}>
                    <Td>{sr.name}</Td>
                    <Td className="tabular-nums">{fmtPrice(sr.s1)}</Td>
                    <Td className="tabular-nums">{fmtPrice(sr.s2)}</Td>
                    <Td className="tabular-nums">{fmtPrice(sr.r1)}</Td>
                    <Td className="tabular-nums">{fmtPrice(sr.r2)}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </div>
        </div>
      )}

      {turnover && (
        <div>
          <SectionTitle>Cash Market · {String(turnover.trade_date ?? '')}</SectionTitle>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <StatCard label="Total Turnover" value={fmtCr(Number(turnover.total_turnover_cr))} />
            <StatCard label="Stocks Traded" value={String(turnover.total_stocks ?? '—')} />
            <StatCard label="Avg Delivery %" value={turnover.avg_delivery_pct != null ? `${Number(turnover.avg_delivery_pct).toFixed(1)}%` : '—'} />
          </div>
        </div>
      )}

      {news.length > 0 && (
        <div>
          <SectionTitle>Market News</SectionTitle>
          <div className="mt-3 max-h-80 space-y-2 overflow-y-auto">
            {news.slice(0, 12).map((a, i) => (
              <a
                key={`${a.link}-${i}`}
                href={String(a.link)}
                target="_blank"
                rel="noreferrer"
                className="block rounded-xl border border-slate-800/60 bg-slate-800/20 p-3 transition-colors hover:border-slate-700 hover:bg-slate-800/40"
              >
                <p className="text-sm font-medium text-white">{String(a.title)}</p>
                <p className="mt-1 text-xs text-slate-500">{String(a.source)} · {String(a.published)}</p>
                {a.summary != null && <p className="mt-2 line-clamp-2 text-xs text-slate-400">{String(a.summary)}</p>}
              </a>
            ))}
          </div>
        </div>
      )}

      {events.length > 0 && (
        <div>
          <SectionTitle>Upcoming India Events</SectionTitle>
          <div className="mt-3 space-y-2">
            {events.map((ev) => (
              <div key={String(ev.title)} className="flex items-start justify-between gap-3 rounded-xl border border-slate-800/60 bg-slate-800/20 px-3 py-2.5">
                <div>
                  <p className="text-sm font-medium text-white">{String(ev.title)}</p>
                  <p className="text-xs text-slate-500">{String(ev.detail)}</p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-xs text-slate-400">{String(ev.date)}</p>
                  <span className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    ev.impact === 'HIGH' ? 'bg-rose-500/20 text-rose-300' : 'bg-slate-700 text-slate-300'
                  }`}>{String(ev.impact)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function BreadthPanel({ data }: { data: Row }) {
  const items = (data.items as Row[]) ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(items, {
    index_name: (r) => String(r.index_name ?? ''),
    group: (r) => String(r.group ?? ''),
    advances: (r) => Number(r.advances),
    declines: (r) => Number(r.declines),
    unchanged: (r) => Number(r.unchanged),
    pct_change: (r) => Number(r.pct_change),
    last: (r) => Number(r.last),
  })
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!items.length) return <p className="text-sm text-slate-500">No breadth data available.</p>
  return (
    <div>
      <p className="mb-4 text-sm text-slate-500">Showing {items.length} of {Number(data.total ?? 0)} indices</p>
      <DataTable>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'index_name'} direction={sortDir} onSort={() => handleSort('index_name')}>Index</SortableTh>
            <SortableTh active={sortKey === 'group'} direction={sortDir} onSort={() => handleSort('group')}>Group</SortableTh>
            <SortableTh active={sortKey === 'advances'} direction={sortDir} onSort={() => handleSort('advances')}>Adv</SortableTh>
            <SortableTh active={sortKey === 'declines'} direction={sortDir} onSort={() => handleSort('declines')}>Dec</SortableTh>
            <SortableTh active={sortKey === 'unchanged'} direction={sortDir} onSort={() => handleSort('unchanged')}>Unch</SortableTh>
            <SortableTh active={sortKey === 'pct_change'} direction={sortDir} onSort={() => handleSort('pct_change')}>% Chg</SortableTh>
            <SortableTh active={sortKey === 'last'} direction={sortDir} onSort={() => handleSort('last')}>Last</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={String(row.index_name)}>
              <Td>{String(row.index_name)}</Td>
              <Td className="text-slate-400">{String(row.group ?? '')}</Td>
              <Td className="text-emerald-400">{String(row.advances ?? '—')}</Td>
              <Td className="text-rose-400">{String(row.declines ?? '—')}</Td>
              <Td>{String(row.unchanged ?? '—')}</Td>
              <Td className={pctClass(Number(row.pct_change))}>{fmtPct(Number(row.pct_change))}</Td>
              <Td>{fmtPrice(Number(row.last))}</Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  )
}

export function MonthlyPanel({ data }: { data: Row }) {
  const items = (data.items as Row[]) ?? []
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!items.length) return <p className="text-sm text-slate-500">No monthly performance data available.</p>
  return (
    <div className="space-y-4">
      {items.map((block) => (
        <Card key={String(block.index_name)} className="!p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-medium text-white">{String(block.index_name)}</h4>
            <span className={`text-sm tabular-nums ${pctClass(Number(block.index_return_pct))}`}>
              Index 1M: {fmtPct(Number(block.index_return_pct))}
            </span>
          </div>
          {block.movers != null && (
            <MoversTable
              gainers={(block.movers as { gainers?: Row[] }).gainers}
              losers={(block.movers as { losers?: Row[] }).losers}
            />
          )}
        </Card>
      ))}
    </div>
  )
}

function SectorWindowTable({ title, window, benchmarkLabel = 'Nifty' }: { title: string; window?: Row; benchmarkLabel?: string }) {
  const sectors = (window?.sectors as Row[]) ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(sectors, {
    name: (r) => String(r.name ?? ''),
    pct: (r) => Number(r.pct),
    relative: (r) => Number(r.relative),
    last: (r) => Number(r.last),
  })
  if (!sectors.length) return null
  return (
    <div>
      <h4 className="mb-2 text-sm font-medium text-slate-300">{title}</h4>
      <DataTable>
        <thead><tr>
          <SortableTh active={sortKey === 'name'} direction={sortDir} onSort={() => handleSort('name')}>Sector</SortableTh>
          <SortableTh active={sortKey === 'pct'} direction={sortDir} onSort={() => handleSort('pct')}>Return</SortableTh>
          <SortableTh active={sortKey === 'relative'} direction={sortDir} onSort={() => handleSort('relative')}>vs {benchmarkLabel}</SortableTh>
          <SortableTh active={sortKey === 'last'} direction={sortDir} onSort={() => handleSort('last')}>Last</SortableTh>
        </tr></thead>
        <tbody>
          {sorted.slice(0, 15).map((s) => (
            <tr key={String(s.name)}>
              <Td>{String(s.name).replace('NIFTY ', '')}</Td>
              <Td className={pctClass(Number(s.pct))}>{fmtPct(Number(s.pct))}</Td>
              <Td className={pctClass(Number(s.relative))}>{fmtPct(Number(s.relative))}</Td>
              <Td>{fmtPrice(Number(s.last))}</Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  )
}

export function SectorRotationPanel({ data, intraday = false }: { data: Row; intraday?: boolean }) {
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  const windows = intraday
    ? [
        { title: 'Minutes', key: 'minutes' },
        { title: 'Hours', key: 'hours' },
        { title: 'Days', key: 'days' },
      ]
    : [
        { title: 'Daily', key: 'daily' },
        { title: 'Weekly', key: 'weekly' },
        { title: 'Monthly', key: 'monthly' },
      ]
  const hasData = windows.some((w) => ((data[w.key] as Row)?.sectors as Row[] | undefined)?.length)
  if (!hasData) {
    return <p className="text-sm text-slate-500">Sector rotation data unavailable. Try again after market hours or check Groww token in Settings.</p>
  }
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-500">Data feed: {String(data.data_feed ?? 'yfinance')}</p>
      {windows.map((w) => (
        <SectorWindowTable
          key={w.key}
          title={w.title}
          window={data[w.key] as Row}
          benchmarkLabel={data.benchmark_symbol ? String(data.benchmark_symbol) : 'Nifty'}
        />
      ))}
      <div className="grid gap-4 md:grid-cols-2">
        <InflowOutflow title="Top performers" rows={(data.daily as Row)?.inflow as Row[] ?? (data.minutes as Row)?.inflow as Row[]} />
        <InflowOutflow title="Laggards" rows={(data.daily as Row)?.outflow as Row[] ?? (data.minutes as Row)?.outflow as Row[]} negative />
      </div>
    </div>
  )
}

function InflowOutflow({ title, rows, negative }: { title: string; rows?: Row[]; negative?: boolean }) {
  const r = rows ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(r, {
    name: (row) => String(row.name ?? ''),
    pct: (row) => Number(row.pct),
  })
  return (
    <div className="min-w-0">
      <h4 className={`mb-2 text-sm font-medium ${negative ? 'text-rose-400' : 'text-emerald-400'}`}>{title}</h4>
      <DataTable>
        <thead><tr>
          <SortableTh active={sortKey === 'name'} direction={sortDir} onSort={() => handleSort('name')}>Name</SortableTh>
          <SortableTh active={sortKey === 'pct'} direction={sortDir} onSort={() => handleSort('pct')}>%</SortableTh>
        </tr></thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={String(row.name)}>
              <Td>{String(row.name).replace('NIFTY ', '')}</Td>
              <Td className={pctClass(Number(row.pct))}>{fmtPct(Number(row.pct))}</Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  )
}

export function StockRotationPanel({ data }: { data: Row }) {
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">
        {String(data.index_name)} · {String(data.tf_key)} · benchmark {fmtPct(Number(data.benchmark_pct))} · {String(data.stock_count)} stocks
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <InflowOutflow title="Inflow (top relative strength)" rows={data.inflow as Row[]} />
        <InflowOutflow title="Outflow (relative weakness)" rows={data.outflow as Row[]} negative />
      </div>
    </div>
  )
}

export function Week52Panel({ data }: { data: Row }) {
  const highs = (data.at_52w_high as Row[]) ?? []
  const lows = (data.at_52w_low as Row[]) ?? []
  const highsSort = useSort(highs, {
    symbol: (r) => String(r.symbol ?? ''),
    ltp: (r) => Number(r.ltp ?? r.last),
    high_52w: (r) => Number(r.high_52w),
    dist: (r) => Number(r.dist_from_high_pct ?? r.pct_from_high),
  })
  const lowsSort = useSort(lows, {
    symbol: (r) => String(r.symbol ?? ''),
    ltp: (r) => Number(r.ltp ?? r.last),
    low_52w: (r) => Number(r.low_52w),
    dist: (r) => Number(r.dist_from_low_pct ?? r.pct_from_low),
  })
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{String(data.index)} · {Number(data.constituent_count)} constituents scanned</p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="min-w-0">
          <h4 className="mb-2 text-sm font-medium text-emerald-400">Near 52W High</h4>
          <DataTable>
            <thead><tr>
              <SortableTh active={highsSort.sortKey === 'symbol'} direction={highsSort.sortDir} onSort={() => highsSort.handleSort('symbol')}>Symbol</SortableTh>
              <SortableTh active={highsSort.sortKey === 'ltp'} direction={highsSort.sortDir} onSort={() => highsSort.handleSort('ltp')}>LTP</SortableTh>
              <SortableTh active={highsSort.sortKey === 'high_52w'} direction={highsSort.sortDir} onSort={() => highsSort.handleSort('high_52w')}>High</SortableTh>
              <SortableTh active={highsSort.sortKey === 'dist'} direction={highsSort.sortDir} onSort={() => highsSort.handleSort('dist')}>Dist %</SortableTh>
            </tr></thead>
            <tbody>
              {highsSort.sorted.slice(0, 15).map((r) => (
                <tr key={String(r.symbol)}>
                  <Td>{String(r.symbol)}</Td>
                  <Td>{fmtPrice(Number(r.ltp ?? r.last))}</Td>
                  <Td>{fmtPrice(Number(r.high_52w))}</Td>
                  <Td>{fmtPct(Number(r.dist_from_high_pct ?? r.pct_from_high))}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <div className="min-w-0">
          <h4 className="mb-2 text-sm font-medium text-rose-400">Near 52W Low</h4>
          <DataTable>
            <thead><tr>
              <SortableTh active={lowsSort.sortKey === 'symbol'} direction={lowsSort.sortDir} onSort={() => lowsSort.handleSort('symbol')}>Symbol</SortableTh>
              <SortableTh active={lowsSort.sortKey === 'ltp'} direction={lowsSort.sortDir} onSort={() => lowsSort.handleSort('ltp')}>LTP</SortableTh>
              <SortableTh active={lowsSort.sortKey === 'low_52w'} direction={lowsSort.sortDir} onSort={() => lowsSort.handleSort('low_52w')}>Low</SortableTh>
              <SortableTh active={lowsSort.sortKey === 'dist'} direction={lowsSort.sortDir} onSort={() => lowsSort.handleSort('dist')}>Dist %</SortableTh>
            </tr></thead>
            <tbody>
              {lowsSort.sorted.slice(0, 15).map((r) => (
                <tr key={String(r.symbol)}>
                  <Td>{String(r.symbol)}</Td>
                  <Td>{fmtPrice(Number(r.ltp ?? r.last))}</Td>
                  <Td>{fmtPrice(Number(r.low_52w))}</Td>
                  <Td>{fmtPct(Number(r.dist_from_low_pct ?? r.pct_from_low))}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      </div>
    </div>
  )
}

export function HeatmapPanel({ data }: { data: Row }) {
  const rows = (data.rows as Row[]) ?? []
  if (!rows.length) {
    return <p className="text-sm text-slate-500">No heatmap data — add a Groww API token in Settings for live sector indices, or try again later.</p>
  }
  return (
    <div>
      <p className="mb-4 text-sm text-slate-500">Timeframe: {String(data.timeframe)}</p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {rows.map((r) => {
          const pct = Number(r.change ?? r.pct ?? 0)
          const intensity = Math.min(Math.abs(pct) / 3, 1)
          const bg = pct >= 0
            ? `rgba(16, 185, 129, ${0.15 + intensity * 0.45})`
            : `rgba(244, 63, 94, ${0.15 + intensity * 0.45})`
          const label = String(r.ticker ?? r.name ?? r.symbol)
          return (
            <div key={label} className="rounded-xl border border-slate-800/60 p-3" style={{ background: bg }}>
              <p className="truncate text-sm font-medium text-white">{label}</p>
              <p className={`text-lg font-semibold tabular-nums ${pctClass(pct)}`}>{fmtPct(pct)}</p>
              <p className="text-xs text-slate-400">{fmtPrice(Number(r.price ?? r.ltp))}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function HedgePanel({ data }: { data: Row }) {
  const plans = (data.plans as Row[]) ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(plans, {
    window: (p) => String(p.window_label ?? p.window_key ?? ''),
    long: (p) => String((p.long as Row | undefined)?.sector ?? (p.long as Row | undefined)?.ticker ?? ''),
    short: (p) => String((p.short as Row | undefined)?.sector ?? (p.short as Row | undefined)?.ticker ?? ''),
    edge: (p) => Number(p.spread_edge_pct),
    conf: (p) => Number(p.confidence_pct),
  })
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  const consensus = data.consensus as Row | undefined
  const longLeg = consensus?.long as Row | undefined
  const shortLeg = consensus?.short as Row | undefined
  return (
    <div className="space-y-4">
      {consensus && (
        <Card className="!p-4">
          <p className="text-sm text-slate-400">Consensus hedge pair</p>
          <p className="mt-1 text-white">
            Long <strong>{String(consensus.long_sector ?? longLeg?.sector ?? consensus.long_ticker)}</strong>
            {' · '}
            Short <strong>{String(consensus.short_sector ?? shortLeg?.sector ?? consensus.short_ticker)}</strong>
          </p>
          <p className="mt-2 text-xs text-slate-500">
            {String(consensus.long_ticker)} vs {String(consensus.short_ticker)} · confidence {Number(consensus.consensus_confidence_pct).toFixed(0)}%
          </p>
        </Card>
      )}
      {plans.length > 0 && (
        <DataTable>
          <thead><tr>
            <SortableTh active={sortKey === 'window'} direction={sortDir} onSort={() => handleSort('window')}>Window</SortableTh>
            <SortableTh active={sortKey === 'long'} direction={sortDir} onSort={() => handleSort('long')}>Long</SortableTh>
            <SortableTh active={sortKey === 'short'} direction={sortDir} onSort={() => handleSort('short')}>Short</SortableTh>
            <SortableTh active={sortKey === 'edge'} direction={sortDir} onSort={() => handleSort('edge')}>Edge %</SortableTh>
            <SortableTh active={sortKey === 'conf'} direction={sortDir} onSort={() => handleSort('conf')}>Conf</SortableTh>
          </tr></thead>
          <tbody>
            {sorted.map((p) => {
              const long = p.long as Row | undefined
              const short = p.short as Row | undefined
              return (
                <tr key={String(p.window_key ?? p.window_label)}>
                  <Td>{String(p.window_label ?? p.window_key)}</Td>
                  <Td className="text-emerald-400">{String(long?.sector ?? long?.ticker)}</Td>
                  <Td className="text-rose-400">{String(short?.sector ?? short?.ticker)}</Td>
                  <Td>{fmtPct(Number(p.spread_edge_pct))}</Td>
                  <Td>{Number(p.confidence_pct).toFixed(0)}%</Td>
                </tr>
              )
            })}
          </tbody>
        </DataTable>
      )}
    </div>
  )
}

export function MtfBiasPanel({ data }: { data: Row }) {
  const bullish = (data.bullish as Row[]) ?? []
  const bearish = (data.bearish as Row[]) ?? []
  const errors = (data.errors as Row[]) ?? []
  const biasAccessors = {
    ticker: (r: Row) => String(r.ticker ?? ''),
    confidence: (r: Row) => Number(r.confidence),
    direction: (r: Row) => String(r.trade_direction ?? r.direction ?? r.bias ?? ''),
  }
  const bullishSort = useSort(bullish, biasAccessors)
  const bearishSort = useSort(bearish, biasAccessors)
  return (
    <div className="space-y-4">
      {errors.length > 0 && <Alert type="error">{errors.map((e) => String(e.error)).join('; ')}</Alert>}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="min-w-0">
          <h4 className="mb-2 text-sm font-medium text-emerald-400">Bullish bias</h4>
          <DataTable>
            <thead><tr>
              <SortableTh active={bullishSort.sortKey === 'ticker'} direction={bullishSort.sortDir} onSort={() => bullishSort.handleSort('ticker')}>Ticker</SortableTh>
              <SortableTh active={bullishSort.sortKey === 'confidence'} direction={bullishSort.sortDir} onSort={() => bullishSort.handleSort('confidence')}>Conf</SortableTh>
              <SortableTh active={bullishSort.sortKey === 'direction'} direction={bullishSort.sortDir} onSort={() => bullishSort.handleSort('direction')}>Direction</SortableTh>
            </tr></thead>
            <tbody>
              {bullishSort.sorted.map((r) => (
                <tr key={String(r.ticker)}>
                  <Td>{String(r.ticker)}</Td>
                  <Td>{String(r.confidence_pct ?? `${Number(r.confidence).toFixed(0)}%`)}</Td>
                  <Td>{String(r.trade_direction ?? r.direction ?? r.bias)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <div className="min-w-0">
          <h4 className="mb-2 text-sm font-medium text-rose-400">Bearish bias</h4>
          <DataTable>
            <thead><tr>
              <SortableTh active={bearishSort.sortKey === 'ticker'} direction={bearishSort.sortDir} onSort={() => bearishSort.handleSort('ticker')}>Ticker</SortableTh>
              <SortableTh active={bearishSort.sortKey === 'confidence'} direction={bearishSort.sortDir} onSort={() => bearishSort.handleSort('confidence')}>Conf</SortableTh>
              <SortableTh active={bearishSort.sortKey === 'direction'} direction={bearishSort.sortDir} onSort={() => bearishSort.handleSort('direction')}>Direction</SortableTh>
            </tr></thead>
            <tbody>
              {bearishSort.sorted.map((r) => (
                <tr key={String(r.ticker)}>
                  <Td>{String(r.ticker)}</Td>
                  <Td>{String(r.confidence_pct ?? `${Number(r.confidence).toFixed(0)}%`)}</Td>
                  <Td>{String(r.trade_direction ?? r.direction ?? r.bias)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      </div>
    </div>
  )
}

export function CommodityPanel({ data }: { data: Row }) {
  const commodities = (data.commodities as Row[]) ?? []
  const niftySignals = (data.nifty_signals as Row[]) ?? []
  const commoditiesSort = useSort(commodities, {
    name: (c) => String(c.name ?? ''),
    price: (c) => Number(c.price),
    avg_change: (c) => Number(c.avg_change),
    consensus: (c) => String(c.consensus ?? ''),
  })
  const signalsSort = useSort(niftySignals, {
    ticker: (s) => String(s.ticker ?? s.sector ?? ''),
    direction: (s) => String(s.direction ?? ''),
    confidence: (s) => Number(s.confidence),
    commodity: (s) => String(s.commodity ?? ''),
  })
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Commodity stance</SectionTitle>
        <div className="mt-3 overflow-x-auto">
          <DataTable>
            <thead><tr>
              <SortableTh active={commoditiesSort.sortKey === 'name'} direction={commoditiesSort.sortDir} onSort={() => commoditiesSort.handleSort('name')}>Commodity</SortableTh>
              <SortableTh active={commoditiesSort.sortKey === 'price'} direction={commoditiesSort.sortDir} onSort={() => commoditiesSort.handleSort('price')}>Price</SortableTh>
              <SortableTh active={commoditiesSort.sortKey === 'avg_change'} direction={commoditiesSort.sortDir} onSort={() => commoditiesSort.handleSort('avg_change')}>Avg chg</SortableTh>
              <SortableTh active={commoditiesSort.sortKey === 'consensus'} direction={commoditiesSort.sortDir} onSort={() => commoditiesSort.handleSort('consensus')}>Consensus</SortableTh>
            </tr></thead>
            <tbody>
              {commoditiesSort.sorted.map((c) => (
                <tr key={String(c.symbol)}>
                  <Td>{String(c.name)}</Td>
                  <Td>{fmtPrice(Number(c.price))}</Td>
                  <Td className={pctClass(Number(c.avg_change))}>{fmtPct(Number(c.avg_change))}</Td>
                  <Td>{String(c.consensus)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      </div>
      {niftySignals.length > 0 && (
        <div>
          <SectionTitle>Nifty index trade ideas</SectionTitle>
          <div className="mt-3 overflow-x-auto">
            <DataTable>
              <thead><tr>
                <SortableTh active={signalsSort.sortKey === 'ticker'} direction={signalsSort.sortDir} onSort={() => signalsSort.handleSort('ticker')}>Index</SortableTh>
                <SortableTh active={signalsSort.sortKey === 'direction'} direction={signalsSort.sortDir} onSort={() => signalsSort.handleSort('direction')}>Direction</SortableTh>
                <SortableTh active={signalsSort.sortKey === 'confidence'} direction={signalsSort.sortDir} onSort={() => signalsSort.handleSort('confidence')}>Conf</SortableTh>
                <SortableTh active={signalsSort.sortKey === 'commodity'} direction={signalsSort.sortDir} onSort={() => signalsSort.handleSort('commodity')}>Commodity</SortableTh>
              </tr></thead>
              <tbody>
                {signalsSort.sorted.map((s, i) => (
                  <tr key={`${s.ticker}-${i}`}>
                    <Td>{String(s.ticker ?? s.sector)}</Td>
                    <Td className={String(s.direction).toUpperCase().includes('BUY') ? 'text-emerald-400' : 'text-rose-400'}>{String(s.direction)}</Td>
                    <Td>{Number(s.confidence).toFixed(0)}%</Td>
                    <Td>{String(s.commodity)}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </div>
        </div>
      )}
    </div>
  )
}

export function AccurateStrategyPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!results.length) return <p className="text-sm text-slate-500">No Accurate Strategy results.</p>
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Actionable: <strong className="text-white">{String(data.entry_count ?? 0)}</strong>
        {data.strategy != null && <> · {String(data.strategy)}</>}
      </p>
      <DataTable>
        <thead>
          <tr>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Ticker</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Signal</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Score</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Entry / SL / TP</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Win rate</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => {
            const sig = (r.latest_signal as Row) || {}
            const summary = (r.summary as Row) || {}
            return (
              <tr key={String(r.ticker)}>
                <Td className="font-medium">{String(r.ticker)}</Td>
                <Td className={r.error ? 'text-rose-400' : 'text-slate-200'}>
                  {r.error ? String(r.error) : String(sig.side ?? sig.direction ?? '—').toUpperCase()}
                </Td>
                <Td>{sig.confluence_score != null ? String(sig.confluence_score) : '—'}</Td>
                <Td className="text-xs">
                  {sig.entry != null
                    ? `${sig.entry} / ${sig.stop ?? '—'} / ${sig.target ?? '—'}`
                    : '—'}
                </Td>
                <Td>{summary.win_rate_pct != null ? `${summary.win_rate_pct}%` : '—'}</Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>
    </div>
  )
}

export function PumpDumpBreakoutPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!results.length) return <p className="text-sm text-slate-500">No Pump/Dump Breakout results.</p>
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Actionable: <strong className="text-white">{String(data.entry_count ?? 0)}</strong>
      </p>
      <DataTable>
        <thead>
          <tr>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Symbol</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">24h %</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Live</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">R:R</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Note</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => {
            const live = (r.live as Row) || {}
            const setup = (live.latest_signal as Row) || {}
            const status = r.error
              ? String(r.error)
              : setup.side
                ? String(setup.side)
                : live.watch
                  ? 'WATCH (consolidating)'
                  : '—'
            return (
              <tr key={String(r.symbol)}>
                <Td className="font-medium">{String(r.symbol)}</Td>
                <Td className={pctClass(Number(r.change_24h_pct))}>{fmtPct(Number(r.change_24h_pct))}</Td>
                <Td>{status}</Td>
                <Td>{setup.rr_ratio != null ? `1:${setup.rr_ratio}` : '—'}</Td>
                <Td className="max-w-[14rem] truncate text-xs text-slate-400">
                  {setup.status
                    ? String(setup.status)
                    : live.is_consolidating
                      ? 'In consolidation box'
                      : String((r.screened as Row)?.reason ?? '—')}
                </Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>
    </div>
  )
}

export function BigWhalePanel({ data }: { data: Row }) {
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  const recs = (data.trade_recommendations as Row[]) ?? []
  const pumped = (data.pumped as Row[]) ?? []
  const watch = (data.watchlist as Row[]) ?? []
  const rows = recs.length ? recs : [...watch, ...pumped]
  if (!rows.length) return <p className="text-sm text-slate-500">No whale scan hits — try again later.</p>
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Recommendations: <strong className="text-white">{recs.length}</strong>
        {' · '}Pumped: <strong className="text-white">{pumped.length}</strong>
        {' · '}Watch: <strong className="text-white">{watch.length}</strong>
      </p>
      <DataTable>
        <thead>
          <tr>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Symbol</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Chain</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Pump 24h</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Role / Verdict</th>
            <th className="px-3 py-2 text-left text-xs text-slate-400">Conf</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const setup = (r.trade_setup as Row) || {}
            return (
              <tr key={`${r.symbol}-${i}`}>
                <Td className="font-medium">{String(r.symbol ?? r.base_symbol ?? '—')}</Td>
                <Td>{String(r.chain_id ?? r.chain ?? '—')}</Td>
                <Td className={pctClass(Number(r.pump_24h_pct))}>{fmtPct(Number(r.pump_24h_pct))}</Td>
                <Td>{String(r.role ?? r.verdict ?? setup.role ?? '—')}</Td>
                <Td>{setup.confidence_pct != null ? `${setup.confidence_pct}%` : '—'}</Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>
    </div>
  )
}
