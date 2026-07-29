import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, RotateCcw, ShoppingCart, X, Pencil, Check } from 'lucide-react'
import {
  getAccount, placeOrder, resetAccount, cancelOrder, modifyOrder, fetchPaperPrice,
  type PaperOrderRow, type PlaceOrderPayload,
} from '../api/client'
import { AssetClassTickerPicker, type TickerPickerValue } from '../components/command-center/AssetClassTickerPicker'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { StatCard } from '../components/ui/StatCard'
import { FormField, Input, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, SortableTh, Th, Td, useSort } from '../components/ui/Table'

type OrderType = 'market' | 'limit' | 'stop' | 'stop_limit'
type PaperAssetClass = 'india' | 'us' | 'crypto' | 'commodity'

function currencySymbol(assetClass?: string): string {
  if (assetClass === 'us' || assetClass === 'commodity') return '$'
  if (assetClass === 'crypto') return ''
  return '₹'
}

const ASSET_CLASS_LABEL: Record<string, string> = {
  india: '🇮🇳 India', us: '🇺🇸 US', crypto: '₿ Crypto', commodity: '🛢️ Commodity',
}

const ORDER_TYPE_LABEL: Record<string, string> = {
  market: 'Market', limit: 'Limit', stop: 'Stop', stop_limit: 'Stop-Limit',
  auto_sl: 'Auto SL', auto_tp: 'Auto TP',
}

const ORDER_TYPE_EXPLANATION: Record<OrderType, string> = {
  market: 'Fills immediately at the current market price. Use this when you want in (or out) right now and don’t care about a precise entry level.',
  limit: 'Stays pending until the price reaches your chosen level, then fills there (or better) — never worse. A buy limit fills at or below your price; a sell limit fills at or above it. Use this to enter/exit at a specific price without watching the market.',
  stop: 'Stays pending until the price crosses your trigger level, then fills as a market order. A buy stop triggers when price rises to the trigger (breakout entry); a sell stop triggers when price falls to it (stop-loss on a long, or breakout-short entry). Useful for automatic downside protection or breakout entries.',
  stop_limit: 'Combines both: once price crosses your trigger level, it places a limit order at your limit price instead of filling at market. Gives price control after the trigger, but can stay unfilled if price moves past the limit before it fills.',
}

const STATUS_BADGE: Record<string, string> = {
  filled: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30',
  pending: 'bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30',
  cancelled: 'bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-lg px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${STATUS_BADGE[status] ?? STATUS_BADGE.cancelled}`}>
      {status}
    </span>
  )
}

function OrderTypeBadge({ orderType }: { orderType: string }) {
  return <span className="text-xs text-slate-400">{ORDER_TYPE_LABEL[orderType] ?? orderType}</span>
}

