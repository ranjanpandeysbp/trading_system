import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Radio, RefreshCw, ShoppingCart, X } from 'lucide-react'
import {
  apiErrorMessage,
  cancelLiveOrder,
  getLiveAccount,
  getLiveBrokers,
  placeLiveOrder,
  type LiveBrokerId,
  type LiveBrokerInfo,
  type LiveOrderRow,
} from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { StatCard } from '../components/ui/StatCard'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, Th, Td } from '../components/ui/Table'

type OrderType = 'market' | 'limit'

const BROKER_HELP: Record<LiveBrokerId, string> = {
  indmoney: 'India equities — configure Client ID / MPIN / TOTP in Manage.',
  groww: 'India equities — configure API key + TOTP in Manage, then refresh token.',
  coindcx: 'Crypto — configure CoinDCX API key + secret in Manage. Use markets like BTCINR.',
}

export default function LiveTrade() {
  const qc = useQueryClient()
  const [broker, setBroker] = useState<LiveBrokerId>('indmoney')
  const [brokerReady, setBrokerReady] = useState(false)
  const [ticker, setTicker] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [orderType, setOrderType] = useState<OrderType>('market')
  const [limitPrice, setLimitPrice] = useState<number | ''>('')
  const [exchange, setExchange] = useState('NSE')
  const [product, setProduct] = useState('CNC')
  const [notes, setNotes] = useState('')
  const [msg, setMsg] = useState('')
  const [confirming, setConfirming] = useState(false)

  const brokersQuery = useQuery({
    queryKey: ['live-brokers'],
    queryFn: getLiveBrokers,
    staleTime: 15_000,
  })

  const defaultBroker = (brokersQuery.data?.default_broker || 'indmoney') as LiveBrokerId

  useEffect(() => {
    if (brokerReady || !brokersQuery.data?.default_broker) return
    setBroker(defaultBroker)
    setBrokerReady(true)
  }, [brokerReady, brokersQuery.data?.default_broker, defaultBroker])

  const activeBroker = useMemo(() => {
    const ids = (brokersQuery.data?.brokers || []).map((b) => b.id || b.broker_id)
    if (ids.includes(broker)) return broker
    if (ids.includes(defaultBroker)) return defaultBroker
    return (ids[0] as LiveBrokerId) || 'indmoney'
  }, [broker, brokersQuery.data, defaultBroker])

  const accountQuery = useQuery({
    queryKey: ['live-account', activeBroker],
    queryFn: () => getLiveAccount(activeBroker),
    refetchInterval: 12_000,
    enabled: Boolean(activeBroker),
  })

  const placeMutation = useMutation({
    mutationFn: placeLiveOrder,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['live-account', activeBroker] })
      qc.invalidateQueries({ queryKey: ['live-brokers'] })
      setConfirming(false)
      if (data.ok) {
        setMsg(data.broker_result?.message ? String(data.broker_result.message) : 'Order submitted')
      } else {
        setMsg(data.error?.message || data.order?.message || 'Order rejected by broker')
      }
    },
    onError: (e: unknown) => {
      setConfirming(false)
      setMsg(apiErrorMessage(e))
    },
  })

  const cancelMutation = useMutation({
    mutationFn: ({ id }: { id: number }) => cancelLiveOrder(id, activeBroker),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['live-account', activeBroker] })
    },
  })

  const brokerMeta = accountQuery.data?.broker
  const portfolio = accountQuery.data?.portfolio
  const holdings = portfolio?.holdings ?? []
  const orders: LiveOrderRow[] = accountQuery.data?.recent_orders ?? []
  const funds = portfolio?.funds
  const connected = Boolean(brokerMeta?.connected)
  const configured = Boolean(brokerMeta?.credentials_configured)

  const submit = () => {
    if (!ticker.trim() || quantity <= 0) {
      setMsg('Enter a ticker and quantity')
      return
    }
    setConfirming(true)
  }

  const confirmPlace = () => {
    placeMutation.mutate({
      broker: activeBroker,
      ticker: ticker.trim(),
      side,
      quantity,
      order_type: orderType,
      limit_price: orderType === 'limit' && limitPrice !== '' ? Number(limitPrice) : null,
      exchange: activeBroker === 'coindcx' ? undefined : exchange,
      product: activeBroker === 'coindcx' ? undefined : product,
      notes: notes || null,
    })
  }

  return (
    <div>
      <PageHeader
        title="Live Trade"
        description="Choose a broker → view portfolio → place live orders. Configure credentials in Manage."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {(brokersQuery.data?.brokers || [
          { id: 'indmoney', label: 'INDMoney', broker_id: 'indmoney' },
          { id: 'groww', label: 'Groww', broker_id: 'groww' },
          { id: 'coindcx', label: 'CoinDCX', broker_id: 'coindcx' },
        ] as Array<Pick<LiveBrokerInfo, 'id' | 'label' | 'broker_id'>>).map((b) => {
          const id = (b.id || b.broker_id) as LiveBrokerId
          return (
            <Chip
              key={id}
              selected={activeBroker === id}
              onClick={() => {
                setBroker(id)
                setMsg('')
                setTicker(id === 'coindcx' ? 'BTCINR' : '')
              }}
            >
              {b.label}
            </Chip>
          )
        })}
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            qc.invalidateQueries({ queryKey: ['live-brokers'] })
            qc.invalidateQueries({ queryKey: ['live-account', activeBroker] })
          }}
        >
          <RefreshCw size={14} /> Refresh
        </Button>
        <Link
          to="/settings"
          className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 hover:border-slate-500 hover:text-white"
        >
          <Radio size={13} /> Manage broker credentials
        </Link>
      </div>

      <p className="mb-4 text-xs text-slate-500">{BROKER_HELP[activeBroker]}</p>

      {accountQuery.isLoading && <Loading message="Loading live account…" />}

      {accountQuery.data && (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Connection"
              value={connected ? 'Connected' : configured ? 'Creds saved' : 'Not configured'}
            />
            <StatCard
              label="Available funds"
              value={
                funds?.available != null
                  ? `${funds.currency || ''} ${Number(funds.available).toLocaleString()}`
                  : '—'
              }
            />
            <StatCard label="Holdings" value={String(holdings.length)} />
            <StatCard label="Recent orders" value={String(orders.length)} />
          </div>

          {(accountQuery.data.error || brokerMeta?.message) && (
            <div className="mb-4">
              <Alert type={connected ? 'success' : 'error'}>
                {accountQuery.data.error?.message || brokerMeta?.message}
                {!configured && (
                  <>
                    {' '}
                    <Link to="/settings" className="underline">
                      Open Manage
                    </Link>
                  </>
                )}
              </Alert>
            </div>
          )}

          {portfolio?.message && connected && (
            <p className="mb-3 text-[11px] text-slate-500">{portfolio.message}</p>
          )}

          <div className="mb-4 grid gap-4 lg:grid-cols-2">
            <Card>
              <div className="mb-3 flex items-center gap-2">
                <ShoppingCart size={18} className="text-rose-400" />
                <h3 className="font-semibold text-white">Place live order</h3>
                <span className="inline-flex rounded-lg bg-rose-500/15 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-rose-300 ring-1 ring-rose-500/30">
                  LIVE
                </span>
              </div>
              <FormField label="Ticker / market">
                <Input
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                  placeholder={activeBroker === 'coindcx' ? 'BTCINR' : 'RELIANCE'}
                />
              </FormField>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label="Side">
                  <Select value={side} onChange={(e) => setSide(e.target.value as 'buy' | 'sell')}>
                    <option value="buy">Buy</option>
                    <option value="sell">Sell</option>
                  </Select>
                </FormField>
                <FormField label="Quantity">
                  <Input
                    type="number"
                    min={0}
                    step="any"
                    value={quantity}
                    onChange={(e) => setQuantity(Number(e.target.value) || 0)}
                  />
                </FormField>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label="Order type">
                  <Select value={orderType} onChange={(e) => setOrderType(e.target.value as OrderType)}>
                    <option value="market">Market</option>
                    <option value="limit">Limit</option>
                  </Select>
                </FormField>
                {orderType === 'limit' && (
                  <FormField label="Limit price">
                    <Input
                      type="number"
                      value={limitPrice}
                      onChange={(e) => setLimitPrice(e.target.value === '' ? '' : Number(e.target.value))}
                    />
                  </FormField>
                )}
              </div>
              {activeBroker !== 'coindcx' && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <FormField label="Exchange">
                    <Select value={exchange} onChange={(e) => setExchange(e.target.value)}>
                      <option value="NSE">NSE</option>
                      <option value="BSE">BSE</option>
                    </Select>
                  </FormField>
                  <FormField label="Product">
                    <Select value={product} onChange={(e) => setProduct(e.target.value)}>
                      <option value="CNC">CNC (delivery)</option>
                      <option value="MIS">MIS (intraday)</option>
                      <option value="NRML">NRML</option>
                    </Select>
                  </FormField>
                </div>
              )}
              <FormField label="Notes (optional)">
                <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
              </FormField>
              <Button
                className="w-full"
                onClick={submit}
                disabled={!configured || placeMutation.isPending}
              >
                Review live {side.toUpperCase()}
              </Button>
              <p className="mt-2 text-[11px] text-amber-400/90">
                Real money — double-check ticker, qty, and broker before confirming.
              </p>
            </Card>

            <Card>
              <h3 className="mb-3 font-semibold text-white">Portfolio holdings</h3>
              {holdings.length === 0 ? (
                <p className="text-sm text-slate-500">No holdings returned for this broker yet.</p>
              ) : (
                <DataTable>
                  <thead>
                    <tr>
                      <Th>Symbol</Th>
                      <Th>Qty</Th>
                      <Th>Avg</Th>
                      <Th>Exch</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.map((h) => (
                      <tr key={`${h.symbol}-${h.exchange || ''}`}>
                        <Td className="font-medium text-slate-200">{h.symbol}</Td>
                        <Td>{h.quantity}</Td>
                        <Td>{h.avg_price != null ? Number(h.avg_price).toFixed(2) : '—'}</Td>
                        <Td>{h.exchange || '—'}</Td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              )}
            </Card>
          </div>

          <Card>
            <h3 className="mb-3 font-semibold text-white">Recent live orders</h3>
            {orders.length === 0 ? (
              <p className="text-sm text-slate-500">No orders yet for {activeBroker}.</p>
            ) : (
              <DataTable>
                <thead>
                  <tr>
                    <Th>Time</Th>
                    <Th>Ticker</Th>
                    <Th>Side</Th>
                    <Th>Qty</Th>
                    <Th>Type</Th>
                    <Th>Status</Th>
                    <Th>Broker id</Th>
                    <Th></Th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={`${o.id}-${o.broker_order_id || ''}`}>
                      <Td className="text-[11px] text-slate-500">
                        {o.created_at ? new Date(o.created_at).toLocaleString() : '—'}
                      </Td>
                      <Td className="font-medium text-slate-200">{o.ticker}</Td>
                      <Td className={o.side === 'buy' ? 'text-emerald-400' : 'text-rose-400'}>
                        {o.side}
                      </Td>
                      <Td>{o.quantity}</Td>
                      <Td>{o.order_type}</Td>
                      <Td>
                        <Badge action={o.status} />
                      </Td>
                      <Td className="max-w-[8rem] truncate text-[11px] text-slate-500">
                        {o.broker_order_id || '—'}
                      </Td>
                      <Td>
                        {o.id > 0 &&
                          o.broker_order_id &&
                          !['cancelled', 'rejected', 'error', 'success', 'filled'].includes(
                            String(o.status || '').toLowerCase(),
                          ) && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => cancelMutation.mutate({ id: o.id })}
                            disabled={cancelMutation.isPending}
                          >
                            <X size={14} /> Cancel
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Card>
        </>
      )}

      {msg && (
        <div className="mt-4">
          <Alert type={msg.toLowerCase().includes('fail') || msg.toLowerCase().includes('reject') ? 'error' : 'success'}>
            {msg}
          </Alert>
        </div>
      )}

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-2xl border border-rose-500/30 bg-slate-900 p-5 shadow-xl">
            <p className="text-sm font-semibold text-rose-300">Confirm LIVE order</p>
            <p className="mt-2 text-sm text-slate-300">
              {side.toUpperCase()} <span className="font-semibold text-white">{quantity}</span> of{' '}
              <span className="font-semibold text-white">{ticker || '—'}</span> on{' '}
              <span className="font-semibold text-white">{activeBroker}</span>
              {orderType === 'limit' && limitPrice !== '' ? ` @ ${limitPrice}` : ' (market)'}
            </p>
            <div className="mt-4 flex gap-2">
              <Button className="flex-1" onClick={confirmPlace} disabled={placeMutation.isPending}>
                Place live order
              </Button>
              <Button className="flex-1" variant="secondary" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
