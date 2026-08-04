import { useMemo, useState } from 'react'
import { DataTable, SortableTh, Td } from '../ui/Table'
import { Card } from '../ui/Card'
import { Alert } from '../ui/Feedback'
import { Button } from '../ui/Button'

type Row = Record<string, unknown>
type SortKey = 'rank' | 'symbol' | 'underlying' | 'price' | 'sma20' | 'pct_from_dma'

function fmtInr(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function pctClass(v?: number | null) {
  if (v == null) return 'text-slate-400'
  return Number(v) < 0 ? 'text-emerald-400' : 'text-rose-400'
}

function compareAnalysis(a: Row, b: Row, key: SortKey): number {
  switch (key) {
    case 'rank':
      return Number(a.rank ?? 999) - Number(b.rank ?? 999)
    case 'symbol':
      return String(a.symbol).localeCompare(String(b.symbol))
    case 'underlying':
      return String(a.underlying ?? '').localeCompare(String(b.underlying ?? ''))
    case 'price':
      return Number(a.price ?? -1) - Number(b.price ?? -1)
    case 'sma20':
      return Number(a.sma20 ?? -1) - Number(b.sma20 ?? -1)
    case 'pct_from_dma':
      return Number(a.pct_from_dma ?? 999) - Number(b.pct_from_dma ?? 999)
  }
}

export function StfShopRankTable({ analyses }: { analyses: Row[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('rank')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir(key === 'pct_from_dma' || key === 'rank' ? 'asc' : 'desc')
    }
  }

  const rows = useMemo(
    () =>
      [...analyses].sort((a, b) => {
        const cmp = compareAnalysis(a, b, sortKey)
        return sortDir === 'asc' ? cmp : -cmp
      }),
    [analyses, sortKey, sortDir],
  )

  if (!rows.length) return <p className="text-sm text-slate-500">No ETF data.</p>

  return (
    <DataTable minWidth={720}>
      <thead>
        <tr>
          <SortableTh active={sortKey === 'rank'} direction={sortDir} onSort={() => handleSort('rank')}>Rank</SortableTh>
          <SortableTh active={sortKey === 'symbol'} direction={sortDir} onSort={() => handleSort('symbol')}>ETF</SortableTh>
          <SortableTh active={sortKey === 'underlying'} direction={sortDir} onSort={() => handleSort('underlying')}>Underlying</SortableTh>
          <SortableTh active={sortKey === 'price'} direction={sortDir} onSort={() => handleSort('price')}>CMP</SortableTh>
          <SortableTh active={sortKey === 'sma20'} direction={sortDir} onSort={() => handleSort('sma20')}>20 DMA</SortableTh>
          <SortableTh active={sortKey === 'pct_from_dma'} direction={sortDir} onSort={() => handleSort('pct_from_dma')}>% vs DMA</SortableTh>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={String(r.symbol)} className={r.error ? 'opacity-60' : ''}>
            <Td>{r.rank != null ? String(r.rank) : '—'}</Td>
            <Td className="font-medium">{String(r.symbol)}</Td>
            <Td className="text-xs text-slate-500">{String(r.underlying ?? '—')}</Td>
            <Td>{fmtInr(Number(r.price))}</Td>
            <Td>{fmtInr(Number(r.sma20))}</Td>
            <Td className={pctClass(Number(r.pct_from_dma))}>
              {r.pct_from_dma != null ? `${Number(r.pct_from_dma).toFixed(2)}%` : String(r.error ?? '—')}
            </Td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  )
}

export function StfShopRecommendationPanel({
  rec,
  onExecuteBuy,
  onExecuteSell,
  buyPending,
  sellPending,
}: {
  rec: Row
  onExecuteBuy?: () => void
  onExecuteSell?: () => void
  buyPending?: boolean
  sellPending?: boolean
}) {
  const buy = rec.buy_recommendation as Row | undefined
  const sell = rec.primary_sell as Row | undefined
  const buyActionable = buy && buy.action === 'BUY' && buy.blocked !== true

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="border-emerald-500/20 bg-emerald-500/5">
        <h4 className="mb-2 text-sm font-semibold text-emerald-400">Today&apos;s buy</h4>
        {buy ? (
          <div className="space-y-1 text-sm text-slate-300">
            <p className="text-lg font-bold text-white">{String(buy.action ?? '—')}</p>
            {buy.symbol != null && <p>Symbol: <strong>{String(buy.symbol)}</strong></p>}
            {buy.buy_type != null && <p>Type: {String(buy.buy_type)}</p>}
            {buy.price != null && <p>CMP: {fmtInr(Number(buy.price))}</p>}
            {buy.slot_amount != null && <p>Amount: {fmtInr(Number(buy.slot_amount))}</p>}
            {buy.sip_amount != null && <p>SIP amount: {fmtInr(Number(buy.sip_amount))}</p>}
            {buy.quantity != null && (
              <p>
                Quantity: <strong>{Number(buy.quantity).toLocaleString('en-IN')} unit{Number(buy.quantity) === 1 ? '' : 's'}</strong>
                {buy.actual_amount != null && Number(buy.quantity) > 0 && (
                  <span className="text-slate-400"> · actual outlay {fmtInr(Number(buy.actual_amount))}</span>
                )}
              </p>
            )}
            {buy.reason != null && <p className="text-slate-400">{String(buy.reason)}</p>}
            {buy.blocked === true && buy.block_reason != null && (
              <Alert type="error">{String(buy.block_reason)}</Alert>
            )}
            {buyActionable && onExecuteBuy && (
              <Button size="sm" className="mt-2" onClick={onExecuteBuy} disabled={buyPending}>
                {buyPending
                  ? 'Recording…'
                  : `Execute buy — ${Number(buy.quantity ?? 0)} unit${Number(buy.quantity) === 1 ? '' : 's'} (${fmtInr(Number(buy.actual_amount ?? buy.slot_amount ?? buy.sip_amount))})`}
              </Button>
            )}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No buy signal.</p>
        )}
      </Card>
      <Card className="border-rose-500/20 bg-rose-500/5">
        <h4 className="mb-2 text-sm font-semibold text-rose-400">FIFO sell candidate</h4>
        {sell ? (
          <div className="space-y-1 text-sm text-slate-300">
            <p className="text-lg font-bold text-white">{String(sell.symbol)}</p>
            <p>Profit: {Number(sell.profit_pct).toFixed(2)}% · {fmtInr(Number(sell.profit_inr))}</p>
            <p className="text-slate-400">Sell at CMP {fmtInr(Number(sell.current_price))}</p>
            {sell.note != null && <p className="text-slate-400">{String(sell.note)}</p>}
            {onExecuteSell && (
              <Button size="sm" variant="danger" className="mt-2" onClick={onExecuteSell} disabled={sellPending}>
                {sellPending ? 'Recording…' : 'Execute sell'}
              </Button>
            )}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No sell candidate today.</p>
        )}
      </Card>
    </div>
  )
}

export function StfShopCapitalMetrics({ rec }: { rec: Row }) {
  const items = [
    ['Effective capital', fmtInr(Number(rec.effective_capital))],
    ['Slot size', fmtInr(Number(rec.slot_size))],
    ['Deployed', fmtInr(Number(rec.deployed_capital))],
    ['Free', fmtInr(Number(rec.free_capital))],
    ['% deployed', rec.pct_deployed != null ? `${rec.pct_deployed}%` : '—'],
    ['Annualized', rec.annualized_return_pct != null ? `${rec.annualized_return_pct}%` : '—'],
  ]
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map(([label, val]) => (
        <div key={label} className="rounded-xl border border-slate-800/60 bg-slate-900/40 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
          <p className="text-sm font-semibold text-white">{val}</p>
        </div>
      ))}
    </div>
  )
}
