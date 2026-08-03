import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiErrorMessage, runIndiaFiiDiiHoldings } from '../../api/client'
import {
  AssetClassTickerPicker,
  type TickerPickerValue,
} from './AssetClassTickerPicker'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import { AskAIPanel } from '../ai/AskAIPanel'
import { Alert, Loading } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField } from '../ui/Form'
import { DataTable, Td, Th } from '../ui/Table'

type Row = Record<string, unknown>

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function fmt(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

function trendClass(t: unknown): string {
  const s = String(t ?? '').toUpperCase()
  if (s === 'INCREASING' || s === 'YES' || s === 'GOOD') return 'text-emerald-400'
  if (s === 'DECREASING' || s === 'NO' || s === 'BAD') return 'text-rose-400'
  if (s === 'WAIT' || s === 'MIXED' || s === 'STABLE') return 'text-amber-400'
  return 'text-slate-300'
}

function timingBadge(v: unknown) {
  const s = String(v ?? '—').toUpperCase()
  if (s === 'YES') {
    return <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-300">YES · LONG bias</span>
  }
  if (s === 'NO') {
    return <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-xs font-semibold text-rose-300">NO · avoid / SHORT bias</span>
  }
  return <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-300">WAIT</span>
}

const CAT_COLORS: Record<string, string> = {
  Promoters: '#a78bfa',
  FIIs: '#10b981',
  DIIs: '#06b6d4',
  Public: '#f59e0b',
}

function OwnershipChart({ rows, ticker }: { rows: Row[]; ticker: string }) {
  const { data, cats } = useMemo(() => {
    const sub = rows.filter((r) => String(r.ticker) === ticker)
    const byDate = new Map<string, Record<string, string | number>>()
    const catSet = new Set<string>()
    for (const r of sub) {
      const d = String(r.date ?? '').slice(0, 10)
      const cat = String(r.category ?? '')
      if (!d || !cat || r.holding_pct == null) continue
      catSet.add(cat)
      const row = byDate.get(d) ?? { date: d }
      row[cat] = Number(r.holding_pct)
      byDate.set(d, row)
    }
    return {
      data: [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date))),
      cats: [...catSet],
    }
  }, [rows, ticker])

  if (!data.length) return <p className="text-xs text-slate-500">No ownership series for {ticker}.</p>

  return (
    <div className="h-64 w-full rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
      <p className="mb-1 text-xs font-medium text-slate-300">{ticker} · ownership %</p>
      <ResponsiveContainer width="100%" height="90%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={24} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} width={40} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            formatter={(v) => [`${Number(v).toFixed(2)}%`, '']}
          />
          {cats.map((c) => (
            <Line
              key={c}
              type="monotone"
              dataKey={c}
              stroke={CAT_COLORS[c] ?? '#94a3b8'}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <ul className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-400">
        {cats.map((c) => (
          <li key={c} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: CAT_COLORS[c] ?? '#94a3b8' }} />
            {c}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Command Center — India FII-DII Holding (screener.in ownership + invest timing).
 */
export function IndiaFiiDiiHoldingsPanel() {
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [fromDate, setFromDate] = useState(isoDaysAgo(400))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [error, setError] = useState('')
  const [data, setData] = useState<Row | null>(null)
  const [selected, setSelected] = useState('')
  const [showHow, setShowHow] = useState(false)

  const scanMut = useMutation({
    mutationFn: () =>
      runIndiaFiiDiiHoldings({
        tickers: picker.tickers,
        from_date: fromDate,
        to_date: toDate,
      }),
    onSuccess: (res) => {
      setError('')
      setData(res as Row)
      const ok = ((res as Row).ok as Row[]) ?? []
      setSelected(String(ok[0]?.ticker ?? ''))
    },
    onError: (e) => {
      setError(apiErrorMessage(e))
      setData(null)
    },
  })

  const summary = useMemo(() => {
    const s = data?.summary
    if (Array.isArray(s)) return s as Row[]
    return []
  }, [data])

  const ok = ((data?.ok as Row[]) ?? [])
  const chartAll = ((data?.chart_all as Row[]) ?? [])
  const detail = ok.find((r) => String(r.ticker) === selected) ?? ok[0]
  const categories = (detail?.categories as Record<string, Row>) ?? {}

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="font-medium text-white">India FII-DII Holding</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Promoters / FII / DII / Public stake trend · revenue &amp; profit · P/E vs ROCE · invest timing (YES / WAIT / NO).
              India NSE only · data from screener.in.
            </p>
          </div>
          <button type="button" className="text-xs text-slate-400 hover:text-white" onClick={() => setShowHow((v) => !v)}>
            {showHow ? 'Hide guide' : 'How to read'}
          </button>
        </div>
        {showHow && (
          <div className="mb-4 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs leading-relaxed text-slate-400">
            <p className="mb-2 text-slate-300">Trade bias from ownership:</p>
            <ul className="list-disc space-y-1 pl-4">
              <li><span className="text-emerald-400">YES</span> — FII/DII accumulating + supportive fundamentals → long bias</li>
              <li><span className="text-rose-400">NO</span> — institutions reducing / rich valuation → avoid or short bias</li>
              <li><span className="text-amber-400">WAIT</span> — mixed ownership or valuation not aligned</li>
            </ul>
            <p className="mt-2">Daily cash-market FII/DII flows (net ₹ Cr) live under Market Pulse → News Scanner, not this tab.</p>
          </div>
        )}

        <AssetClassTickerPicker
          assetClass="india"
          onChange={setPicker}
          showDurations={false}
        />

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <FormField label="From date">
            <input
              type="date"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
            />
          </FormField>
          <FormField label="To date">
            <input
              type="date"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
            />
          </FormField>
          <div className="flex items-end">
            <Button
              className="w-full"
              disabled={scanMut.isPending || !picker.tickers.length || !fromDate || !toDate}
              onClick={() => scanMut.mutate()}
            >
              {scanMut.isPending ? 'Analyzing…' : 'Analyze FII-DII holdings'}
            </Button>
          </div>
        </div>

        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
        {scanMut.isPending && <div className="mt-4"><Loading message="Fetching screener.in shareholding…" /></div>}
      </Card>

      {data && !scanMut.isPending && (
        <Card>
          {data.error ? (
            <Alert type="error">{String(data.error)}</Alert>
          ) : (
            <div className="space-y-5">
              {data.snapshot_note && (
                <p className="text-xs text-slate-500">{String(data.snapshot_note)}</p>
              )}

              <div>
                <h4 className="mb-2 text-sm font-semibold text-white">Invest timing overview</h4>
                {!summary.length ? (
                  <p className="text-sm text-slate-500">No successful tickers.</p>
                ) : (
                  <DataTable minWidth={980} title="FII-DII Holdings">
                    <thead>
                      <tr>
                        <Th>Ticker</Th>
                        <Th>Timing</Th>
                        <Th>Ownership</Th>
                        <Th>FII Δ</Th>
                        <Th>DII Δ</Th>
                        <Th>Valuation</Th>
                        <Th>P/E</Th>
                        <Th>Revenue</Th>
                        <Th>Profit</Th>
                        <Th>Ownership Summary</Th>
                        <Th>Summary</Th>
                        <Th></Th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.map((r) => {
                        const t = String(r.Ticker ?? '')
                        return (
                          <tr
                            key={t}
                            className={`cursor-pointer border-t border-slate-800/80 align-top hover:bg-slate-800/40 ${selected === t ? 'bg-slate-800/50' : ''}`}
                            onClick={() => setSelected(t)}
                          >
                            <Td className="font-medium text-white">{t}</Td>
                            <Td>{timingBadge(r.Timing)}</Td>
                            <Td className={trendClass(r.Ownership)}>{String(r.Ownership ?? '—')}</Td>
                            <Td className={Number(r['FIIs Δ']) > 0 ? 'text-emerald-400' : Number(r['FIIs Δ']) < 0 ? 'text-rose-400' : ''}>
                              {fmt(r['FIIs Δ'])} pp
                            </Td>
                            <Td className={Number(r['DIIs Δ']) > 0 ? 'text-emerald-400' : Number(r['DIIs Δ']) < 0 ? 'text-rose-400' : ''}>
                              {fmt(r['DIIs Δ'])} pp
                            </Td>
                            <Td className="text-xs text-slate-300">{String(r.Valuation ?? '—')}</Td>
                            <Td>{fmt(r['P/E'], 1)}</Td>
                            <Td className={trendClass(r['Revenue trend'])}>{String(r['Revenue trend'] ?? '—')}</Td>
                            <Td className={trendClass(r['Profit trend'])}>{String(r['Profit trend'] ?? '—')}</Td>
                            <Td className="max-w-xs text-xs text-slate-400">{String(r['Ownership Summary'] ?? '—')}</Td>
                            <Td className="max-w-xs text-xs text-slate-400">{String(r.Summary ?? '—')}</Td>
                            <Td>
                              <AddToWatchlistButton
                                ticker={t}
                                displayName={t}
                                notes={`FII-DII · ${r.Timing} · FII Δ ${fmt(r['FIIs Δ'])} · DII Δ ${fmt(r['DIIs Δ'])}`}
                                marketType="india"
                                compact
                              />
                            </Td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </DataTable>
                )}
              </div>

              {ok.length > 0 && (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {ok.map((r) => (
                      <Chip
                        key={String(r.ticker)}
                        selected={selected === String(r.ticker)}
                        onClick={() => setSelected(String(r.ticker))}
                      >
                        {String(r.ticker)}
                      </Chip>
                    ))}
                  </div>

                  {detail && !detail.error && (
                    <>
                      <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-white">{String(detail.ticker)}</p>
                          {timingBadge((detail.timing as Row)?.verdict)}
                        </div>
                        <p className="mt-2 text-sm leading-relaxed text-slate-200">
                          {String(detail.ownership_summary ?? '—')}
                        </p>
                        <p className="mt-1 text-xs leading-relaxed text-slate-400">
                          {String((detail.timing as Row)?.summary ?? (detail.ownership as Row)?.summary ?? '—')}
                        </p>
                        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                          {(['Promoters', 'FIIs', 'DIIs', 'Public'] as const).map((cat) => {
                            const info = categories[cat] ?? {}
                            return (
                              <div key={cat} className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
                                <p className="text-[11px] uppercase tracking-wide text-slate-500">{cat}</p>
                                <p className="mt-1 text-lg font-semibold tabular-nums text-white">{fmt(info.last_pct)}%</p>
                                <p className={`text-xs ${trendClass(info.trend)}`}>
                                  {fmt(info.change_pp)} pp · {String(info.trend ?? '—')}
                                </p>
                              </div>
                            )
                          })}
                        </div>
                      </div>

                      <OwnershipChart rows={chartAll} ticker={String(detail.ticker)} />

                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-xl border border-slate-800/80 p-3">
                          <p className="text-xs font-medium text-slate-400">Valuation</p>
                          <p className="mt-1 text-sm text-white">{String((detail.valuation as Row)?.label ?? '—')}</p>
                          <p className="mt-1 text-xs text-slate-500">
                            P/E {fmt(detail.pe, 1)} · ROCE {fmt(detail.roce_pct, 1)}%
                          </p>
                        </div>
                        <div className="rounded-xl border border-slate-800/80 p-3">
                          <p className="text-xs font-medium text-slate-400">Revenue &amp; profit</p>
                          <p className="mt-1 text-sm text-slate-200">
                            Sales {(detail.revenue_profit as Row)?.sales ? String(((detail.revenue_profit as Row).sales as Row).trend) : '—'}
                            {' · '}
                            Profit {(detail.revenue_profit as Row)?.net_profit ? String(((detail.revenue_profit as Row).net_profit as Row).trend) : '—'}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            Deals flagged: {String((detail.deals as Row)?.n_flagged ?? 0)} · Actions: {String((detail.actions as Row)?.n_signal ?? 0)}
                          </p>
                        </div>
                      </div>

                      <AskAIPanel
                        context={String(detail.ai_context ?? '')}
                        systemPrompt={String(data.ai_system_prompt ?? '')}
                        section={`command-center/fii-dii/${String(detail.ticker)}`}
                      />
                    </>
                  )}
                  {detail?.error && <Alert type="error">{String(detail.error)}</Alert>}
                </div>
              )}

              {((data.errors as Row[]) ?? []).length > 0 && (
                <div>
                  <p className="mb-1 text-xs text-slate-500">Failed tickers</p>
                  <ul className="space-y-1 text-xs text-rose-300/90">
                    {((data.errors as Row[]) ?? []).map((e) => (
                      <li key={String(e.ticker)}>{String(e.ticker)} — {String(e.error)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
