import { useMemo, useState } from 'react'
import { DataTable, SortableTh, Td } from '../ui/Table'
import { Alert } from '../ui/Feedback'
import { Card } from '../ui/Card'

type Row = Record<string, unknown>

type SortKey = 'ticker' | 'verdict' | 'confidence_pct' | 'sl_pct' | 'tp_pct' | 'hold_duration' | 'last_close'

const VERDICT_ORDER: Record<string, number> = {
  'TAKE LONG': 0,
  'TAKE SHORT': 1,
  'WATCH LONG': 2,
  'WATCH SHORT': 3,
  WAIT: 4,
}

function verdictClass(verdict?: string) {
  const v = (verdict ?? '').toUpperCase()
  if (v.includes('TAKE') || v.includes('BUY') || v.includes('LONG')) return 'text-emerald-400'
  if (v.includes('SELL') || v.includes('SHORT')) return 'text-rose-400'
  if (v.includes('WATCH')) return 'text-amber-400'
  return 'text-slate-400'
}

function rowTicker(r: Row) {
  return String(r.ticker ?? '')
}

function rowLive(r: Row) {
  return (r.live as Row) ?? {}
}

function compareRows(a: Row, b: Row, key: SortKey): number {
  const liveA = rowLive(a)
  const liveB = rowLive(b)

  switch (key) {
    case 'ticker':
      return rowTicker(a).localeCompare(rowTicker(b))
    case 'verdict': {
      const va = String(a.error ?? liveA.verdict ?? '').toUpperCase()
      const vb = String(b.error ?? liveB.verdict ?? '').toUpperCase()
      const oa = VERDICT_ORDER[va] ?? (va.includes('ERROR') ? 99 : 50)
      const ob = VERDICT_ORDER[vb] ?? (vb.includes('ERROR') ? 99 : 50)
      if (oa !== ob) return oa - ob
      return va.localeCompare(vb)
    }
    case 'confidence_pct':
      return Number(liveA.confidence_pct ?? -1) - Number(liveB.confidence_pct ?? -1)
    case 'sl_pct':
      return Number(liveA.sl_pct ?? -1) - Number(liveB.sl_pct ?? -1)
    case 'tp_pct':
      return Number(liveA.tp_pct ?? -1) - Number(liveB.tp_pct ?? -1)
    case 'hold_duration':
      return String(liveA.hold_duration ?? '').localeCompare(String(liveB.hold_duration ?? ''))
    case 'last_close':
      return Number(a.last_close ?? -1) - Number(b.last_close ?? -1)
  }
}

export function TradingHubResultsPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const entries = (data.entries as Row[]) ?? []
  const [selected, setSelected] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('confidence_pct')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(
        key === 'confidence_pct' || key === 'sl_pct' || key === 'tp_pct' || key === 'last_close' ? 'desc' : 'asc',
      )
    }
  }

  const sortedResults = useMemo(
    () =>
      [...results].sort((a, b) => {
        const cmp = compareRows(a, b, sortKey)
        return sortDir === 'asc' ? cmp : -cmp
      }),
    [results, sortKey, sortDir],
  )

  if (data.error) return <Alert type="error">{String(data.error)}</Alert>
  if (!results.length) return <p className="text-sm text-slate-500">No scan results.</p>

  const selectedRow = results.find((r) => rowTicker(r) === selected)

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
            <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>
              Ticker
            </SortableTh>
            <SortableTh active={sortKey === 'verdict'} direction={sortDir} onSort={() => handleSort('verdict')}>
              Verdict
            </SortableTh>
            <SortableTh active={sortKey === 'confidence_pct'} direction={sortDir} onSort={() => handleSort('confidence_pct')}>
              Conf %
            </SortableTh>
            <SortableTh active={sortKey === 'sl_pct'} direction={sortDir} onSort={() => handleSort('sl_pct')}>
              SL %
            </SortableTh>
            <SortableTh active={sortKey === 'tp_pct'} direction={sortDir} onSort={() => handleSort('tp_pct')}>
              TP %
            </SortableTh>
            <SortableTh active={sortKey === 'hold_duration'} direction={sortDir} onSort={() => handleSort('hold_duration')}>
              Hold
            </SortableTh>
            <SortableTh active={sortKey === 'last_close'} direction={sortDir} onSort={() => handleSort('last_close')}>
              Last
            </SortableTh>
          </tr>
        </thead>
        <tbody>
          {sortedResults.map((r) => {
            const live = rowLive(r)
            const ticker = rowTicker(r) || '—'
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
          <p className="mb-2 font-semibold text-white">{rowTicker(selectedRow)}</p>
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
