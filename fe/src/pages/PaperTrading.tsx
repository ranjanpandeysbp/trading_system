import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, RotateCcw, ShoppingCart } from 'lucide-react'
import { getAccount, placeOrder, resetAccount } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { StatCard } from '../components/ui/StatCard'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, SortableTh, Td, useSort } from '../components/ui/Table'

export default function PaperTrading() {
  const qc = useQueryClient()
  const [ticker, setTicker] = useState('RELIANCE')
  const [quantity, setQuantity] = useState(10)
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [msg, setMsg] = useState('')

  const { data: account, isLoading, isFetching, refetch } = useQuery({ queryKey: ['account'], queryFn: getAccount })

  const orderMutation = useMutation({
    mutationFn: placeOrder,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['account'] }); setMsg('Order placed successfully'); },
    onError: (e: Error) => setMsg(e.message),
  })

  const resetMutation = useMutation({
    mutationFn: resetAccount,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['account'] }); setMsg('Account reset'); },
  })

  const {
    sorted: sortedPositions,
    sortKey: positionsSortKey,
    sortDir: positionsSortDir,
    handleSort: handlePositionsSort,
  } = useSort(account?.positions ?? [], {
    ticker: (r) => r.ticker,
    quantity: (r) => r.quantity,
    avg_price: (r) => r.avg_price,
    ltp: (r) => r.ltp,
    pnl_pct: (r) => r.pnl_pct,
    sl_pct: (r) => r.sl_pct,
  })

  const {
    sorted: sortedOrders,
    sortKey: ordersSortKey,
    sortDir: ordersSortDir,
    handleSort: handleOrdersSort,
  } = useSort(account?.recent_orders ?? [], {
    created_at: (r) => r.created_at,
    ticker: (r) => r.ticker,
    side: (r) => r.side,
    quantity: (r) => r.quantity,
    price: (r) => r.price,
    strategy: (r) => r.strategy,
  })

  if (isLoading) return <Loading message="Loading account..." />

  const isSuccess = msg.includes('reset') || msg.includes('placed')

  return (
    <div>
      <PageHeader
        title="Paper Trading"
        description="Demo portfolio with virtual capital — execute trades manually or from scanner signals"
      />

      {account && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Portfolio" value={`₹${account.portfolio_value.toLocaleString('en-IN')}`} />
          <StatCard label="Cash" value={`₹${account.cash_balance.toLocaleString('en-IN')}`} />
          <StatCard
            label="P&L"
            value={`₹${account.total_pnl.toLocaleString('en-IN')} (${account.total_pnl_pct}%)`}
            trend={account.total_pnl >= 0 ? 'up' : 'down'}
          />
          <StatCard label="Positions" value={account.positions.length} />
        </div>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <Card className="min-w-0">
          <div className="mb-5 flex items-center gap-2">
            <ShoppingCart className="text-emerald-400" size={20} />
            <h3 className="font-semibold text-white">Place Order</h3>
          </div>

          <FormField label="Ticker">
            <Input value={ticker} onChange={(e) => setTicker(e.target.value)} />
          </FormField>
          <FormField label="Side">
            <Select value={side} onChange={(e) => setSide(e.target.value as 'buy' | 'sell')}>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </Select>
          </FormField>
          <FormField label="Quantity">
            <Input type="number" value={quantity} onChange={(e) => setQuantity(parseInt(e.target.value) || 1)} min={1} />
          </FormField>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <Button className="w-full sm:w-auto" onClick={() => orderMutation.mutate({ ticker, side, quantity })} disabled={orderMutation.isPending}>
              Place Market Order
            </Button>
            <Button className="w-full sm:w-auto" variant="danger" onClick={() => resetMutation.mutate()} disabled={resetMutation.isPending}>
              <RotateCcw size={16} />
              Reset Account
            </Button>
          </div>
          {msg && <Alert type={isSuccess ? 'success' : 'error'}>{msg}</Alert>}
        </Card>

        <Card className="min-w-0">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-white">Open Positions</h3>
            <Button variant="secondary" size="sm" onClick={() => refetch()} disabled={isFetching}>
              <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
              {isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
          {account?.positions.length ? (
            <DataTable>
              <thead>
                <tr>
                  <SortableTh active={positionsSortKey === 'ticker'} direction={positionsSortDir} onSort={() => handlePositionsSort('ticker')}>Ticker</SortableTh>
                  <SortableTh active={positionsSortKey === 'quantity'} direction={positionsSortDir} onSort={() => handlePositionsSort('quantity')}>Qty</SortableTh>
                  <SortableTh active={positionsSortKey === 'avg_price'} direction={positionsSortDir} onSort={() => handlePositionsSort('avg_price')}>Avg</SortableTh>
                  <SortableTh active={positionsSortKey === 'ltp'} direction={positionsSortDir} onSort={() => handlePositionsSort('ltp')}>LTP</SortableTh>
                  <SortableTh active={positionsSortKey === 'pnl_pct'} direction={positionsSortDir} onSort={() => handlePositionsSort('pnl_pct')}>P&L</SortableTh>
                  <SortableTh active={positionsSortKey === 'sl_pct'} direction={positionsSortDir} onSort={() => handlePositionsSort('sl_pct')}>SL/TP</SortableTh>
                </tr>
              </thead>
              <tbody>
                {sortedPositions.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/20">
                    <Td className="font-medium text-white">{p.ticker}</Td>
                    <Td>{p.quantity}</Td>
                    <Td>₹{p.avg_price}</Td>
                    <Td>₹{p.ltp}</Td>
                    <Td className={p.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{p.pnl_pct}%</Td>
                    <Td className="text-slate-500">{p.sl_pct ? `${p.sl_pct}/${p.tp_pct}%` : '—'}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">No open positions</p>
          )}
        </Card>
      </div>

      {account && account.recent_orders.length > 0 && (
        <Card className="mt-6">
          <h3 className="mb-4 font-semibold text-white">Recent Orders</h3>
          <DataTable>
            <thead>
              <tr>
                <SortableTh active={ordersSortKey === 'created_at'} direction={ordersSortDir} onSort={() => handleOrdersSort('created_at')}>Time</SortableTh>
                <SortableTh active={ordersSortKey === 'ticker'} direction={ordersSortDir} onSort={() => handleOrdersSort('ticker')}>Ticker</SortableTh>
                <SortableTh active={ordersSortKey === 'side'} direction={ordersSortDir} onSort={() => handleOrdersSort('side')}>Side</SortableTh>
                <SortableTh active={ordersSortKey === 'quantity'} direction={ordersSortDir} onSort={() => handleOrdersSort('quantity')}>Qty</SortableTh>
                <SortableTh active={ordersSortKey === 'price'} direction={ordersSortDir} onSort={() => handleOrdersSort('price')}>Price</SortableTh>
                <SortableTh active={ordersSortKey === 'strategy'} direction={ordersSortDir} onSort={() => handleOrdersSort('strategy')}>Strategy</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedOrders.map((o) => (
                <tr key={o.id} className="hover:bg-slate-800/20">
                  <Td className="text-slate-400">{new Date(o.created_at).toLocaleString()}</Td>
                  <Td className="font-medium text-white">{o.ticker}</Td>
                  <Td><Badge action={o.side === 'buy' ? 'BUY' : 'SELL'} /></Td>
                  <Td>{o.quantity}</Td>
                  <Td className="tabular-nums">₹{o.price}</Td>
                  <Td className="text-slate-500">{o.strategy ?? '—'}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Card>
      )}
    </div>
  )
}
