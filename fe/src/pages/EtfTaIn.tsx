import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IndianRupee, RefreshCw, Save } from 'lucide-react'
import {
  addEtfShopLot,
  apiErrorMessage,
  closeEtfShopLot,
  fetchEtfShopPortfolio,
  fetchEtfTaUniverse,
  runEtfShopDaily,
  updateEtfShopConfig,
  type EtfShopConfig,
  type EtfShopLot,
} from '../api/client'
import {
  StfShopCapitalMetrics,
  StfShopRankTable,
  StfShopRecommendationPanel,
} from '../components/etf-ta/StfShopPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, SortableTh, Th, Td, useSort } from '../components/ui/Table'

type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

const ASSET_CLASSES: { id: AssetClass; label: string }[] = [
  { id: 'india', label: 'India' },
  { id: 'us', label: 'US' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'commodity', label: 'Commodities' },
]

const ASSET_CLASS_DESCRIPTION: Record<AssetClass, string> = {
  india: 'India NSE ETFs or Nifty 50/Next 50 stocks — ETF Shop 4.0 programmatic rotation, dynamic SIP, FIFO compounding',
  us: 'US-listed ETFs (broad market, sector SPDRs, factor/style) or mega-cap stocks — same Rank-vs-20-DMA rotation, dynamic SIP, FIFO compounding, converted to ₹ at a live USD/INR rate',
  crypto: 'Top liquid CoinDCX coins, run through the same buy-and-hold-and-rotate shop — treated as this venue’s closest equivalent to an ETF basket, converted to ₹ at a live USD/INR rate',
  commodity: 'US-listed commodity ETFs (gold, silver, oil, agriculture baskets) or commodity-linked stocks (energy, mining, agriculture majors) — converted to ₹ at a live USD/INR rate',
}

type ConfigDraft = {
  deposited_capital: number
  growth_amount: number
  dividend_withdrawn: number
  slots_divisor: number
  sell_mode: EtfShopConfig['sell_mode']
  profit_target_pct: number
  min_profit_inr: number
  profit_target_inr: number
  prefer_sip: boolean
  averaging_trigger_pct: number
  preset: string
  custom_symbols: string
}

function draftFromConfig(cfg: EtfShopConfig): ConfigDraft {
  return {
    deposited_capital: cfg.deposited_capital,
    growth_amount: cfg.growth_amount,
    dividend_withdrawn: cfg.dividend_withdrawn,
    slots_divisor: cfg.slots_divisor,
    sell_mode: cfg.sell_mode,
    profit_target_pct: cfg.profit_target_pct,
    min_profit_inr: cfg.min_profit_inr,
    profit_target_inr: cfg.profit_target_inr,
    prefer_sip: cfg.prefer_sip,
    averaging_trigger_pct: cfg.averaging_trigger_pct,
    preset: cfg.preset,
    custom_symbols: cfg.custom_symbols ?? '',
  }
}

