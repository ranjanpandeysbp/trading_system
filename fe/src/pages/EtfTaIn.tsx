import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { IndianRupee, RefreshCw } from 'lucide-react'
import {
  apiErrorMessage,
  fetchEtfTaUniverse,
  recommendEtfTaStf,
} from '../api/client'
import {
  StfShopCapitalMetrics,
  StfShopRankTable,
  StfShopRecommendationPanel,
} from '../components/etf-ta/StfShopPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, SortableTh, Th, Td, useSort } from '../components/ui/Table'

const STORAGE_KEY = 'ist_stf_shop_state'

type PortfolioSlot = {
  slot_id: string
  symbol: string
  purchase_price: number
  purchase_date: string
  amount: number
  quantity: number
  status: 'open' | 'closed'
  lot_type?: string
  closed_date?: string
}

type ShopState = {
  deposited: number
  growth: number
  dividend: number
  sipLocked: string[]
  portfolio: PortfolioSlot[]
  shopStart: string | null
  preset: string
  customSymbols: string
  sellMode: 'combined' | 'percentage' | 'absolute'
  profitPct: number
  minProfitInr: number
  profitInr: number
  slotsDivisor: number
  preferSip: boolean
}

const DEFAULT_STATE: ShopState = {
  deposited: 500_000,
  growth: 0,
  dividend: 0,
  sipLocked: [],
  portfolio: [],
  shopStart: null,
  preset: 'ETF Shop 4.0 — 39 distinct (recommended)',
  customSymbols: '',
  sellMode: 'combined',
  profitPct: 6,
  minProfitInr: 500,
  profitInr: 700,
  slotsDivisor: 60,
  preferSip: true,
}

function loadState(): ShopState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_STATE
    return { ...DEFAULT_STATE, ...JSON.parse(raw) }
  } catch {
    return DEFAULT_STATE
  }
}

