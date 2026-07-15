import { Badge } from '../ui/Badge'
import { DataTable, Td, SortableTh, useSort } from '../ui/Table'

type ScreenerResult = Record<string, unknown>

function statusBadge(row: ScreenerResult) {
  if (row.error) return <Badge action="SELL" />
  if (isActionable(row)) return <Badge action="BUY" />
  return <Badge action="HOLD" />
}

function isActionable(row: ScreenerResult): boolean {
  if (row.error) return false
  if (row.actionable || row.take_trade) return true
  const phase = String(row.phase ?? '')
  if (['ENTRY_READY', 'SNIPER_ENTRY', 'GOLDEN_BULLET_ENTRY'].includes(phase)) return true
  const verdict = String(row.verdict ?? '').toUpperCase()
  return verdict.startsWith('TAKE')
}

function summaryFor(row: ScreenerResult): string {
  if (row.error) return String(row.error)
  const keys = ['verdict', 'signal', 'phase', 'bias', 'recommendation', 'action', 'status', 'summary']
  for (const k of keys) {
    if (row[k] != null && row[k] !== '') return String(row[k])
  }
  return 'See details'
}

export function TaScreenerResultsPanel({ data }: { data: Record<string, unknown> }) {
  const results = (data.results as ScreenerResult[]) ?? []
  const actionable = (data.actionable as ScreenerResult[]) ?? []
  const label = String(data.label ?? data.screener_id ?? 'Screener')

  const { sorted, sortKey, sortDir, handleSort } = useSort(results, {
    ticker: (row) => String(row.ticker ?? ''),
    summary: (row) => summaryFor(row),
    status: (row) => (row.error ? 'ERROR' : isActionable(row) ? 'BUY' : 'HOLD'),
  })

  if (!results.length) {
    return <p className="text-sm text-slate-500">No results returned.</p>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold text-white">{label}</h3>
        <Badge action={actionable.length ? 'BUY' : 'HOLD'} />
        <span className="text-sm text-slate-400">
          {actionable.length} actionable / {results.length} scanned
        </span>
        {data.timeframe != null && data.timeframe !== '' && (
          <span className="text-xs text-slate-500">TF: {String(data.timeframe)}</span>
        )}
      </div>

      <DataTable>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
            <SortableTh active={sortKey === 'summary'} direction={sortDir} onSort={() => handleSort('summary')}>Summary</SortableTh>
            <SortableTh active={sortKey === 'status'} direction={sortDir} onSort={() => handleSort('status')}>Status</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const ticker = String(row.ticker ?? `#${i + 1}`)
            return (
              <tr key={`${ticker}-${i}`}>
                <Td className="font-medium text-white">{ticker}</Td>
                <Td className="max-w-md truncate text-slate-300">{summaryFor(row)}</Td>
                <Td>{statusBadge(row)}</Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>

      {actionable.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-emerald-400/80">
            Actionable details
          </p>
          <div className="space-y-3">
            {actionable.map((row, i) => (
              <pre
                key={i}
                className="max-h-64 overflow-auto rounded-xl border border-emerald-500/20 bg-slate-900/60 p-3 text-xs text-slate-300"
              >
                {JSON.stringify(row, null, 2)}
              </pre>
            ))}
          </div>
        </div>
      )}

      <details className="rounded-xl border border-slate-800/60 bg-slate-900/40 p-3">
        <summary className="cursor-pointer text-sm text-slate-400">Full raw response</summary>
        <pre className="mt-3 max-h-96 overflow-auto text-xs text-slate-500">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  )
}
