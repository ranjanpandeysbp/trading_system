import { useState } from 'react'
import { DataTable, Th, Td } from '../ui/Table'
import { Alert } from '../ui/Feedback'
import { Card } from '../ui/Card'

type Row = Record<string, unknown>

function verdictClass(verdict?: string) {
  const v = (verdict ?? '').toUpperCase()
  if (v.includes('TAKE') || v.includes('BUY') || v.includes('LONG')) return 'text-emerald-400'
  if (v.includes('SELL') || v.includes('SHORT')) return 'text-rose-400'
  if (v.includes('WATCH')) return 'text-amber-400'
  return 'text-slate-400'
}

export function TradingHubResultsPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const entries = (data.entries as Row[]) ?? []
  const [selected, setSelected] = useState<string | null>(null)

  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!results.length) return <p className="text-sm text-slate-500">No scan results.</p>

  const selectedRow = results.find((r) => String(r.ticker) === selected)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-sm text-slate-400">
        {data.entry_count != null && (
          <span>Actionable: <strong className="text-white">{String(data.entry_count)}</strong></span>
        )}
        {data.strategy != null && <span>Strategy: <strong className="text-white">{String(data.strategy)}</strong></span>}
        {entries.length > 0 && <span className="text-emerald-400">{entries.length} live setup(s)</span>}
      </div>

      <DataTable>
        <thead>
          <tr>
            <Th>Ticker</Th>
            <Th>Verdict</Th>
            <Th>Conf %</Th>
            <Th>SL %</Th>
            <Th>TP %</Th>
            <Th>Hold</Th>
            <Th>Last</Th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => {
            const live = (r.live as Row) ?? {}
            const ticker = String(r.ticker ?? '—')
            const err = r.error ? String(r.error) : null
            return (
              <tr
                key={ticker}
                className={`cursor-pointer hover:bg-slate-800/30 ${selected === ticker ? 'bg-slate-800/40' : ''}`}
                onClick={() => setSelected(ticker)}
              >
                <Td className="font-medium">{ticker}</Td>
                <Td className={err ? 'text-rose-400' : verdictClass(String(live.verdict))}>
                  {err ?? String(live.verdict ?? '—')}
                </Td>
                <Td>{live.confidence_pct != null ? `${live.confidence_pct}%` : '—'}</Td>
                <Td>{live.sl_pct != null ? `-${live.sl_pct}` : '—'}</Td>
                <Td>{live.tp_pct != null ? `+${live.tp_pct}` : '—'}</Td>
                <Td className="max-w-[10rem] truncate text-xs">{String(live.hold_duration ?? '—')}</Td>
                <Td>{r.last_close != null ? `₹${Number(r.last_close).toFixed(2)}` : '—'}</Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>

      {selectedRow && (
        <Card>
          <p className="mb-2 font-semibold text-white">{String(selectedRow.ticker)}</p>
          {selectedRow.error ? (
            <Alert type="error">{String(selectedRow.error)}</Alert>
          ) : (
            <div className="space-y-2 text-sm text-slate-300">
              {((selectedRow.live as Row)?.reasons as string[] | undefined)?.map((reason) => (
                <p key={reason}>· {reason}</p>
              ))}
              {((selectedRow.live as Row)?.phase != null) && (
                <p>Phase: <strong>{String((selectedRow.live as Row).phase)}</strong></p>
              )}
              {(selectedRow.backtest as Row | undefined)?.pnl_pct != null && (
                <p className="text-slate-400">
                  Backtest PnL: {Number((selectedRow.backtest as Row).pnl_pct).toFixed(2)}%
                  {' · '}Trades: {String((selectedRow.backtest as Row).trade_count ?? '—')}
                </p>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
