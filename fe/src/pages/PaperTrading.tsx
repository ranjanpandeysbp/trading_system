import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, ShoppingCart } from 'lucide-react'
import { getAccount, placeOrder, resetAccount } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { StatCard } from '../components/ui/StatCard'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, Th, Td } from '../components/ui/Table'

export default function PaperTrading() {
  const qc = useQueryClient()
  const [ticker, setTicker] = useState('RELIANCE')
  const [quantity, setQuantity] = useState(10)
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [msg, setMsg] = useState('')

  const { data: account, isLoading } = useQuery({ queryKey: ['account'], queryFn: getAccount })

  const orderMutation = useMutation({
    mutationFn: placeOrder,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['account'] }); setMsg('Order placed successfully'); },
    onError: (e: Error) => setMsg(e.message),
  })

  const resetMutation = useMutation({
    mutationFn: resetAccount,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['account'] }); setMsg('Account reset'); },
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
        <Card>
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

        <Card>
          <h3 className="mb-4 font-semibold text-white">Open Positions</h3>
          {account?.positions.length ? (
            <DataTable>
              <thead>
                <tr>
                  <Th>Ticker</Th>
                  <Th>Qty</Th>
                  <Th>Avg</Th>
                  <Th>LTP</Th>
                  <Th>P&L</Th>
                  <Th>SL/TP</Th>
                </tr>
              </thead>
              <tbody>
                {account.positions.map((p) => (
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
                <Th>Time</Th>
                <Th>Ticker</Th>
                <Th>Side</Th>
                <Th>Qty</Th>
                <Th>Price</Th>
                <Th>Strategy</Th>
              </tr>
            </thead>
            <tbody>
              {account.recent_orders.map((o) => (
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
