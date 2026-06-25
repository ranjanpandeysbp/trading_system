import { StatCard } from '../ui/StatCard'
import { DataTable, Th, Td } from '../ui/Table'
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
  if (!g.length && !l.length) {
    return <p className="text-sm text-slate-500">{emptyMessage}</p>
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h4 className="mb-2 text-sm font-medium text-emerald-400">Gainers</h4>
        <DataTable>
          <thead><tr><Th>Symbol</Th><Th>%</Th><Th>Last</Th></tr></thead>
          <tbody>
            {(gainers ?? []).length === 0 ? (
              <tr><td colSpan={3} className="whitespace-nowrap border-b border-slate-800/40 px-3 py-2.5 text-xs text-slate-500 sm:px-4 sm:py-3 sm:text-sm">No gainers</td></tr>
            ) : (gainers ?? []).map((r) => (
              <tr key={String(r.symbol)}>
                <Td>{String(r.symbol)}</Td>
                <Td className="text-emerald-400">{fmtPct(Number(r.pct))}</Td>
                <Td>{fmtPrice(Number(r.last))}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </div>
      <div>
        <h4 className="mb-2 text-sm font-medium text-rose-400">Losers</h4>
        <DataTable>
          <thead><tr><Th>Symbol</Th><Th>%</Th><Th>Last</Th></tr></thead>
          <tbody>
            {(losers ?? []).length === 0 ? (
              <tr><td colSpan={3} className="whitespace-nowrap border-b border-slate-800/40 px-3 py-2.5 text-xs text-slate-500 sm:px-4 sm:py-3 sm:text-sm">No losers</td></tr>
            ) : (losers ?? []).map((r) => (
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
                <tr><Th>Index</Th><Th>S1</Th><Th>S2</Th><Th>R1</Th><Th>R2</Th></tr>
              </thead>
              <tbody>
                {Object.entries(srMap).map(([name, sr]) => (
                  <tr key={name}>
                    <Td>{name}</Td>
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
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!items.length) return <p className="text-sm text-slate-500">No breadth data available.</p>
  return (
    <div>
      <p className="mb-4 text-sm text-slate-500">Showing {items.length} of {Number(data.total ?? 0)} indices</p>
      <DataTable>
        <thead>
          <tr><Th>Index</Th><Th>Group</Th><Th>Adv</Th><Th>Dec</Th><Th>Unch</Th><Th>% Chg</Th><Th>Last</Th></tr>
        </thead>
        <tbody>
          {items.map((row) => (
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

function SectorWindowTable({ title, window }: { title: string; window?: Row }) {
  const sectors = (window?.sectors as Row[]) ?? []
  if (!sectors.length) return null
  return (
    <div>
      <h4 className="mb-2 text-sm font-medium text-slate-300">{title}</h4>
      <DataTable>
        <thead><tr><Th>Sector</Th><Th>Return</Th><Th>vs Nifty</Th><Th>Last</Th></tr></thead>
        <tbody>
          {sectors.slice(0, 15).map((s) => (
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
        <SectorWindowTable key={w.key} title={w.title} window={data[w.key] as Row} />
      ))}
      <div className="grid gap-4 md:grid-cols-2">
        <InflowOutflow title="Top performers" rows={(data.daily as Row)?.inflow as Row[] ?? (data.minutes as Row)?.inflow as Row[]} />
        <InflowOutflow title="Laggards" rows={(data.daily as Row)?.outflow as Row[] ?? (data.minutes as Row)?.outflow as Row[]} negative />
      </div>
    </div>
  )
}

function InflowOutflow({ title, rows, negative }: { title: string; rows?: Row[]; negative?: boolean }) {
  return (
    <div>
      <h4 className={`mb-2 text-sm font-medium ${negative ? 'text-rose-400' : 'text-emerald-400'}`}>{title}</h4>
      <DataTable>
        <thead><tr><Th>Name</Th><Th>%</Th></tr></thead>
        <tbody>
          {(rows ?? []).map((r) => (
            <tr key={String(r.name)}>
              <Td>{String(r.name).replace('NIFTY ', '')}</Td>
              <Td className={pctClass(Number(r.pct))}>{fmtPct(Number(r.pct))}</Td>
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
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  const highs = (data.at_52w_high as Row[]) ?? []
  const lows = (data.at_52w_low as Row[]) ?? []
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{String(data.index)} · {Number(data.constituent_count)} constituents scanned</p>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-medium text-emerald-400">Near 52W High</h4>
          <DataTable>
            <thead><tr><Th>Symbol</Th><Th>LTP</Th><Th>High</Th><Th>Dist %</Th></tr></thead>
            <tbody>
              {highs.slice(0, 15).map((r) => (
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
        <div>
          <h4 className="mb-2 text-sm font-medium text-rose-400">Near 52W Low</h4>
          <DataTable>
            <thead><tr><Th>Symbol</Th><Th>LTP</Th><Th>Low</Th><Th>Dist %</Th></tr></thead>
            <tbody>
              {lows.slice(0, 15).map((r) => (
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
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  const consensus = data.consensus as Row | undefined
  const plans = (data.plans as Row[]) ?? []
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
          <thead><tr><Th>Window</Th><Th>Long</Th><Th>Short</Th><Th>Edge %</Th><Th>Conf</Th></tr></thead>
          <tbody>
            {plans.map((p) => {
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
  return (
    <div className="space-y-4">
      {errors.length > 0 && <Alert type="error">{errors.map((e) => String(e.error)).join('; ')}</Alert>}
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-medium text-emerald-400">Bullish bias</h4>
          <DataTable>
            <thead><tr><Th>Ticker</Th><Th>Conf</Th><Th>Direction</Th></tr></thead>
            <tbody>
              {bullish.map((r) => (
                <tr key={String(r.ticker)}>
                  <Td>{String(r.ticker)}</Td>
                  <Td>{String(r.confidence_pct ?? `${Number(r.confidence).toFixed(0)}%`)}</Td>
                  <Td>{String(r.trade_direction ?? r.direction ?? r.bias)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <div>
          <h4 className="mb-2 text-sm font-medium text-rose-400">Bearish bias</h4>
          <DataTable>
            <thead><tr><Th>Ticker</Th><Th>Conf</Th><Th>Direction</Th></tr></thead>
            <tbody>
              {bearish.map((r) => (
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
  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  const commodities = (data.commodities as Row[]) ?? []
  const niftySignals = (data.nifty_signals as Row[]) ?? []
  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Commodity stance</SectionTitle>
        <div className="mt-3 overflow-x-auto">
          <DataTable>
            <thead><tr><Th>Commodity</Th><Th>Price</Th><Th>Avg chg</Th><Th>Consensus</Th></tr></thead>
            <tbody>
              {commodities.map((c) => (
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
              <thead><tr><Th>Index</Th><Th>Direction</Th><Th>Conf</Th><Th>Commodity</Th></tr></thead>
              <tbody>
                {niftySignals.slice(0, 10).map((s, i) => (
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