export default function PaperTrading() {
  const qc = useQueryClient()
  const [assetClass, setAssetClass] = useState<PaperAssetClass>('india')
  const [ticker, setTicker] = useState('RELIANCE')
  const [quantity, setQuantity] = useState(10)
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [orderType, setOrderType] = useState<OrderType>('market')
  const [limitPrice, setLimitPrice] = useState<number | ''>('')
  const [triggerPrice, setTriggerPrice] = useState<number | ''>('')
  const [slPct, setSlPct] = useState<number | ''>('')
  const [tpPct, setTpPct] = useState<number | ''>('')
  const [notes, setNotes] = useState('')
  const [msg, setMsg] = useState('')
  const [confirming, setConfirming] = useState(false)

  const handleAssetClassChange = (next: PaperAssetClass) => {
    setAssetClass(next)
    setTicker('')
  }

  const {
    data: livePrice, isFetching: priceFetching, isError: priceError,
  } = useQuery({
    queryKey: ['paper-price', assetClass, ticker],
    queryFn: () => fetchPaperPrice(ticker, assetClass),
    enabled: ticker.length > 0,
    staleTime: 10_000,
    retry: false,
  })

  const { data: account, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['account'],
    queryFn: getAccount,
    refetchInterval: 15_000,
    refetchIntervalInBackground: true,
  })

  const orderMutation = useMutation({
    mutationFn: placeOrder,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['account'] })
      setMsg(res?.status === 'pending' ? 'Order placed — pending fill' : 'Order filled')
      setConfirming(false)
    },
    onError: (e: Error) => { setMsg(e.message); setConfirming(false) },
  })

  const cancelMutation = useMutation({
    mutationFn: cancelOrder,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['account'] }); setMsg('Order cancelled') },
    onError: (e: Error) => setMsg(e.message),
  })

  const modifyMutation = useMutation({
    mutationFn: ({ orderId, payload }: { orderId: number; payload: { quantity?: number; limit_price?: number; trigger_price?: number } }) =>
      modifyOrder(orderId, payload),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['account'] }); setMsg('Order updated') },
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
    opened_at: (r) => r.opened_at,
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

  const isSuccess = msg.includes('reset') || msg.includes('filled') || msg.includes('pending') || msg.includes('cancelled') || msg.includes('updated')

  const needsLimitPrice = orderType === 'limit' || orderType === 'stop_limit'
  const needsTriggerPrice = orderType === 'stop' || orderType === 'stop_limit'
  const canSubmit =
    quantity > 0 &&
    ticker.trim().length > 0 &&
    (!needsLimitPrice || limitPrice !== '') &&
    (!needsTriggerPrice || triggerPrice !== '')

  const buildPayload = (): PlaceOrderPayload => ({
    ticker,
    side,
    quantity,
    order_type: orderType,
    asset_class: assetClass,
    ...(needsLimitPrice ? { limit_price: Number(limitPrice) } : {}),
    ...(needsTriggerPrice ? { trigger_price: Number(triggerPrice) } : {}),
    ...(slPct !== '' ? { sl_pct: Number(slPct) } : {}),
    ...(tpPct !== '' ? { tp_pct: Number(tpPct) } : {}),
    ...(notes.trim() ? { notes: notes.trim() } : {}),
  })

  const pendingOrders = account?.pending_orders ?? []

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

          <FormField label="Asset class">
            <Select value={assetClass} onChange={(e) => handleAssetClassChange(e.target.value as PaperAssetClass)}>
              <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
              <option value="us">🇺🇸 US stocks (Yahoo)</option>
              <option value="crypto">₿ Crypto (CoinDCX)</option>
              <option value="commodity">🛢️ Commodity futures</option>
            </Select>
          </FormField>

          <FormField label="Ticker">
            <AssetClassTickerPicker
              key={assetClass}
              assetClass={assetClass}
              single
              showDurations={false}
              onChange={(v: TickerPickerValue) => { if (v.tickers[0]) setTicker(v.tickers[0]) }}
            />
          </FormField>
          <p className="mb-4 text-xs text-slate-500">
            {!ticker
              ? null
              : priceFetching
                ? 'Fetching current price…'
                : priceError
                  ? <span className="text-rose-400">Could not fetch a price for this ticker.</span>
                  : livePrice
                    ? <>Current price: <span className="font-medium text-slate-300">{currencySymbol(assetClass)}{livePrice.price.toLocaleString('en-IN')}</span></>
                    : null}
          </p>
          <div className="grid grid-cols-2 gap-3">
            <FormField label="Side">
              <Select value={side} onChange={(e) => setSide(e.target.value as 'buy' | 'sell')}>
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </Select>
            </FormField>
            <FormField label="Order Type">
              <Select value={orderType} onChange={(e) => setOrderType(e.target.value as OrderType)}>
                <option value="market">Market</option>
                <option value="limit">Limit</option>
                <option value="stop">Stop-Loss</option>
                <option value="stop_limit">Stop-Limit</option>
              </Select>
            </FormField>
          </div>
          <p className="mb-4 text-xs leading-relaxed text-slate-500">
            {ORDER_TYPE_EXPLANATION[orderType]}
          </p>
          <FormField label="Quantity">
            <Input type="number" value={quantity} onChange={(e) => setQuantity(parseInt(e.target.value) || 1)} min={1} />
          </FormField>

          {needsLimitPrice && (
            <FormField label="Limit Price">
              <Input
                type="number"
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value === '' ? '' : parseFloat(e.target.value))}
                placeholder={side === 'buy' ? 'Fill at or below this price' : 'Fill at or above this price'}
              />
            </FormField>
          )}
          {needsTriggerPrice && (
            <FormField label={orderType === 'stop_limit' ? 'Stop (Trigger) Price' : 'Trigger Price'}>
              <Input
                type="number"
                value={triggerPrice}
                onChange={(e) => setTriggerPrice(e.target.value === '' ? '' : parseFloat(e.target.value))}
                placeholder={side === 'buy' ? 'Triggers when price rises to this level' : 'Triggers when price falls to this level'}
              />
            </FormField>
          )}

          <div className="grid grid-cols-2 gap-3">
            <FormField label="Stop-Loss % (optional)">
              <Input type="number" value={slPct} onChange={(e) => setSlPct(e.target.value === '' ? '' : parseFloat(e.target.value))} placeholder="e.g. 5" />
            </FormField>
            <FormField label="Take-Profit % (optional)">
              <Input type="number" value={tpPct} onChange={(e) => setTpPct(e.target.value === '' ? '' : parseFloat(e.target.value))} placeholder="e.g. 10" />
            </FormField>
          </div>

          <FormField label="Notes (optional)">
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Why this trade? e.g. thesis, setup, target"
              rows={2}
            />
          </FormField>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <Button className="w-full sm:w-auto" onClick={() => setConfirming(true)} disabled={!canSubmit || orderMutation.isPending}>
              Review Order
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
                  <Th>Asset</Th>
                  <SortableTh active={positionsSortKey === 'quantity'} direction={positionsSortDir} onSort={() => handlePositionsSort('quantity')}>Qty</SortableTh>
                  <SortableTh active={positionsSortKey === 'avg_price'} direction={positionsSortDir} onSort={() => handlePositionsSort('avg_price')}>Avg</SortableTh>
                  <SortableTh active={positionsSortKey === 'ltp'} direction={positionsSortDir} onSort={() => handlePositionsSort('ltp')}>LTP</SortableTh>
                  <SortableTh active={positionsSortKey === 'pnl_pct'} direction={positionsSortDir} onSort={() => handlePositionsSort('pnl_pct')}>P&L</SortableTh>
                  <SortableTh active={positionsSortKey === 'sl_pct'} direction={positionsSortDir} onSort={() => handlePositionsSort('sl_pct')}>SL/TP</SortableTh>
                  <SortableTh active={positionsSortKey === 'opened_at'} direction={positionsSortDir} onSort={() => handlePositionsSort('opened_at')}>Opened</SortableTh>
                  <Th>Notes</Th>
                </tr>
              </thead>
              <tbody>
                {sortedPositions.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/20">
                    <Td className="font-medium text-white">{p.ticker}</Td>
                    <Td className="text-xs text-slate-400">{ASSET_CLASS_LABEL[p.asset_class ?? 'india'] ?? p.asset_class}</Td>
                    <Td>{p.quantity}</Td>
                    <Td>{currencySymbol(p.asset_class)}{p.avg_price}</Td>
                    <Td>{currencySymbol(p.asset_class)}{p.ltp}</Td>
                    <Td className={p.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{p.pnl_pct}%</Td>
                    <Td className="text-slate-500">{p.sl_pct ? `${p.sl_pct}/${p.tp_pct}%` : '—'}</Td>
                    <Td className="text-slate-400">{p.opened_at ? new Date(p.opened_at).toLocaleString() : '—'}</Td>
                    <Td className="max-w-[200px] truncate text-slate-400">
                      <span title={p.notes ?? ''}>{p.notes || '—'}</span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">No open positions</p>
          )}
        </Card>
      </div>

      {pendingOrders.length > 0 && (
        <Card className="mt-6">
          <h3 className="mb-4 font-semibold text-white">Pending Orders</h3>
          <DataTable>
            <thead>
              <tr>
                <Th>Ticker</Th>
                <Th>Asset</Th>
                <Th>Side</Th>
                <Th>Type</Th>
                <Th>Qty</Th>
                <Th>Limit</Th>
                <Th>Trigger</Th>
                <Th>Placed</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {pendingOrders.map((o) => (
                <PendingOrderRow
                  key={o.id}
                  order={o}
                  onCancel={() => cancelMutation.mutate(o.id)}
                  onModify={(payload) => modifyMutation.mutate({ orderId: o.id, payload })}
                  busy={cancelMutation.isPending || modifyMutation.isPending}
                />
              ))}
            </tbody>
          </DataTable>
        </Card>
      )}

      {account && account.recent_orders.length > 0 && (
        <Card className="mt-6">
          <h3 className="mb-4 font-semibold text-white">Recent Orders</h3>
          <DataTable>
            <thead>
              <tr>
                <SortableTh active={ordersSortKey === 'created_at'} direction={ordersSortDir} onSort={() => handleOrdersSort('created_at')}>Time</SortableTh>
                <SortableTh active={ordersSortKey === 'ticker'} direction={ordersSortDir} onSort={() => handleOrdersSort('ticker')}>Ticker</SortableTh>
                <Th>Asset</Th>
                <SortableTh active={ordersSortKey === 'side'} direction={ordersSortDir} onSort={() => handleOrdersSort('side')}>Side</SortableTh>
                <Th>Type</Th>
                <SortableTh active={ordersSortKey === 'quantity'} direction={ordersSortDir} onSort={() => handleOrdersSort('quantity')}>Qty</SortableTh>
                <SortableTh active={ordersSortKey === 'price'} direction={ordersSortDir} onSort={() => handleOrdersSort('price')}>Price</SortableTh>
                <Th>Status</Th>
                <SortableTh active={ordersSortKey === 'strategy'} direction={ordersSortDir} onSort={() => handleOrdersSort('strategy')}>Strategy</SortableTh>
                <Th>Notes</Th>
              </tr>
            </thead>
            <tbody>
              {sortedOrders.map((o) => (
                <tr key={o.id} className="hover:bg-slate-800/20">
                  <Td className="text-slate-400">{new Date(o.created_at).toLocaleString()}</Td>
                  <Td className="font-medium text-white">{o.ticker}</Td>
                  <Td className="text-xs text-slate-400">{ASSET_CLASS_LABEL[o.asset_class ?? 'india'] ?? o.asset_class}</Td>
                  <Td><Badge action={o.side === 'buy' ? 'BUY' : 'SELL'} /></Td>
                  <Td><OrderTypeBadge orderType={o.order_type} /></Td>
                  <Td>{o.quantity}</Td>
                  <Td className="tabular-nums">{currencySymbol(o.asset_class)}{o.filled_price ?? o.price}</Td>
                  <Td><StatusBadge status={o.status} /></Td>
                  <Td className="text-slate-500">{o.strategy ?? '—'}</Td>
                  <Td className="max-w-[200px] truncate text-slate-400">
                    <span title={o.notes ?? ''}>{o.notes || '—'}</span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Card>
      )}

      {confirming && (
        <OrderConfirmDialog
          ticker={ticker}
          assetClass={assetClass}
          side={side}
          quantity={quantity}
          orderType={orderType}
          limitPrice={needsLimitPrice ? Number(limitPrice) : undefined}
          triggerPrice={needsTriggerPrice ? Number(triggerPrice) : undefined}
          slPct={slPct === '' ? undefined : Number(slPct)}
          tpPct={tpPct === '' ? undefined : Number(tpPct)}
          notes={notes.trim() || undefined}
          submitting={orderMutation.isPending}
          onCancel={() => setConfirming(false)}
          onConfirm={() => orderMutation.mutate(buildPayload())}
        />
      )}
    </div>
  )
}

function PendingOrderRow({
  order, onCancel, onModify, busy,
}: {
  order: PaperOrderRow
  onCancel: () => void
  onModify: (payload: { quantity?: number; limit_price?: number; trigger_price?: number }) => void
  busy: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [qty, setQty] = useState(order.quantity)
  const [limitPrice, setLimitPrice] = useState(order.limit_price ?? '')
  const [triggerPrice, setTriggerPrice] = useState(order.trigger_price ?? '')

  if (editing) {
    return (
      <tr className="bg-slate-800/30">
        <Td className="font-medium text-white">{order.ticker}</Td>
        <Td className="text-xs text-slate-400">{ASSET_CLASS_LABEL[order.asset_class ?? 'india'] ?? order.asset_class}</Td>
        <Td><Badge action={order.side === 'buy' ? 'BUY' : 'SELL'} /></Td>
        <Td><OrderTypeBadge orderType={order.order_type} /></Td>
        <Td><Input type="number" className="!w-20 !py-1" value={qty} onChange={(e) => setQty(parseInt(e.target.value) || 1)} /></Td>
        <Td>
          {order.order_type !== 'stop' ? (
            <Input type="number" className="!w-24 !py-1" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value === '' ? '' : parseFloat(e.target.value))} />
          ) : '—'}
        </Td>
        <Td>
          {order.order_type !== 'limit' ? (
            <Input type="number" className="!w-24 !py-1" value={triggerPrice} onChange={(e) => setTriggerPrice(e.target.value === '' ? '' : parseFloat(e.target.value))} />
          ) : '—'}
        </Td>
        <Td className="text-slate-400">{new Date(order.created_at).toLocaleString()}</Td>
        <Td>
          <div className="flex gap-1.5">
            <Button
              size="sm" variant="secondary" disabled={busy}
              onClick={() => {
                onModify({
                  quantity: qty,
                  ...(limitPrice !== '' ? { limit_price: Number(limitPrice) } : {}),
                  ...(triggerPrice !== '' ? { trigger_price: Number(triggerPrice) } : {}),
                })
                setEditing(false)
              }}
            >
              <Check size={14} />
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              <X size={14} />
            </Button>
          </div>
        </Td>
      </tr>
    )
  }

  return (
    <tr className="hover:bg-slate-800/20">
      <Td className="font-medium text-white">{order.ticker}</Td>
      <Td className="text-xs text-slate-400">{ASSET_CLASS_LABEL[order.asset_class ?? 'india'] ?? order.asset_class}</Td>
      <Td><Badge action={order.side === 'buy' ? 'BUY' : 'SELL'} /></Td>
      <Td><OrderTypeBadge orderType={order.order_type} /></Td>
      <Td>{order.quantity}</Td>
      <Td className="tabular-nums">{order.limit_price != null ? `${currencySymbol(order.asset_class)}${order.limit_price}` : '—'}</Td>
      <Td className="tabular-nums">{order.trigger_price != null ? `${currencySymbol(order.asset_class)}${order.trigger_price}` : '—'}</Td>
      <Td className="text-slate-400">{new Date(order.created_at).toLocaleString()}</Td>
      <Td>
        <div className="flex gap-1.5">
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => setEditing(true)}>
            <Pencil size={14} />
          </Button>
          <Button size="sm" variant="danger" disabled={busy} onClick={onCancel}>
            <X size={14} />
          </Button>
        </div>
      </Td>
    </tr>
  )
}