function saveState(state: ShopState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

function newSlot(symbol: string, price: number, amount: number, lotType = 'standard'): PortfolioSlot {
  return {
    slot_id: crypto.randomUUID().slice(0, 8),
    symbol: symbol.toUpperCase(),
    purchase_price: price,
    purchase_date: new Date().toISOString().slice(0, 10),
    amount,
    quantity: price > 0 ? amount / price : 0,
    status: 'open',
    lot_type: lotType,
  }
}

export default function EtfTaIn() {
  const [state, setState] = useState<ShopState>(loadState)
  const [error, setError] = useState('')
  const [addSymbol, setAddSymbol] = useState('')
  const [addPrice, setAddPrice] = useState('')
  const [addAmount, setAddAmount] = useState('')

  useEffect(() => {
    saveState(state)
  }, [state])

  const { data: universe } = useQuery({ queryKey: ['etf-ta-universe'], queryFn: fetchEtfTaUniverse })

  const presetNames = useMemo(
    () => Object.keys(universe?.presets ?? { 'ETF Shop 4.0 — 39 distinct (recommended)': [] }),
    [universe],
  )

  const symbols = useMemo(() => {
    if (state.customSymbols.trim()) {
      return state.customSymbols.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean)
    }
    return universe?.presets?.[state.preset] ?? universe?.default_symbols ?? []
  }, [state.customSymbols, state.preset, universe])

  const recommendMutation = useMutation({
    mutationFn: () =>
      recommendEtfTaStf({
        symbols,
        deposited_capital: state.deposited,
        growth_amount: state.growth,
        dividend_withdrawn: state.dividend,
        portfolio: state.portfolio,
        sip_locked: state.sipLocked,
        sell_mode: state.sellMode,
        profit_target_pct: state.profitPct,
        profit_target_inr: state.profitInr,
        min_profit_inr: state.minProfitInr,
        slots_divisor: state.slotsDivisor,
        shop_start_date: state.shopStart,
        prefer_sip: state.preferSip,
      }),
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: (data) => {
      setError('')
      const locked = (data as { sip_locked_symbols?: string[] }).sip_locked_symbols
      if (locked) {
        setState((s) => ({ ...s, sipLocked: locked }))
      }
    },
  })

  const rec = recommendMutation.data as Record<string, unknown> | undefined
  const analyses = (rec?.analyses as Record<string, unknown>[]) ?? []
  const openLots = state.portfolio.filter((p) => p.status === 'open')

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

  const handleAddLot = () => {
    const price = Number(addPrice)
    const amount = Number(addAmount)
    const sym = addSymbol.trim().toUpperCase()
    if (!sym || !price || !amount) return
    const slot = newSlot(sym, price, amount)
    setState((s) => ({
      ...s,
      portfolio: [...s.portfolio, slot],
      shopStart: s.shopStart ?? slot.purchase_date,
    }))
    setAddSymbol('')
    setAddPrice('')
    setAddAmount('')
  }

  const handleCloseLot = (slotId: string) => {
    setState((s) => ({
      ...s,
      portfolio: s.portfolio.map((p) =>
        p.slot_id === slotId
          ? { ...p, status: 'closed' as const, closed_date: new Date().toISOString().slice(0, 10) }
          : p,
      ),
    }))
  }

  return (
    <div>
      <PageHeader
        title="ETF TA IN"
        description="India NSE ETF strategies — ETF Shop 4.0 programmatic rotation, dynamic SIP, FIFO compounding"
      />

      <Card className="mb-4">
        <p className="text-sm text-slate-400">
          <strong className="text-slate-200">ETF Shop 4.0</strong> — 39 distinct underlying ETFs, Rank 1 vs 20 DMA buys,
          −10% weakness → dynamic SIP, FIFO sells with % + min ₹ targets. Daily routine under 5 minutes.
        </p>
      </Card>

      <Card className="mb-4">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-400">Capital &amp; rules</h3>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <FormField label="Deposited capital (₹)">
            <Input type="number" value={state.deposited} onChange={(e) => setState((s) => ({ ...s, deposited: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Growth reinvested (₹)">
            <Input type="number" value={state.growth} onChange={(e) => setState((s) => ({ ...s, growth: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Dividends withdrawn (₹)">
            <Input type="number" value={state.dividend} onChange={(e) => setState((s) => ({ ...s, dividend: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Slot divisor">
            <Input type="number" value={state.slotsDivisor} onChange={(e) => setState((s) => ({ ...s, slotsDivisor: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Sell mode">
            <Select value={state.sellMode} onChange={(e) => setState((s) => ({ ...s, sellMode: e.target.value as ShopState['sellMode'] }))}>
              <option value="combined">% + min ₹ (4.0 default)</option>
              <option value="percentage">% gain only</option>
              <option value="absolute">₹ gain only</option>
            </Select>
          </FormField>
          <FormField label="% profit target">
            <Input type="number" value={state.profitPct} onChange={(e) => setState((s) => ({ ...s, profitPct: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Min ₹ profit">
            <Input type="number" value={state.minProfitInr} onChange={(e) => setState((s) => ({ ...s, minProfitInr: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Prefer SIP when eligible">
            <Select value={state.preferSip ? 'yes' : 'no'} onChange={(e) => setState((s) => ({ ...s, preferSip: e.target.value === 'yes' }))}>
              <option value="yes">Yes</option>
              <option value="no">No — Rank 1 only</option>
            </Select>
          </FormField>
        </div>
      </Card>

      <Card className="mb-4">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-400">ETF universe</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <FormField label="Preset">
            <Select value={state.preset} onChange={(e) => setState((s) => ({ ...s, preset: e.target.value }))}>
              {presetNames.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </Select>
          </FormField>
          <FormField label={`Symbols (${symbols.length})`}>
            <Textarea
              rows={2}
              placeholder="Custom symbols override preset (comma-separated)"
              value={state.customSymbols}
              onChange={(e) => setState((s) => ({ ...s, customSymbols: e.target.value }))}
            />
          </FormField>
        </div>
        <div className="mt-4 flex gap-2">
          <Button onClick={() => recommendMutation.mutate()} disabled={recommendMutation.isPending}>
            <IndianRupee size={16} />
            {recommendMutation.isPending ? 'Scanning…' : 'Run daily recommendation'}
          </Button>
          <Button variant="ghost" onClick={() => recommendMutation.mutate()} disabled={recommendMutation.isPending}>
            <RefreshCw size={16} />
            Refresh
          </Button>
        </div>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      {recommendMutation.isPending && (
        <Loading message="Scanning 39 ETFs vs 20 DMA — can take 1–3 minutes…" />
      )}

      {rec && !recommendMutation.isPending && (
        <>
          <Card className="mb-4">
            <StfShopCapitalMetrics rec={rec} />
            <div className="mt-4">
              <StfShopRecommendationPanel rec={rec} />
            </div>
            {(rec.data_errors as string[] | undefined)?.length ? (
              <p className="mt-3 text-xs text-amber-400">
                Data errors: {(rec.data_errors as string[]).slice(0, 8).join(', ')}
              </p>
            ) : null}
          </Card>

          <Card className="mb-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-300">Rank vs 20 DMA</h3>
            <StfShopRankTable analyses={analyses} />
          </Card>
        </>
      )}

      <Card>
        <h3 className="mb-3 text-sm font-semibold text-slate-300">Portfolio — open lots (Bought)</h3>
        <DataTable>
          <thead>
            <tr>
              <SortableTh active={lotsSortKey === 'symbol'} direction={lotsSortDir} onSort={() => handleLotsSort('symbol')}>Symbol</SortableTh>
              <SortableTh active={lotsSortKey === 'purchase_date'} direction={lotsSortDir} onSort={() => handleLotsSort('purchase_date')}>Date</SortableTh>
              <SortableTh active={lotsSortKey === 'purchase_price'} direction={lotsSortDir} onSort={() => handleLotsSort('purchase_price')}>Price</SortableTh>
              <SortableTh active={lotsSortKey === 'amount'} direction={lotsSortDir} onSort={() => handleLotsSort('amount')}>Amount</SortableTh>
              <SortableTh active={lotsSortKey === 'lot_type'} direction={lotsSortDir} onSort={() => handleLotsSort('lot_type')}>Type</SortableTh>
              <Th></Th>
            </tr>
          </thead>
          <tbody>
            {sortedLots.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-3 text-sm text-slate-500">No open lots — record buys after execution.</td></tr>
            ) : sortedLots.map((p) => (
              <tr key={p.slot_id}>
                <Td className="font-medium">{p.symbol}</Td>
                <Td>{p.purchase_date}</Td>
                <Td>₹{p.purchase_price.toFixed(2)}</Td>
                <Td>₹{p.amount.toLocaleString('en-IN')}</Td>
                <Td>{p.lot_type ?? 'standard'}</Td>
                <Td>
                  <Button variant="ghost" size="sm" onClick={() => handleCloseLot(p.slot_id)}>Mark sold</Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>

        <div className="mt-4 grid gap-3 border-t border-slate-800/60 pt-4 md:grid-cols-4">
          <FormField label="Symbol">
            <Input value={addSymbol} onChange={(e) => setAddSymbol(e.target.value)} placeholder="NIFTYBEES" />
          </FormField>
          <FormField label="Buy price">
            <Input type="number" value={addPrice} onChange={(e) => setAddPrice(e.target.value)} />
          </FormField>
          <FormField label="Amount (₹)">
            <Input type="number" value={addAmount} onChange={(e) => setAddAmount(e.target.value)} />
          </FormField>
          <div className="flex items-end">
            <Button onClick={handleAddLot}>Add lot</Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
