import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  apiErrorMessage,
  fetchTickerUniverse,
  fetchWatchlistItems,
  fetchWatchlists,
  type WatchlistInfo,
} from '../../api/client'
import { Chip } from '../ui/Chip'
import { Alert, Loading } from '../ui/Feedback'
import { FormField, Input, Select, Textarea } from '../ui/Form'

export type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

function watchlistMarketFor(assetClass: AssetClass): 'india' | 'us' | 'crypto' | null {
  if (assetClass === 'india' || assetClass === 'us' || assetClass === 'crypto') return assetClass
  return null
}

type Universe = {
  asset_class: string
  picker_type: 'equity_index' | 'crypto' | 'commodity'
  label: string
  scenario: string
  default_durations: string[]
  all_durations: string[]
  index_groups?: Record<string, string[]>
  group_names?: string[]
  custom_default?: string
  default_group?: string
  crypto_modes?: string[]
  crypto_tickers?: Array<{ symbol: string; display: string }>
  crypto_tickers_by_volatility?: string[]
  default_mode?: string
  commodities?: Array<{ symbol: string; name: string }>
}

export type TickerPickerValue = {
  tickers: string[]
  durations: string[]
}

type Props = {
  assetClass: AssetClass
  single?: boolean
  showDurations?: boolean
  /** Initial "how many tickers" selection. Defaults to 15. */
  defaultSelectCount?: TickerSelectCount
  /** Initial crypto Top-N. Defaults to 15. */
  defaultCryptoTopN?: number
  onChange: (value: TickerPickerValue) => void
}

const CRYPTO_TOP_N = [10, 15, 25, 50, 100, 200, 500]
const TICKER_SELECT_COUNTS = [15, 25, 50, 100, 200, 'All'] as const
type TickerSelectCount = number | 'All'

const WL_PREFIX = 'WL:'

function isWatchlistValue(v: string) {
  return v.startsWith(WL_PREFIX)
}

function watchlistIdFromValue(v: string) {
  return Number(v.slice(WL_PREFIX.length))
}

function watchlistOptionValue(id: number) {
  return `${WL_PREFIX}${id}`
}

function parseCustom(raw: string) {
  return raw.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean)
}

function applyCount(pool: string[], n: TickerSelectCount) {
  return n === 'All' ? pool : pool.slice(0, n)
}