function OrderConfirmDialog({
  ticker, assetClass, side, quantity, orderType, limitPrice, triggerPrice, slPct, tpPct, notes, submitting, onCancel, onConfirm,
}: {
  ticker: string
  assetClass: PaperAssetClass
  side: 'buy' | 'sell'
  quantity: number
  orderType: OrderType
  limitPrice?: number
  triggerPrice?: number
  slPct?: number
  tpPct?: number
  notes?: string
  submitting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const cur = currencySymbol(assetClass)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <Card className="w-full max-w-md">
        <h3 className="mb-4 font-semibold text-white">Confirm Order</h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-400">Action</span>
            <span className="flex items-center gap-2 font-medium text-white">
              <Badge action={side === 'buy' ? 'BUY' : 'SELL'} /> {ticker}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Asset class</span>
            <span className="text-white">{ASSET_CLASS_LABEL[assetClass]}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Order Type</span>
            <span className="text-white">{ORDER_TYPE_LABEL[orderType]}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Quantity</span>
            <span className="text-white">{quantity}</span>
          </div>
          {limitPrice != null && (
            <div className="flex justify-between">
              <span className="text-slate-400">Limit Price</span>
              <span className="text-white">{cur}{limitPrice}</span>
            </div>
          )}
          {triggerPrice != null && (
            <div className="flex justify-between">
              <span className="text-slate-400">Trigger Price</span>
              <span className="text-white">{cur}{triggerPrice}</span>
            </div>
          )}
          {slPct != null && (
            <div className="flex justify-between">
              <span className="text-slate-400">Stop-Loss</span>
              <span className="text-rose-400">{slPct}%</span>
            </div>
          )}
          {tpPct != null && (
            <div className="flex justify-between">
              <span className="text-slate-400">Take-Profit</span>
              <span className="text-emerald-400">{tpPct}%</span>
            </div>
          )}
          {notes && (
            <div className="flex flex-col gap-1">
              <span className="text-slate-400">Notes</span>
              <span className="whitespace-pre-wrap text-white">{notes}</span>
            </div>
          )}
        </div>
        {orderType !== 'market' && (
          <p className="mt-3 text-xs text-slate-500">
            This order will stay pending until the trigger/limit condition is met on a future price refresh.
          </p>
        )}
        <div className="mt-6 flex gap-3">
          <Button className="flex-1" onClick={onConfirm} disabled={submitting}>
            {submitting ? 'Placing…' : 'Confirm'}
          </Button>
          <Button className="flex-1" variant="secondary" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </Card>
    </div>
  )
}
