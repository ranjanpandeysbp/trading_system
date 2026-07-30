import { useMemo, useState } from 'react'
import { DataTable, SortableTh, Td, Th } from '../ui/Table'
import { Alert } from '../ui/Feedback'
import { Card } from '../ui/Card'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import { type SRChartBar, type SRTrendline } from './SupportResistanceChart'
import { SupportResistanceChartPanel } from './SupportResistanceChartPanel'

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

// Walk-forward calibration notes (15 India stocks, ATR-scaled target/stop) for
// the Trading Hub sections that have actually been checked against history so
// far — most of the other 28 sections have never been backtested at all, so
// there's nothing calibrated to report for them yet.
const CALIBRATION_NOTES: Record<string, string> = {
  swing_trading_st:
    "Calibration check: the Mean-Reversion mode never fired once across 15 stocks over ~3 years — each entry " +
    "condition (RSI<30, 2x volume, reversal candle) occurs individually, but the three together essentially " +
    "never do on liquid large-caps. The Continuation-Breakout mode fired 334 times at a pooled 46.9% win rate " +
    "(1:1 ATR-scaled target/stop) — no confidence bucket above the dominant 65-75% one had enough samples to " +
    "trust. Treat both modes' confidence scores as unvalidated until recalibrated.",
  swing_trading_st_simple_steal:
    "Calibration check (walk-forward, 15 India stocks, 145 signals, ATR-scaled target/stop): pooled win rate " +
    "43.6% — below breakeven at this test's 1:1 ratio. Treat the confidence score as unvalidated, not a " +
    "probability, until recalibrated.",
}

export function TradingHubResultsPanel({ data, sectionId, assetClass }: { data: Row; sectionId?: string; assetClass?: string }) {
  const results = (data.results as Row[]) ?? []
  const entries = (data.entries as Row[]) ?? []
  const [selected, setSelected] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('confidence_pct')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const calibrationNote = sectionId ? CALIBRATION_NOTES[sectionId] : undefined

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
      {calibrationNote && <p className="text-xs text-amber-500/80">{calibrationNote}</p>}
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
            <Th>Watch</Th>
          </tr>
        </thead>
        <tbody>
          {sortedResults.map((r) => {
            const live = rowLive(r)
            const ticker = rowTicker(r) || '—'
            const err = r.error ? String(r.error) : null
            // sl_pct/tp_pct are 0 (not null) when there's no live signal — entry
            // == stop == target in that placeholder state, so treat an exact
            // zero as "no real level" rather than rendering a meaningless -0/+0.
            const actionable = live.sl_pct != null && Number(live.sl_pct) !== 0
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
                <Td>{actionable ? `-${live.sl_pct}` : '—'}</Td>
                <Td>{actionable ? `+${live.tp_pct}` : '—'}</Td>
                <Td className="max-w-[10rem] truncate text-xs">{actionable ? String(live.hold_duration ?? '—') : '—'}</Td>
                <Td>{r.last_close != null ? `₹${Number(r.last_close).toFixed(2)}` : '—'}</Td>
                <Td>
                  <span onClick={(e) => e.stopPropagation()}>
                    <AddToWatchlistButton ticker={ticker} compact />
                  </span>
                </Td>
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
              {sectionId === 'support_resistance' && Boolean((selectedRow.live as Row)?.chart_data) && (
                <SupportResistanceChartPanel
                  ticker={rowTicker(selectedRow)}
                  assetClass={assetClass ?? 'india'}
                  timeframe={String((selectedRow.live as Row)?.htf ?? '1d')}
                  lastClose={selectedRow.last_close as number | undefined}
                  fallback={{
                    chartData: (selectedRow.live as Row).chart_data as unknown as SRChartBar[],
                    supportZone: ((selectedRow.live as Row).support_zone as [number, number] | null) ?? null,
                    resistanceZone: ((selectedRow.live as Row).resistance_zone as [number, number] | null) ?? null,
                    trendlines: ((selectedRow.live as Row).trendlines as unknown as SRTrendline[]) ?? [],
                  }}
                />
              )}
              {((selectedRow.live as Row)?.reasons as string[] | undefined)?.map((reason) => (
                <p key={reason}>· {reason}</p>
              ))}
              {((selectedRow.live as Row)?.phase != null) && (
                <p>Phase: <strong>{String((selectedRow.live as Row).phase)}</strong></p>
              )}
              {((selectedRow.live as Row)?.position_size != null) && (() => {
                const ps = (selectedRow.live as Row).position_size as Row
                return (
                  <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Suggested position — sized off your paper account</p>
                    <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                      <div><p className="text-xs text-slate-500">Quantity</p><p className="font-medium text-white">{String(ps.quantity)}</p></div>
                      <div><p className="text-xs text-slate-500">Notional</p><p className="font-medium text-white">₹{Number(ps.notional).toLocaleString('en-IN')}</p></div>
                      <div><p className="text-xs text-slate-500">Risk if stopped</p><p className="font-medium text-white">₹{Number(ps.risk_amount).toLocaleString('en-IN')} ({Number(ps.risk_pct_of_equity).toFixed(2)}%)</p></div>
                      <div><p className="text-xs text-slate-500">Portfolio risk already open</p><p className="font-medium text-white">{Number(ps.portfolio_open_risk_pct).toFixed(2)}%</p></div>
                    </div>
                    {Boolean(ps.already_holding) && (
                      <p className="mt-2 text-xs text-amber-400">You already hold a position in this ticker — check total exposure before adding more.</p>
                    )}
                    {Boolean(ps.portfolio_at_risk_cap) && (
                      <p className="mt-2 text-xs text-rose-400">Total open portfolio risk is already at/above the 6% cap — consider skipping new entries until existing risk comes down.</p>
                    )}
                    {Boolean(ps.capped_by_cash) && (
                      <p className="mt-2 text-xs text-slate-500">Size capped by available cash, not the risk formula.</p>
                    )}
                  </div>
                )
              })()}
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