export function AssetClassTickerPicker({
  assetClass,
  single = false,
  showDurations = false,
  defaultSelectCount = 15,
  defaultCryptoTopN = 15,
  onChange,
}: Props) {
  const [group, setGroup] = useState('Custom')
  const [cryptoMode, setCryptoMode] = useState('Manual Selection')
  const [cryptoTopN, setCryptoTopN] = useState(defaultCryptoTopN)
  const [selectCount, setSelectCount] = useState<TickerSelectCount>(defaultSelectCount)
  const [search, setSearch] = useState('')
  const [customText, setCustomText] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [durations, setDurations] = useState<string[]>([])
  const [watchlistLoading, setWatchlistLoading] = useState(false)
  const [watchlistError, setWatchlistError] = useState('')
  const [activeWatchlistName, setActiveWatchlistName] = useState('')

  const { data: universe, isLoading, isError, error: universeError } = useQuery({
    queryKey: ['cc-universe', assetClass],
    queryFn: () => fetchTickerUniverse(assetClass) as Promise<Universe>,
  })

  const wlMarket = watchlistMarketFor(assetClass)
  const { data: watchlistsPayload } = useQuery({
    queryKey: ['watchlists'],
    queryFn: fetchWatchlists,
    enabled: wlMarket != null,
  })

  const assetWatchlists = useMemo(() => {
    const lists = (watchlistsPayload?.watchlists ?? []) as WatchlistInfo[]
    if (!wlMarket) return []
    return lists.filter((w) => w.market_type === wlMarket).sort((a, b) => a.name.localeCompare(b.name))
  }, [watchlistsPayload, wlMarket])

  // Reset picker when asset class changes
  useEffect(() => {
    setSearch('')
    setSelected([])
    setCustomText('')
    setWatchlistError('')
    setActiveWatchlistName('')
    if (!universe) return

    setDurations(universe.default_durations ?? ['1d'])

    if (universe.picker_type === 'equity_index') {
      const g = universe.default_group ?? universe.group_names?.[0] ?? 'Custom'
      setGroup(g)
      const pool = universe.index_groups?.[g] ?? []
      setSelected(single ? pool.slice(0, 1) : applyCount(pool, selectCount))
      setCustomText(universe.custom_default ?? '')
    } else if (universe.picker_type === 'crypto') {
      setCryptoMode(universe.default_mode ?? 'Manual Selection')
      const displays = (universe.crypto_tickers ?? []).map((t) => t.display)
      setSelected(single ? displays.slice(0, 1) : applyCount(displays, selectCount))
      setCustomText(universe.custom_default ?? '')
    } else {
      setGroup('All Commodities')
      const syms = (universe.commodities ?? []).map((c) => c.symbol)
      setSelected(single ? syms.slice(0, 1) : applyCount(syms, selectCount))
      setCustomText(universe.custom_default ?? '')
    }
  }, [assetClass, universe, single])

  const applyWatchlistTickers = (tickers: string[], wlName: string) => {
    const pool = single ? tickers.slice(0, 1) : tickers
    setActiveWatchlistName(wlName)
    setWatchlistError('')
    if (universe?.picker_type === 'crypto') {
      setCustomText(pool.join(', '))
      setSelected(pool)
      return
    }
    const norm = universe?.picker_type === 'equity_index'
      ? pool.map((t) => t.toUpperCase())
      : pool
    setCustomText(norm.join(', '))
    setSelected(norm)
  }

  const loadWatchlistById = async (id: number, wlName: string) => {
    setWatchlistLoading(true)
    setWatchlistError('')
    try {
      const data = await fetchWatchlistItems(id)
      const tickers = (data.items ?? [])
        .map((i) => String(i.display_name || i.ticker || '').trim())
        .filter(Boolean)
      if (!tickers.length) {
        setWatchlistError(`Watchlist “${wlName}” has no tickers yet.`)
        setSelected([])
        setCustomText('')
        return
      }
      applyWatchlistTickers(tickers, wlName)
    } catch (e) {
      setWatchlistError(apiErrorMessage(e))
      setSelected([])
      setCustomText('')
    } finally {
      setWatchlistLoading(false)
    }
  }

  const onEquityGroupChange = (g: string) => {
    setGroup(g)
    setSearch('')
    setWatchlistError('')
    if (isWatchlistValue(g)) {
      const id = watchlistIdFromValue(g)
      const wl = assetWatchlists.find((w) => w.id === id)
      void loadWatchlistById(id, wl?.name ?? `Watchlist ${id}`)
      return
    }
    setActiveWatchlistName('')
    if (g !== 'Custom') {
      const pool = universe?.index_groups?.[g] ?? []
      setSelected(single ? pool.slice(0, 1) : applyCount(pool, selectCount))
    }
  }

  const onCryptoModeChange = (m: string) => {
    setCryptoMode(m)
    setSearch('')
    setWatchlistError('')
    if (isWatchlistValue(m)) {
      const id = watchlistIdFromValue(m)
      const wl = assetWatchlists.find((w) => w.id === id)
      void loadWatchlistById(id, wl?.name ?? `Watchlist ${id}`)
      return
    }
    setActiveWatchlistName('')
  }

  const onCommodityGroupChange = (g: string) => {
    setGroup(g)
    setWatchlistError('')
    if (isWatchlistValue(g)) {
      const id = watchlistIdFromValue(g)
      const wl = assetWatchlists.find((w) => w.id === id)
      void loadWatchlistById(id, wl?.name ?? `Watchlist ${id}`)
      return
    }
    setActiveWatchlistName('')
    if (g === 'All Commodities' && universe) {
      const syms = (universe.commodities ?? []).map((c) => c.symbol)
      setSelected(single ? syms.slice(0, 1) : applyCount(syms, selectCount))
    }
  }

  const equityWatchlistActive = isWatchlistValue(group)
  const cryptoWatchlistActive = isWatchlistValue(cryptoMode)
  const commodityWatchlistActive = isWatchlistValue(group)

  const resolvedTickers = useMemo(() => {
    if (!universe) return []

    if (universe.picker_type === 'equity_index') {
      if (equityWatchlistActive) return selected
      if (group === 'Custom') return parseCustom(customText).map((t) => t.toUpperCase())
      return selected
    }

    if (universe.picker_type === 'crypto') {
      if (cryptoWatchlistActive) return selected
      if (cryptoMode === 'Custom') return parseCustom(customText)
      const byDisplay = new Map(
        (universe.crypto_tickers ?? []).map((t) => [t.display, t.symbol]),
      )
      if (cryptoMode === 'Manual Selection') {
        return selected.map((d) => byDisplay.get(d) ?? d)
      }
      const volatilityPool = universe.crypto_tickers_by_volatility ?? []
      const pool = cryptoMode === 'Top Volatile' && volatilityPool.length
        ? volatilityPool
        : (universe.crypto_tickers ?? []).map((t) => t.display)
      const slice = cryptoMode === 'All USDT Pairs'
        ? pool
        : pool.slice(0, cryptoTopN)
      if (single) return [byDisplay.get(slice[0]) ?? slice[0]].filter(Boolean)
      return slice.map((d) => byDisplay.get(d) ?? d)
    }

    if (commodityWatchlistActive) return selected
    if (group === 'Custom') return parseCustom(customText)
    return selected
  }, [
    universe, group, cryptoMode, cryptoTopN, customText, selected, single,
    equityWatchlistActive, cryptoWatchlistActive, commodityWatchlistActive,
  ])

  useEffect(() => {
    onChange({ tickers: resolvedTickers, durations })
  }, [resolvedTickers, durations, onChange])

  const equityPool = useMemo(() => {
    if (!universe?.index_groups || group === 'Custom' || equityWatchlistActive) return []
    const pool = universe.index_groups[group] ?? []
    const q = search.trim().toUpperCase()
    if (!q) return pool
    return pool.filter((t) => t.includes(q))
  }, [universe, group, search, equityWatchlistActive])

  const cryptoDisplayPool = useMemo(() => {
    const pool = (universe?.crypto_tickers ?? []).map((t) => t.display)
    const q = search.trim().toUpperCase()
    if (!q) return pool
    return pool.filter((t) => t.toUpperCase().includes(q))
  }, [universe, search])

  const toggleTicker = (t: string) => {
    if (single) {
      setSelected([t])
      return
    }
    setSelected((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

  const toggleDuration = (d: string) => {
    setDurations((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]))
  }

  const watchlistOptions = assetWatchlists.length > 0 && (
    <optgroup label={`Watchlists (${wlMarket})`}>
      {assetWatchlists.map((w) => (
        <option key={w.id} value={watchlistOptionValue(w.id)}>
          ★ {w.name}
        </option>
      ))}
    </optgroup>
  )

  if (isError) {
    return <Alert type="error">{apiErrorMessage(universeError)}</Alert>
  }

  if (isLoading || !universe) {
    return <Loading message="Loading ticker universe…" />
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">
        <strong className="text-slate-200">{universe.label}</strong>
        {' · '}
        TA profile: <em>{universe.scenario}</em>
      </p>

      {(watchlistLoading || watchlistError) && (
        <div className="text-xs">
          {watchlistLoading && <p className="text-slate-500">Loading watchlist tickers…</p>}
          {watchlistError && <p className="text-amber-400">{watchlistError}</p>}
        </div>
      )}

      {universe.picker_type === 'equity_index' && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Index / Group / Watchlist">
              <Select
                value={group}
                disabled={watchlistLoading}
                onChange={(e) => onEquityGroupChange(e.target.value)}
              >
                {(universe.group_names ?? []).map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
                {watchlistOptions}
              </Select>
            </FormField>
            {!equityWatchlistActive && group !== 'Custom' && (
              <FormField label="Filter symbols">
                <Input
                  placeholder="Type to filter…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </FormField>
            )}
          </div>
          {!equityWatchlistActive && group !== 'Custom' && !single && (
            <FormField label="Select how many tickers">
              <Select
                value={String(selectCount)}
                onChange={(e) => {
                  const raw = e.target.value
                  const n: TickerSelectCount = raw === 'All' ? 'All' : Number(raw)
                  setSelectCount(n)
                  const pool = universe.index_groups?.[group] ?? []
                  setSelected(applyCount(pool, n))
                }}
              >
                {TICKER_SELECT_COUNTS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </Select>
            </FormField>
          )}
          {equityWatchlistActive ? (
            <>
              <p className="text-xs text-slate-500">
                Watchlist{activeWatchlistName ? ` “${activeWatchlistName}”` : ''}: {selected.length} ticker
                {selected.length === 1 ? '' : 's'} — click to {single ? 'select one' : 'toggle'}
              </p>
              <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-800/60 p-2">
                <div className="flex flex-wrap gap-2">
                  {selected.map((t) => (
                    <Chip key={t} selected onClick={() => toggleTicker(t)}>
                      {t}
                    </Chip>
                  ))}
                </div>
              </div>
            </>
          ) : group === 'Custom' ? (
            <FormField label="Custom tickers (comma-separated)">
              <Textarea
                rows={3}
                value={customText}
                onChange={(e) => setCustomText(e.target.value)}
                placeholder={universe.custom_default}
              />
            </FormField>
          ) : (
            <>
              <p className="text-xs text-slate-500">
                {group}: {equityPool.length} symbols — click to {single ? 'select one' : 'toggle'}
              </p>
              <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-800/60 p-2">
                <div className="flex flex-wrap gap-2">
                  {equityPool.map((t) => (
                    <Chip key={t} selected={selected.includes(t)} onClick={() => toggleTicker(t)}>
                      {t}
                    </Chip>
                  ))}
                </div>
              </div>
            </>
          )}
        </>
      )}

      {universe.picker_type === 'crypto' && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Select tickers mode / Watchlist">
              <Select
                value={cryptoMode}
                disabled={watchlistLoading}
                onChange={(e) => onCryptoModeChange(e.target.value)}
              >
                {(universe.crypto_modes ?? []).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
                {watchlistOptions}
              </Select>
            </FormField>
            {!cryptoWatchlistActive && cryptoMode !== 'Custom' && cryptoMode !== 'Manual Selection' && (
              <FormField label="Limit (Top N)">
                <Select
                  value={String(cryptoTopN)}
                  onChange={(e) => setCryptoTopN(Number(e.target.value))}
                >
                  {CRYPTO_TOP_N.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </Select>
              </FormField>
            )}
          </div>
          {cryptoWatchlistActive ? (
            <>
              <p className="text-xs text-slate-500">
                Watchlist{activeWatchlistName ? ` “${activeWatchlistName}”` : ''}: {selected.length} pair
                {selected.length === 1 ? '' : 's'} — click to {single ? 'select one' : 'toggle'}
              </p>
              <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-800/60 p-2">
                <div className="flex flex-wrap gap-2">
                  {selected.map((t) => (
                    <Chip key={t} selected onClick={() => toggleTicker(t)}>
                      {t}
                    </Chip>
                  ))}
                </div>
              </div>
            </>
          ) : cryptoMode === 'Custom' ? (
            <FormField label="Custom crypto pairs (comma-separated)">
              <Textarea
                rows={3}
                value={customText}
                onChange={(e) => setCustomText(e.target.value)}
                placeholder="BTC-USDT, ETH-USDT, SOL-USDT"
              />
            </FormField>
          ) : cryptoMode === 'Manual Selection' ? (
            <>
              <FormField label="Filter pairs">
                <Input
                  placeholder="BTC, ETH…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </FormField>
              <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-800/60 p-2">
                <div className="flex flex-wrap gap-2">
                  {cryptoDisplayPool.map((t) => (
                    <Chip key={t} selected={selected.includes(t)} onClick={() => toggleTicker(t)}>
                      {t}
                    </Chip>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <p className="text-xs text-slate-500">
              Using first {cryptoMode === 'All USDT Pairs' ? 'all' : cryptoTopN} pairs from CoinDCX universe.
            </p>
          )}
        </>
      )}

      {universe.picker_type === 'commodity' && (
        <>
          <FormField label="Universe / Watchlist">
            <Select
              value={group}
              disabled={watchlistLoading}
              onChange={(e) => onCommodityGroupChange(e.target.value)}
            >
              <option value="All Commodities">All Commodities</option>
              <option value="Custom">Custom</option>
              {watchlistOptions}
            </Select>
          </FormField>
          {commodityWatchlistActive ? (
            <>
              <p className="text-xs text-slate-500">
                Watchlist{activeWatchlistName ? ` “${activeWatchlistName}”` : ''}: {selected.length} symbol
                {selected.length === 1 ? '' : 's'}
              </p>
              <div className="flex flex-wrap gap-2">
                {selected.map((t) => (
                  <Chip key={t} selected onClick={() => toggleTicker(t)}>
                    {t}
                  </Chip>
                ))}
              </div>
            </>
          ) : group === 'Custom' ? (
            <FormField label="Custom symbols (Yahoo futures)">
              <Textarea
                rows={2}
                value={customText}
                onChange={(e) => setCustomText(e.target.value)}
                placeholder="CL=F, GC=F, SI=F"
              />
            </FormField>
          ) : (
            <div className="flex flex-wrap gap-2">
              {(universe.commodities ?? []).map((c) => (
                <Chip
                  key={c.symbol}
                  selected={selected.includes(c.symbol)}
                  onClick={() => toggleTicker(c.symbol)}
                >
                  {c.name} ({c.symbol})
                </Chip>
              ))}
            </div>
          )}
        </>
      )}

      {showDurations && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
            Timeframes to analyze
          </p>
          <div className="flex flex-wrap gap-2">
            {universe.all_durations.map((d) => (
              <Chip key={d} selected={durations.includes(d)} onClick={() => toggleDuration(d)}>
                {d}
              </Chip>
            ))}
          </div>
        </div>
      )}

      {resolvedTickers.length > 0 && (
        <p className="text-xs text-slate-500">
          Resolved:{' '}
          <span className="text-slate-300">
            {resolvedTickers
              .map((sym) => {
                const hit = (universe.commodities ?? []).find((c) => c.symbol === sym)
                return hit ? `${hit.name} (${hit.symbol})` : sym
              })
              .join(', ')}
          </span>
        </p>
      )}
    </div>
  )
}
