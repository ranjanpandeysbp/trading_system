import { Badge } from '../ui/Badge'
import { DataTable, Td, SortableTh, useSort } from '../ui/Table'

type ScreenerResult = Record<string, unknown>

const ACTIONABLE_VERDICTS = new Set([
  'BUY',
  'STRONG BUY',
  'SELL',
  'WATCHLIST',
  'TOP PICK',
])

function isActionable(row: ScreenerResult): boolean {
  if (row.error) return false
  if (row.actionable || row.take_trade) return true
  const phase = String(row.phase ?? '')
  if (['ENTRY_READY', 'SNIPER_ENTRY', 'GOLDEN_BULLET_ENTRY'].includes(phase)) return true
  const verdict = String(row.verdict ?? '').toUpperCase()
  if (ACTIONABLE_VERDICTS.has(verdict)) return true
  return verdict.startsWith('TAKE') || verdict.startsWith('WATCH')
}

function statusBadge(row: ScreenerResult) {
  if (row.error) return <Badge action="SELL" />
  const verdict = String(row.verdict ?? '').toUpperCase()
  if (verdict.includes('SELL')) return <Badge action="SELL" />
  if (isActionable(row)) return <Badge action="BUY" />
  return <Badge action="HOLD" />
}

function summaryFor(row: ScreenerResult): string {
  if (row.error) return String(row.error)
  const keys = ['summary', 'verdict', 'signal', 'phase', 'bias', 'recommendation', 'action', 'status']
  for (const k of keys) {
    if (row[k] != null && row[k] !== '') return String(row[k])
  }
  return 'See details'
}

function MtfLegs({ row }: { row: ScreenerResult }) {
  const mtf = (row.mtf as Record<string, unknown> | undefined) ?? undefined
  const legs = (mtf?.legs as Array<Record<string, unknown>> | undefined)
    ?? (row.legs as Array<Record<string, unknown>> | undefined)
  if (!legs?.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {legs.map((leg, i) => {
        const tf = String(leg.tf ?? leg.chart_tf ?? leg.timeframe ?? `#${i}`)
        const verdict = String(leg.verdict ?? '—')
        const conf = leg.confidence != null ? `${Number(leg.confidence).toFixed(0)}%` : ''
        const bias = leg.sr_bias != null ? String(leg.sr_bias) : ''
        return (
          <span
            key={`${tf}-${i}`}
            className="rounded-md border border-slate-700/60 bg-slate-900/50 px-2 py-1 text-[11px] text-slate-300"
          >
            <span className="font-medium text-white">{tf}</span>
            {' · '}
            {verdict}
            {conf ? ` · ${conf}` : ''}
            {bias ? ` · ${bias}` : ''}
          </span>
        )
      })}
    </div>
  )
}

export function TaScreenerResultsPanel({ data }: { data: Record<string, unknown> }) {
  const results = (data.results as ScreenerResult[]) ?? []
  const actionable = (data.actionable as ScreenerResult[]) ?? []
  const label = String(data.label ?? data.screener_id ?? 'Screener')
  const isWssr = String(data.screener_id ?? '') === 'weak_strong_sr'
  const timeframes = data.timeframes as string[] | undefined

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
        {timeframes?.length ? (
          <span className="text-xs text-slate-500">TFs: {timeframes.join(', ')}</span>
        ) : data.timeframe != null && data.timeframe !== '' ? (
          <span className="text-xs text-slate-500">TF: {String(data.timeframe)}</span>
        ) : null}
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
                <Td className="font-medium text-white align-top">
                  {ticker}
                  {isWssr && <MtfLegs row={row} />}
                </Td>
                <Td className="max-w-md text-slate-300">
                  <div className="truncate">{summaryFor(row)}</div>
                  {isWssr && row.phase != null && (
                    <div className="mt-1 text-[11px] text-slate-500">
                      phase {String(row.phase)}
                      {row.confidence != null ? ` · conf ${Number(row.confidence).toFixed(0)}%` : ''}
                      {row.direction != null && row.direction !== '—' ? ` · ${String(row.direction)}` : ''}
                    </div>
                  )}
                </Td>
                <Td className="align-top">{statusBadge(row)}</Td>
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
