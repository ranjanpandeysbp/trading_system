import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { apiErrorMessage, fetchPaperPrice, placeOrder, type PlaceOrderPayload } from '../../api/client'
import { Card } from '../ui/Card'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { FormField, Input, Select, Textarea } from '../ui/Form'
import { Alert } from '../ui/Feedback'

type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

function currencySymbol(assetClass: AssetClass): string {
  if (assetClass === 'us' || assetClass === 'commodity') return '$'
  if (assetClass === 'crypto') return ''
  return '₹'
}

export function PlaceTradeModal({
  ticker,
  assetClass,
  strategyLabel,
  defaultSide = 'buy',
  defaultPrice,
  defaultSlPct,
  defaultTpPct,
  onClose,
}: {
  ticker: string
  assetClass: AssetClass
  strategyLabel?: string
  defaultSide?: 'buy' | 'sell'
  defaultPrice?: number | null
  defaultSlPct?: number | null
  defaultTpPct?: number | null
  onClose: () => void
}) {
  const [side, setSide] = useState<'buy' | 'sell'>(defaultSide)
  const [quantity, setQuantity] = useState(1)
  const [orderType, setOrderType] = useState<'market' | 'limit'>('market')
  const [limitPrice, setLimitPrice] = useState<number | ''>('')
  const [slPct, setSlPct] = useState<number | ''>(defaultSlPct ?? '')
  const [tpPct, setTpPct] = useState<number | ''>(defaultTpPct ?? '')
  const [notes, setNotes] = useState(strategyLabel ? `From backtest: ${strategyLabel}` : '')
  const [placed, setPlaced] = useState(false)

  const priceQuery = useQuery({
    queryKey: ['paper-price', assetClass, ticker],
    queryFn: () => fetchPaperPrice(ticker, assetClass),
    enabled: defaultPrice == null,
    staleTime: 10_000,
    retry: false,
  })
  const price = defaultPrice ?? priceQuery.data?.price ?? null

  const placeMutation = useMutation({
    mutationFn: (payload: PlaceOrderPayload) => placeOrder(payload),
    onSuccess: () => setPlaced(true),
  })

  const handleSubmit = () => {
    if (!price || quantity <= 0) return
    placeMutation.mutate({
      ticker,
      side,
      quantity,
      price: orderType === 'limit' && limitPrice !== '' ? undefined : price,
      order_type: orderType,
      limit_price: orderType === 'limit' && limitPrice !== '' ? Number(limitPrice) : undefined,
      sl_pct: slPct === '' ? undefined : Number(slPct),
      tp_pct: tpPct === '' ? undefined : Number(tpPct),
      strategy: strategyLabel,
      notes: notes.trim() || undefined,
      asset_class: assetClass,
    })
  }

  return (
    <Modal onClose={onClose}>
      <Card>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-semibold text-white">Place paper trade — {ticker}</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white">
            <X size={18} />
          </button>
        </div>

        {placed ? (
          <div className="space-y-3">
            <Alert type="success">Order placed for {ticker}.</Alert>
            <Button onClick={onClose}>Done</Button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <FormField label="Side">
                <Select value={side} onChange={(e) => setSide(e.target.value as 'buy' | 'sell')}>
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </Select>
              </FormField>
              <FormField label="Order type">
                <Select value={orderType} onChange={(e) => setOrderType(e.target.value as 'market' | 'limit')}>
                  <option value="market">Market</option>
                  <option value="limit">Limit</option>
                </Select>
              </FormField>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <FormField label="Quantity">
                <Input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
              </FormField>
              <FormField label={orderType === 'limit' ? 'Limit price' : 'Current price'}>
                {orderType === 'limit' ? (
                  <Input
                    type="number"
                    value={limitPrice}
                    placeholder={price != null ? String(price) : undefined}
                    onChange={(e) => setLimitPrice(e.target.value === '' ? '' : Number(e.target.value))}
                  />
                ) : (
                  <div className="flex h-full items-center gap-1.5 text-sm text-slate-300">
                    {priceQuery.isFetching ? (
                      <Loader2 size={14} className="animate-spin text-slate-500" />
                    ) : price != null ? (
                      <span>{currencySymbol(assetClass)}{price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
                    ) : (
                      <span className="text-rose-400">Price unavailable</span>
                    )}
                  </div>
                )}
              </FormField>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <FormField label="Stop loss %">
                <Input type="number" value={slPct} onChange={(e) => setSlPct(e.target.value === '' ? '' : Number(e.target.value))} />
              </FormField>
              <FormField label="Target %">
                <Input type="number" value={tpPct} onChange={(e) => setTpPct(e.target.value === '' ? '' : Number(e.target.value))} />
              </FormField>
            </div>

            <FormField label="Notes">
              <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </FormField>

            {placeMutation.isError && <Alert type="error">{apiErrorMessage(placeMutation.error)}</Alert>}

            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button
                onClick={handleSubmit}
                disabled={placeMutation.isPending || (orderType === 'market' && price == null) || quantity <= 0}
              >
                {placeMutation.isPending ? 'Placing…' : (
                  <span className="inline-flex items-center gap-1.5">
                    <Badge action={side === 'buy' ? 'BUY' : 'SELL'} />
                    Place order
                  </span>
                )}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </Modal>
  )
}