export default function EtfTaIn() {
  const queryClient = useQueryClient()
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [error, setError] = useState('')
  const [draft, setDraft] = useState<ConfigDraft | null>(null)
  const [sellPriceBySlot, setSellPriceBySlot] = useState<Record<number, string>>({})
  const [sellingId, setSellingId] = useState<number | null>(null)
  const [addSymbol, setAddSymbol] = useState('')
  const [addPrice, setAddPrice] = useState('')
  const [addAmount, setAddAmount] = useState('')

  const { data: universe } = useQuery({
    queryKey: ['etf-ta-universe', assetClass],
    queryFn: () => fetchEtfTaUniverse(assetClass),
  })
  const portfolioQuery = useQuery({
    queryKey: ['etf-shop-portfolio', assetClass],
    queryFn: () => fetchEtfShopPortfolio(assetClass),
  })

  const currency = portfolioQuery.data?.config.currency ?? universe?.currency ?? (assetClass === 'india' ? '₹' : '$')

  useEffect(() => {
    setDraft(null)
    setError('')
  }, [assetClass])

  useEffect(() => {
    if (portfolioQuery.data && !draft) {
      setDraft(draftFromConfig(portfolioQuery.data.config))
    }
  }, [portfolioQuery.data, draft])

  const presetNames = useMemo(
    () => Object.keys(universe?.presets ?? { 'ETF Shop 4.0 — 39 distinct (recommended)': [] }),
    [universe],
  )

  const symbolsPreview = useMemo(() => {
    if (draft?.custom_symbols.trim()) {
      return draft.custom_symbols.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean)
    }
    return universe?.presets?.[draft?.preset ?? ''] ?? universe?.default_symbols ?? []
  }, [draft, universe])

  const saveConfigMutation = useMutation({
    mutationFn: (payload: Partial<EtfShopConfig>) => updateEtfShopConfig({ ...payload, asset_class: assetClass }),
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: (cfg) => {
      setError('')
      queryClient.setQueryData(['etf-shop-portfolio', assetClass], (old: typeof portfolioQuery.data) =>
        old ? { ...old, config: cfg } : old,
      )
    },
  })

  const dailyMutation = useMutation({
    mutationFn: () => runEtfShopDaily(assetClass),
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => {
      setError('')
      queryClient.invalidateQueries({ queryKey: ['etf-shop-portfolio', assetClass] })
    },
  })

  const addLotMutation = useMutation({
    mutationFn: (payload: { symbol: string; price: number; amount: number; lot_type?: string }) =>
      addEtfShopLot({ ...payload, asset_class: assetClass }),
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => {
      setError('')
      setAddSymbol('')
      setAddPrice('')
      setAddAmount('')
      queryClient.invalidateQueries({ queryKey: ['etf-shop-portfolio', assetClass] })
    },
  })

  const closeLotMutation = useMutation({
    mutationFn: ({ lotId, salePrice }: { lotId: number; salePrice: number }) =>
      closeEtfShopLot(lotId, { sale_price: salePrice }),
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: (_data, vars) => {
      setError('')
      setSellingId(null)
      setSellPriceBySlot((s) => {
        const next = { ...s }
        delete next[vars.lotId]
        return next
      })
      queryClient.invalidateQueries({ queryKey: ['etf-shop-portfolio', assetClass] })
    },
  })

  const rec = dailyMutation.data as Record<string, unknown> | undefined
  const analyses = (rec?.analyses as Record<string, unknown>[]) ?? []
  const lots: EtfShopLot[] = portfolioQuery.data?.lots ?? []
  const openLots = lots.filter((p) => p.status === 'open')
  const closedLots = lots.filter((p) => p.status === 'closed')

  const { sorted: sortedLots, sortKey: lotsSortKey, sortDir: lotsSortDir, handleSort: handleLotsSort } = useSort(
    openLots,
    {
      symbol: (r) => r.symbol,
      purchase_date: (r) => r.purchase_date,
      purchase_price: (r) => r.purchase_price,
      amount: (r) => r.amount,
      lot_type: (r) => r.lot_type ?? 'standard',
    },
  )

  const handleSaveConfig = () => {
    if (!draft) return
    saveConfigMutation.mutate(draft)
  }

  const handleAddLot = () => {
    const price = Number(addPrice)
    const amount = Number(addAmount)
    const sym = addSymbol.trim().toUpperCase()
    if (!sym || !price || !amount) return
    addLotMutation.mutate({ symbol: sym, price, amount, lot_type: 'standard' })
  }

  const handleExecuteBuy = () => {
    const buy = rec?.buy_recommendation as Record<string, unknown> | undefined
    if (!buy || buy.action !== 'BUY') return
    const symbol = String(buy.symbol ?? '')
    const price = Number(buy.price)
    const quantity = Number(buy.quantity ?? 0)
    const amount = quantity > 0 ? Number(buy.actual_amount) : Number(buy.slot_amount ?? buy.sip_amount)
    if (!symbol || !price || !amount) return
    addLotMutation.mutate({ symbol, price, amount, lot_type: String(buy.buy_type ?? 'standard') })
  }

  const handleExecuteSell = () => {
    const sell = rec?.primary_sell as Record<string, unknown> | undefined
    if (!sell) return
    const lotId = Number(sell.slot_id)
    const price = Number(sell.current_price)
    if (!lotId || !price) return
    closeLotMutation.mutate({ lotId, salePrice: price })
  }

  const startSell = (lotId: number, currentPrice?: number) => {
    setSellingId(lotId)
    setSellPriceBySlot((s) => ({ ...s, [lotId]: currentPrice ? String(currentPrice) : s[lotId] ?? '' }))
  }

  const confirmSell = (lotId: number) => {
    const price = Number(sellPriceBySlot[lotId])
    if (!price || price <= 0) return
    closeLotMutation.mutate({ lotId, salePrice: price })
  }

  const assetClassPicker = (
    <div className="mb-4 flex flex-wrap gap-2">
      {ASSET_CLASSES.map((ac) => (
        <Chip key={ac.id} selected={assetClass === ac.id} onClick={() => setAssetClass(ac.id)}>
          {ac.label}
        </Chip>
      ))}
    </div>
  )

  if (portfolioQuery.isLoading || !draft) {
    return (
      <div>
        <PageHeader title="ETF TA IN" description={ASSET_CLASS_DESCRIPTION[assetClass]} />
        {assetClassPicker}
        <Loading message="Loading your ETF Shop portfolio…" />
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="ETF TA IN" description={ASSET_CLASS_DESCRIPTION[assetClass]} />
      {assetClassPicker}

      <Card className="mb-4">
        <p className="text-sm text-slate-400">
          <strong className="text-slate-200">ETF Shop 4.0</strong> — Rank 1 vs 20 DMA buys, −10% weakness → dynamic
          SIP, FIFO sells with % + min {currency} targets. Each asset class ({ASSET_CLASSES.map((a) => a.label).join(' / ')}) is
          its own independent shop with its own capital pool, universe, and lot ledger — your capital settings and
          lot ledger are saved to your account, same shop on every device. India's shop can be scheduled under
          Alerts (pick <em>ETF Shop 4.0</em>) for a daily notification without opening this page.
        </p>
      </Card>

      <Card className="mb-4">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Capital &amp; rules</h3>
          <Button size="sm" variant="secondary" onClick={handleSaveConfig} disabled={saveConfigMutation.isPending}>
            <Save size={14} />
            {saveConfigMutation.isPending ? 'Saving…' : 'Save settings'}
          </Button>
        </div>

        <div className="mb-4 rounded-lg border border-slate-800/60 bg-slate-950/40 p-3 text-xs leading-relaxed text-slate-400">
          <p className="mb-2 font-medium text-slate-300">What these settings mean</p>
          <ul className="list-disc space-y-1.5 pl-4">
            <li>
              <strong className="text-slate-300">Deposited capital</strong> — the total money you've put into this
              ETF Shop so far. This (plus Growth reinvested, minus Dividends withdrawn) is what the daily
              recommendation divides by your Slot divisor to size each buy.
            </li>
            <li>
              <strong className="text-slate-300">Growth reinvested</strong> — profit you've booked from past sells
              and chosen to plough back in rather than withdraw, adding to your investable pool without a fresh
              deposit.
            </li>
            <li>
              <strong className="text-slate-300">Dividends withdrawn</strong> — dividend payouts you've taken out
              in cash rather than reinvested; subtracted from your investable pool so the shop doesn't assume
              money is still working that you've already pocketed.
            </li>
            <li>
              <strong className="text-slate-300">Slot divisor</strong> — total capital ÷ this number = the size of
              one "slot" (one buy tranche). A higher divisor means smaller, more numerous buys spread across more
              ETFs/days; a lower divisor means fewer, bigger buys.
            </li>
            <li>
              <strong className="text-slate-300">Sell mode</strong> — the rule for when a held lot is "eligible for
              profit booking": <em>% + min {currency}</em> requires both a minimum % gain and a minimum {currency}
              {' '}gain (the ETF Shop 4.0 default, avoiding both "technically up but trivial" and "big % on a tiny
              position" false positives); <em>% gain only</em> or <em>{currency} gain only</em> use just one of
              those two checks.
            </li>
            <li>
              <strong className="text-slate-300">% profit target</strong> — the minimum % gain a lot needs (from
              your buy price to the current price) to count as eligible for profit booking, when Sell mode includes
              a % check.
            </li>
            <li>
              <strong className="text-slate-300">Min {currency} profit</strong> — the minimum absolute gain a lot
              needs (not %) to count as eligible for profit booking, when Sell mode includes a {currency} check.
            </li>
            <li>
              <strong className="text-slate-300">Prefer SIP when eligible</strong> — when on, the daily
              recommendation can suggest a dynamic-SIP/averaging buy on a weak holding (see Averaging-down trigger
              below) even when it isn't today's #1-ranked ETF; when off, it only ever recommends buying whichever
              ETF currently ranks #1 vs its 20-day moving average.
            </li>
            <li>
              <strong className="text-slate-300">Averaging-down trigger</strong> — when a held ETF falls this % or
              more below your original buy price, it latches into dynamic-SIP/averaging mode: the "Bought" table
              below flags it and suggests topping it up (by default, 10% of what's already invested in it) to lower
              your average cost.
            </li>
          </ul>
        </div>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <FormField label={`Deposited capital (${currency})`}>
            <Input type="number" value={draft.deposited_capital} onChange={(e) => setDraft((d) => d && ({ ...d, deposited_capital: Number(e.target.value) }))} />
          </FormField>
          <FormField label={`Growth reinvested (${currency})`}>
            <Input type="number" value={draft.growth_amount} onChange={(e) => setDraft((d) => d && ({ ...d, growth_amount: Number(e.target.value) }))} />
          </FormField>
          <FormField label={`Dividends withdrawn (${currency})`}>
            <Input type="number" value={draft.dividend_withdrawn} onChange={(e) => setDraft((d) => d && ({ ...d, dividend_withdrawn: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Slot divisor">
            <Input type="number" value={draft.slots_divisor} onChange={(e) => setDraft((d) => d && ({ ...d, slots_divisor: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Sell mode">
            <Select value={draft.sell_mode} onChange={(e) => setDraft((d) => d && ({ ...d, sell_mode: e.target.value as ConfigDraft['sell_mode'] }))}>
              <option value="combined">% + min {currency} (4.0 default)</option>
              <option value="percentage">% gain only</option>
              <option value="absolute">{currency} gain only</option>
            </Select>
          </FormField>
          <FormField label="% profit target">
            <Input type="number" value={draft.profit_target_pct} onChange={(e) => setDraft((d) => d && ({ ...d, profit_target_pct: Number(e.target.value) }))} />
          </FormField>
          <FormField label={`Min ${currency} profit`}>
            <Input type="number" value={draft.min_profit_inr} onChange={(e) => setDraft((d) => d && ({ ...d, min_profit_inr: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Prefer SIP when eligible">
            <Select value={draft.prefer_sip ? 'yes' : 'no'} onChange={(e) => setDraft((d) => d && ({ ...d, prefer_sip: e.target.value === 'yes' }))}>
              <option value="yes">Yes</option>
              <option value="no">No — Rank 1 only</option>
            </Select>
          </FormField>
          <FormField label="Averaging-down trigger (% fall from buy)">
            <Input
              type="number"
              value={draft.averaging_trigger_pct}
              onChange={(e) => setDraft((d) => d && ({ ...d, averaging_trigger_pct: Number(e.target.value) }))}
            />
          </FormField>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          When a held ETF falls this % or more below your initial buy price, it latches into dynamic-SIP/averaging
          mode — the "Bought" table below will flag it and suggest an amount (10% of what's already invested in it).
        </p>
      </Card>

      <Card className="mb-4">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            {assetClass === 'india' ? 'ETF universe' : assetClass === 'crypto' ? 'Coin universe' : 'ETF universe'}
          </h3>
          <Button size="sm" variant="secondary" onClick={handleSaveConfig} disabled={saveConfigMutation.isPending}>
            <Save size={14} />
            {saveConfigMutation.isPending ? 'Saving…' : 'Save universe'}
          </Button>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <FormField label="Preset">
            <Select value={draft.preset} onChange={(e) => setDraft((d) => d && ({ ...d, preset: e.target.value }))}>
              {presetNames.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </Select>
          </FormField>
          <FormField label={`Symbols (${symbolsPreview.length})`}>
            <Textarea
              rows={2}
              placeholder="Custom symbols override preset (comma-separated)"
              value={draft.custom_symbols}
              onChange={(e) => setDraft((d) => d && ({ ...d, custom_symbols: e.target.value }))}
            />
          </FormField>
        </div>
        <div className="mt-4 flex gap-2">
          <Button onClick={() => dailyMutation.mutate()} disabled={dailyMutation.isPending}>
            <IndianRupee size={16} />
            {dailyMutation.isPending ? 'Scanning…' : 'Run daily recommendation'}
          </Button>
          <Button variant="ghost" onClick={() => dailyMutation.mutate()} disabled={dailyMutation.isPending}>
            <RefreshCw size={16} />
            Refresh
          </Button>
        </div>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      {dailyMutation.isPending && (
        <Loading message="Scanning ETFs vs 20 DMA — can take 1–3 minutes…" />
      )}

      {rec && !dailyMutation.isPending && (
        <>
          <Card className="mb-4">
            <StfShopCapitalMetrics rec={rec} currency={currency} />
            <div className="mt-4">
              <StfShopRecommendationPanel
                rec={rec}
                onExecuteBuy={handleExecuteBuy}
                onExecuteSell={handleExecuteSell}
                buyPending={addLotMutation.isPending}
                sellPending={closeLotMutation.isPending}
                currency={currency}
              />
            </div>
            {(rec.data_errors as string[] | undefined)?.length ? (
              <p className="mt-3 text-xs text-amber-400">
                Data errors: {(rec.data_errors as string[]).slice(0, 8).join(', ')}
              </p>
            ) : null}
          </Card>

          <Card className="mb-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-300">Rank vs 20 DMA</h3>
            <StfShopRankTable analyses={analyses} currency={currency} />
          </Card>
        </>
      )}

      <Card className="mb-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-300">Portfolio — open lots (Bought)</h3>
        <DataTable>
          <thead>
            <tr>
              <SortableTh active={lotsSortKey === 'symbol'} direction={lotsSortDir} onSort={() => handleLotsSort('symbol')}>Symbol</SortableTh>
              <SortableTh active={lotsSortKey === 'purchase_date'} direction={lotsSortDir} onSort={() => handleLotsSort('purchase_date')}>Date</SortableTh>
              <SortableTh active={lotsSortKey === 'purchase_price'} direction={lotsSortDir} onSort={() => handleLotsSort('purchase_price')}>Price</SortableTh>
              <Th>Current</Th>
              <SortableTh active={lotsSortKey === 'amount'} direction={lotsSortDir} onSort={() => handleLotsSort('amount')}>Amount</SortableTh>
              <Th>% Profit since bought</Th>
              <SortableTh active={lotsSortKey === 'lot_type'} direction={lotsSortDir} onSort={() => handleLotsSort('lot_type')}>Type</SortableTh>
              <Th>Status</Th>
              <Th>Sell</Th>
            </tr>
          </thead>
          <tbody>
            {sortedLots.length === 0 ? (
              <tr><td colSpan={9} className="px-4 py-3 text-sm text-slate-500">No open lots — record buys after execution.</td></tr>
            ) : sortedLots.map((p) => {
              const pct = p.profit_since_bought_pct
              const profitAbs = p.profit_since_bought_inr
              const pctColor = pct == null ? 'text-slate-500' : pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
              return (
                <tr key={p.id}>
                  <Td className="font-medium">{p.symbol}</Td>
                  <Td>{p.purchase_date}</Td>
                  <Td>{currency}{p.purchase_price.toFixed(2)}</Td>
                  <Td>{p.current_price != null ? `${currency}${p.current_price.toFixed(2)}` : '—'}</Td>
                  <Td>{currency}{p.amount.toLocaleString('en-IN')}</Td>
                  <Td className={pctColor}>
                    {pct != null ? (
                      <>
                        {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                        {profitAbs != null && <span className="ml-1 text-xs text-slate-500">({profitAbs >= 0 ? '+' : ''}{currency}{profitAbs.toLocaleString('en-IN')})</span>}
                      </>
                    ) : '—'}
                  </Td>
                  <Td>{p.lot_type ?? 'standard'}</Td>
                  <Td>
                    <div className="flex flex-col gap-1">
                      {p.eligible_for_profit_booking && (
                        <span
                          className="inline-flex w-fit items-center rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400"
                          title={p.profit_booking_reason ?? ''}
                        >
                          Eligible for profit booking
                        </span>
                      )}
                      {p.averaging_suggested && (
                        <span
                          className="inline-flex w-fit items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-400"
                          title={p.averaging_reason ?? ''}
                        >
                          Consider averaging{p.averaging_amount != null ? ` ~${currency}${Math.round(p.averaging_amount).toLocaleString('en-IN')}` : ''}
                        </span>
                      )}
                    </div>
                  </Td>
                  <Td>
                    {sellingId === p.id ? (
                      <div className="flex items-center gap-2">
                        <div className="w-24">
                          <Input
                            type="number"
                            placeholder={`Sale ${currency}`}
                            value={sellPriceBySlot[p.id] ?? ''}
                            onChange={(e) => setSellPriceBySlot((s) => ({ ...s, [p.id]: e.target.value }))}
                          />
                        </div>
                        <Button size="sm" onClick={() => confirmSell(p.id)} disabled={closeLotMutation.isPending}>
                          Confirm
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setSellingId(null)}>Cancel</Button>
                      </div>
                    ) : (
                      <Button variant="ghost" size="sm" onClick={() => startSell(p.id, p.current_price ?? p.purchase_price)}>Mark sold</Button>
                    )}
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </DataTable>

        <div className="mt-4 grid gap-3 border-t border-slate-800/60 pt-4 md:grid-cols-4">
          <FormField label="Symbol">
            <Input value={addSymbol} onChange={(e) => setAddSymbol(e.target.value)} placeholder={assetClass === 'india' ? 'NIFTYBEES' : assetClass === 'crypto' ? 'B-BTCUSDT' : 'SPY'} />
          </FormField>
          <FormField label="Buy price">
            <Input type="number" value={addPrice} onChange={(e) => setAddPrice(e.target.value)} />
          </FormField>
          <FormField label={`Amount (${currency})`}>
            <Input type="number" value={addAmount} onChange={(e) => setAddAmount(e.target.value)} />
          </FormField>
          <div className="flex items-end">
            <Button onClick={handleAddLot} disabled={addLotMutation.isPending}>
              {addLotMutation.isPending ? 'Adding…' : 'Add lot'}
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 text-sm font-semibold text-slate-300">Bika Hua Maal — closed lots (Sold)</h3>
        <DataTable>
          <thead>
            <tr>
              <Th>Symbol</Th>
              <Th>Bought</Th>
              <Th>Sold</Th>
              <Th>Sale price</Th>
              <Th>Gross P&amp;L</Th>
              <Th>Net P&amp;L</Th>
            </tr>
          </thead>
          <tbody>
            {closedLots.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-3 text-sm text-slate-500">No booked profits yet.</td></tr>
            ) : closedLots.map((p) => (
              <tr key={p.id}>
                <Td className="font-medium">{p.symbol}</Td>
                <Td>{p.purchase_date} · {currency}{p.purchase_price.toFixed(2)}</Td>
                <Td>{p.closed_date}</Td>
                <Td>{currency}{(p.sale_price ?? 0).toFixed(2)}</Td>
                <Td className={(p.gross_profit ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {p.gross_profit != null ? `${currency}${p.gross_profit.toLocaleString('en-IN')}` : '—'}
                </Td>
                <Td className={(p.net_profit ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {p.net_profit != null ? `${currency}${p.net_profit.toLocaleString('en-IN')}` : '—'}
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </Card>
    </div>
  )
}
