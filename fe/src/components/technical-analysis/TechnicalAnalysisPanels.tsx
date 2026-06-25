import { useState } from 'react'
import { DataTable, Th, Td } from '../ui/Table'
import { Alert } from '../ui/Feedback'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'

type Row = Record<string, unknown>

function fmtPct(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const v = Number(n)
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}`
}

function scoreClass(score: number) {
  if (score >= 35) return 'text-emerald-400'
  if (score <= -35) return 'text-rose-400'
  return 'text-amber-400'
}

export function SentimentScreenerPanel({ data }: { data: Row }) {
  const rows = (data.rows as Row[]) ?? []
  const errors = (data.errors as string[]) ?? []
  const [expanded, setExpanded] = useState<string | null>(null)

  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!rows.length) return <p className="text-sm text-slate-500">No results — add tickers and run scan.</p>

  return (
    <div className="space-y-4">
      {errors.length > 0 && (
        <Alert type="error">{errors.length} scan error(s) — partial results shown.</Alert>
      )}
      <DataTable>
        <thead>
          <tr>
            <Th>Ticker</Th>
            <Th>TF</Th>
            <Th>Score</Th>
            <Th>Rating</Th>
            <Th>Signal</Th>
            <Th>Conf</Th>
            <Th>RSI</Th>
            <Th>SL/TP %</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const key = `${r.ticker}-${r.timeframe}`
            const score = Number(r.score ?? 0)
            return (
              <tr key={key} className="cursor-pointer hover:bg-slate-800/30" onClick={() => setExpanded(expanded === key ? null : key)}>
                <Td className="font-medium">{String(r.ticker)}</Td>
                <Td>{String(r.timeframe)}</Td>
                <Td className={scoreClass(score)}>{fmtPct(score)}</Td>
                <Td className="max-w-[12rem] truncate text-xs">{String(r.rating ?? '—')}</Td>
                <Td>{String(r.trade_signal ?? '—')}</Td>
                <Td>{r.trade_confidence != null ? `${r.trade_confidence}%` : '—'}</Td>
                <Td>{r.rsi != null ? Number(r.rsi).toFixed(1) : '—'}</Td>
                <Td>{r.sl_pct != null ? `${r.sl_pct}/${r.tp_pct}` : '—'}</Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>
      {expanded && (
        <Card className="mt-2">
          {(() => {
            const row = rows.find((r) => `${r.ticker}-${r.timeframe}` === expanded)
            const insights = (row?.insights as string[]) ?? []
            return (
              <div>
                <p className="mb-2 text-sm font-medium text-white">{String(row?.ticker)} · {String(row?.timeframe)}</p>
                <ul className="max-h-64 space-y-1 overflow-y-auto text-xs text-slate-300">
                  {insights.map((i) => <li key={i}>{i}</li>)}
                </ul>
              </div>
            )
          })()}
        </Card>
      )}
    </div>
  )
}

export function MtfScannerPanel({ data }: { data: Row }) {
  const results = (data.results as Record<string, Row>) ?? {}
  const tickers = Object.keys(results)
  const [selected, setSelected] = useState(tickers[0] ?? '')

  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!tickers.length) return <p className="text-sm text-slate-500">No MTF results.</p>

  const item = results[selected] as Row | undefined
  const confluence = item?.confluence as Row | undefined
  const setups = (item?.trade_setups as Row[]) ?? []
  const tfResults = (item?.timeframes as Record<string, Row>) ?? {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {tickers.map((t) => (
          <Chip key={t} selected={selected === t} onClick={() => setSelected(t)}>{t}</Chip>
        ))}
      </div>
      {confluence && (
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
          <p className="text-lg font-semibold text-white">
            {String(confluence.verdict ?? confluence.bias ?? 'Confluence')}
          </p>
          <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-300">
            <span>Avg score: <strong className={scoreClass(Number(confluence.avg_score))}>{fmtPct(Number(confluence.avg_score))}</strong></span>
            <span>Confidence: <strong>{Number(confluence.avg_confidence ?? 0).toFixed(0)}%</strong></span>
            <span>Bull/Bear/Neutral: <strong>{String(confluence.bull_count)}/{String(confluence.bear_count)}/{String(confluence.neutral_count)}</strong></span>
          </div>
          {(confluence.suggested_play as string[] | undefined)?.length ? (
            <ul className="mt-3 space-y-1 text-sm text-slate-400">
              {(confluence.suggested_play as string[]).map((p) => <li key={p}>• {p}</li>)}
            </ul>
          ) : null}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Per-timeframe components</h4>
          <DataTable>
            <thead><tr><Th>TF</Th><Th>Score</Th><Th>Bias</Th><Th>Conf</Th></tr></thead>
            <tbody>
              {Object.entries(tfResults).map(([tf, tfData]) => (
                <tr key={tf}>
                  <Td>{tf}</Td>
                  <Td className={scoreClass(Number(tfData.score))}>{fmtPct(Number(tfData.score))}</Td>
                  <Td>{String(tfData.bias ?? '—')}</Td>
                  <Td>{Number(tfData.confidence ?? 0).toFixed(0)}%</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Trade setups</h4>
          {setups.length === 0 ? (
            <p className="text-sm text-slate-500">No setups generated.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {setups.slice(0, 6).map((s, i) => (
                <li key={i} className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-3">
                  <p className="font-medium text-white">{String(s.style ?? s.type ?? 'Setup')} · {String(s.direction ?? '—')}</p>
                  <p className="text-xs text-slate-400">{String(s.status ?? '')} · {String(s.timeframe ?? '')}</p>
                  {s.entry != null && <p className="mt-1 text-slate-300">Entry: ₹{Number(s.entry).toFixed(2)}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

export function TickerInvestigationPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)

  if (data.error && !results.length) return <Alert type="error">{String(data.error)}</Alert>
  if (!results.length) return <p className="text-sm text-slate-500">No investigation results.</p>

  const r = results[idx] ?? results[0]
  const news = (r.news as Row[]) ?? []
  const priceWindows = (r.price_windows as Row[]) ?? []
  const sr = r.sr as Row | undefined
  const strategies = (r.strategies as Row[]) ?? []
  const tradeSetup = r.trade_setup as Row | undefined

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((item, i) => (
          <Chip key={String(item.ticker)} selected={idx === i} onClick={() => setIdx(i)}>
            {String(item.ticker)}
          </Chip>
        ))}
      </div>

      <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
        <p className="text-lg font-semibold text-white">{String(r.display_name ?? r.ticker)}</p>
        <p className="text-sm text-slate-400">
          Price: {r.current_price != null ? `₹${Number(r.current_price).toFixed(2)}` : '—'}
          {r.mtf_label ? ` · ${String(r.mtf_label)}` : ''}
        </p>
        {r.error != null ? <Alert type="error">{String(r.error)}</Alert> : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">News ({news.length})</h4>
          <ul className="max-h-48 space-y-2 overflow-y-auto text-sm">
            {news.slice(0, 8).map((a, i) => (
              <li key={i} className="text-slate-300">
                {a.link ? (
                  <a href={String(a.link)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                    {String(a.title ?? 'Article')}
                  </a>
                ) : String(a.title ?? 'Article')}
                {a.source != null ? <span className="ml-1 text-xs text-slate-500">({String(a.source)})</span> : null}
              </li>
            ))}
            {!news.length && <li className="text-slate-500">No recent headlines.</li>}
          </ul>
        </div>
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Price windows</h4>
          <DataTable>
            <thead><tr><Th>Window</Th><Th>Change</Th><Th>RSI</Th></tr></thead>
            <tbody>
              {priceWindows.map((w) => (
                <tr key={String(w.window)}>
                  <Td>{String(w.window)} ({String(w.timeframe)})</Td>
                  <Td className={Number(w.change_pct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    {w.change_pct != null ? `${Number(w.change_pct) > 0 ? '+' : ''}${Number(w.change_pct).toFixed(2)}%` : '—'}
                  </Td>
                  <Td>{w.rsi != null ? Number(w.rsi).toFixed(1) : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      </div>

      {sr && Object.keys(sr).length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Support / Resistance</h4>
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(sr).map(([tf, levels]) => (
              <div key={tf} className="rounded-lg border border-slate-800/60 p-3">
                <p className="font-medium text-white">{tf}</p>
                <p className="text-slate-400">{(levels as Row).summary ? String((levels as Row).summary) : JSON.stringify(levels).slice(0, 120)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {tradeSetup && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <h4 className="text-sm font-medium text-emerald-400">Primary trade setup</h4>
          <p className="mt-1 text-white">{String(tradeSetup.name ?? tradeSetup.strategy ?? 'Setup')}</p>
          <p className="text-sm text-slate-300">{String(tradeSetup.rationale ?? tradeSetup.summary ?? '')}</p>
        </div>
      )}

      {strategies.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium text-slate-400">Strategies ({strategies.length})</h4>
          <ul className="space-y-2 text-sm">
            {strategies.slice(0, 8).map((s, i) => (
              <li key={i} className="rounded-lg border border-slate-800/60 p-3 text-slate-300">
                <span className="font-medium text-white">{String(s.name ?? s.strategy ?? `Strategy ${i + 1}`)}</span>
                {s.status != null ? <span className="ml-2 text-xs text-slate-500">{String(s.status)}</span> : null}
                {s.note != null ? <p className="mt-1 text-xs">{String(s.note)}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
