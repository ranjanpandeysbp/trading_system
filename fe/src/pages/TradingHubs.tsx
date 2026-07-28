import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BarChart2, Clock, Crosshair, TrendingUp } from 'lucide-react'
import {
  apiErrorMessage,
  fetchTradingHubs,
  runTradingHubScan,
  type TradingHub,
  type TradingHubSection,
} from '../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { TradingHubResultsPanel } from '../components/trading-hubs/TradingHubPanels'
import { Swing5Panel } from '../components/trading-hubs/Swing5Panel'
import { WatchlistMarketProvider, type WatchlistMarket } from '../components/watchlist/WatchlistMarketContext'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const HUB_ICONS: Record<string, typeof TrendingUp> = {
  swing: TrendingUp,
  intraday: Clock,
  scalping: Crosshair,
  smart_money: BarChart2,
}

// Every Trading Hubs strategy trades a fixed timeframe (or fixed combination of
// timeframes) per its own strategy definition — there is no adjustable timeframe
// selector here on purpose. This is display-only context next to each section.
const SECTION_TIMEFRAME_LABEL: Record<string, string> = {
  swing_trading_st: 'Daily',
  swing_trading_st_mtf_mss: 'Weekly + Daily bias + 15m MSS execution',
  swing_trading_st_supertrend: 'Daily (Swing mode) / Weekly (Pyramid mode)',
  swing_trading_st_kiss: 'Weekly bias + 1h execution',
  swing_trading_st_ha_ema: 'Daily bias + 5m execution',
  swing_trading_st_simple_steal: 'Daily',
  swing_trend_breakout: 'Daily (weekly + index-daily context)',
  intraday_alpha_945: '30m opening range + Daily trend filter',
  intraday_7_wasted: 'Daily bias + 5m opening range + 1m execution',
  intraday_fib945: '30m opening-range bias + 5m execution',
  intra_hwp: '5m',
  intraday_vwap_fade: '15m HTF + 5m execution',
  intraday_mtf_breakout_retest: 'Daily bias + 30m/1h/4h HTF + 15m execution',
  scalp_arc: '5m',
  scalp_crt_fvg: '1h HTF sweep + 5m LTF FVG entry',
  scalp_multi_indicator: '1m',
  scalp_rectangle: '1m',
  scalp_heikin_ashi: '1m (India 09:45-11:45 IST / US 10:00-12:00 ET session window; crypto unrestricted)',
  scalp_livefree_fx: 'HTF 1D/4H/1H · 15m sessions · 5m sweep + BoS',
  scalp_smc: '4h HTF + 1h MTF + 5m LTF fusion',
  scalp_sr_mss: '1h HTF zone + 1m MSS entry',
  scalp_weekly: 'Weekly range (from daily) + configurable execution timeframe (15m/1h/4h)',
  scalp_ichimoku_crash: 'Configurable (1h/4h/1d selectable below) — crypto (ETH/BTC) or any market',
  scalp_2min: '2m (1m resampled) · Nifty 50 / Bank Nifty / Sensex only',
  weekly_candle_continuation: 'Configurable (entry timeframe selectable below)',
  smc_cisd: '1h bias + 15m execution',
  smc_htf_zone_sweep: 'Configurable (HTF/LTF selectable below)',
  smc_weekly_sweep_cisd: 'Weekly HTF sweep + 15m execution',
  smc_mtf_day_plan: '4h HTF + 1h MTF + 15m LTF day plan',
  smc_golden_bullet: '1h HTF + 15m NY kill-zone execution',
  smc_liquidity: '1h bias + 15m execution',
  smc_ttg_sniper: 'Configurable (LTF/HTF selectable below)',
  smb_snp: 'Daily HTF + 5m session-window execution',
  sc_fvg: '15m zone + 5m FVG + 1m entry',
  smc_sc_best: 'Configurable (LTF selectable below) + auto HTF resample for context',
  smc_lewiskelly: 'Configurable (Direction/POI TF selectable below) + fixed 1m confirmation entry',
}

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: [] }

function defaultConfig(section: TradingHubSection | undefined): Record<string, string> {
  if (!section?.config_options) return {}
  const out: Record<string, string> = {}
  for (const [key, opt] of Object.entries(section.config_options)) {
    if (opt.default != null) out[key] = String(opt.default)
  }
  return out
}

function sectionHasFixedUniverse(section: TradingHubSection | undefined): boolean {
  return Boolean(section?.fixed_universe?.length)
}

export default function TradingHubs() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [hubId, setHubId] = useState('swing')
  const [sectionId, setSectionId] = useState('')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [config, setConfig] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  const hubsQ = useQuery({ queryKey: ['trading-hubs'], queryFn: fetchTradingHubs })

  const activeHub = useMemo(
    () => hubsQ.data?.hubs?.find((h) => h.id === hubId) as TradingHub | undefined,
    [hubsQ.data, hubId],
  )

  const activeSection = useMemo(
    () => activeHub?.sections?.find((s) => s.id === sectionId) as TradingHubSection | undefined,
    [activeHub, sectionId],
  )

  const fixedUniverse = sectionHasFixedUniverse(activeSection)
  const scanTickers = useMemo(
    () => (fixedUniverse ? (activeSection?.fixed_universe ?? []) : picker.tickers),
    [fixedUniverse, activeSection?.fixed_universe, picker.tickers],
  )

  useEffect(() => {
    const first = activeHub?.sections?.[0]?.id
    if (first && (!sectionId || !activeHub?.sections?.some((s) => s.id === sectionId))) {
      setSectionId(first)
    }
  }, [activeHub, sectionId])

  useEffect(() => {
    setConfig(defaultConfig(activeSection))
  }, [activeSection?.id])

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
    setPicker(DEFAULT_PICKER)
    setError('')
  }

  const handlePickerChange = useCallback((v: TickerPickerValue) => {
    setPicker(v)
  }, [])

  const scanMutation = useMutation({
    mutationFn: () => {
      if (!sectionId) throw new Error('Select a section')
      const tickers = fixedUniverse
        ? (activeSection?.fixed_universe ?? [])
        : picker.tickers
      if (!tickers.length) throw new Error('Select at least one ticker')
      return runTradingHubScan({
        section_id: sectionId,
        tickers,
        // Fixed-universe strategies (e.g. Scalp-2mins) are India indices only.
        asset_class: fixedUniverse ? 'india' : assetClass,
        config: Object.keys(config).length ? config : undefined,
      })
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => setError(''),
  })

  const watchlistMarket: WatchlistMarket =
    assetClass === 'us' || assetClass === 'commodity' ? 'us' : assetClass === 'crypto' ? 'crypto' : 'india'

  return (
    <WatchlistMarketProvider market={watchlistMarket}>
    <div>
      <PageHeader
        title="Trading Hubs"
        description="Swing Trading · Intraday · Scalping · Smart Money — India · US · Crypto · Commodities"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {(hubsQ.data?.hubs ?? []).map((hub) => {
          const Icon = HUB_ICONS[hub.id] ?? TrendingUp
          return (
            <Chip key={hub.id} selected={hubId === hub.id} onClick={() => { setHubId(hub.id); setError('') }}>
              <span className="inline-flex items-center gap-1.5">
                <Icon size={14} />
                {hub.label}
              </span>
            </Chip>
          )
        })}
      </div>

      {activeHub && (
        <p className="mb-4 text-sm text-slate-400">{activeHub.description}</p>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        {activeHub?.sections?.map((s) => (
          <Chip key={s.id} selected={sectionId === s.id} onClick={() => { setSectionId(s.id); setError('') }}>
            {s.label}
          </Chip>
        ))}
      </div>

      <Card className="mb-4">
        {activeSection && (
          <div className="mb-4">
            <p className="text-sm text-slate-400">{activeSection.description}</p>
            {!activeSection.multi_strategy && (
              <p className="mt-1 text-xs text-slate-500">
                🕒 Fixed timeframe: <span className="text-slate-300">{SECTION_TIMEFRAME_LABEL[activeSection.id] ?? 'Per strategy definition'}</span>
                {' — not user-adjustable, this strategy always trades this timeframe.'}
              </p>
            )}
          </div>
        )}

        {fixedUniverse ? (
          <div className="rounded-lg border border-slate-700/80 bg-slate-900/50 px-4 py-3">
            <p className="text-sm font-medium text-slate-200">
              {activeSection?.fixed_universe_label ?? 'Fixed scan universe'}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              This strategy does not use the Crypto / US / commodity ticker picker. It always scans:{' '}
              <span className="text-slate-300">{(activeSection?.fixed_universe ?? []).join(' · ')}</span>
            </p>
          </div>
        ) : (
          <>
            <FormField label="Asset class">
              <Select value={assetClass} onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}>
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
                <option value="commodity">🛢️ Commodity futures</option>
              </Select>
            </FormField>

            <div className="mt-4">
              <AssetClassTickerPicker
                key={assetClass}
                assetClass={assetClass}
                showDurations={false}
                onChange={handlePickerChange}
              />
            </div>
          </>
        )}

        {activeSection?.multi_strategy ? (
          <div className="mt-4">
            <Swing5Panel
              tickers={scanTickers}
              assetClass={assetClass}
              strategyKeys={activeSection.strategy_keys ?? []}
              strategyLabels={activeSection.strategy_labels ?? {}}
              timeframeOptions={activeSection.timeframe_options ?? []}
            />
          </div>
        ) : (
          <>
            {activeSection && Object.entries(activeSection.config_options ?? {}).map(([key, opt]) => (
              <div key={key} className="mt-4">
                <FormField label={opt.label}>
                  {opt.type === 'select' && opt.choices ? (
                    <Select value={config[key] ?? opt.default ?? ''} onChange={(e) => setConfig((c) => ({ ...c, [key]: e.target.value }))}>
                      {opt.choices.map((ch) => (
                        <option key={ch.value} value={ch.value}>{ch.label}</option>
                      ))}
                    </Select>
                  ) : null}
                </FormField>
              </div>
            ))}

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending || !sectionId || !scanTickers.length}>
                {scanMutation.isPending
                  ? `Scanning ${scanTickers.length} ticker${scanTickers.length === 1 ? '' : 's'}…`
                  : `Run live scan${scanTickers.length ? ` (${scanTickers.length})` : ''}`}
              </Button>
              {scanTickers.length > 0 && (
                <span className="text-xs text-slate-500">No ticker count limit — full selected universe is scanned.</span>
              )}
            </div>
            {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          </>
        )}
      </Card>

      {hubsQ.isLoading && <Loading message="Loading trading hubs…" />}

      {!activeSection?.multi_strategy && scanMutation.isPending && (
        <Loading message="Running live scan — fetching OHLCV from Groww/yfinance (1–3 min)…" />
      )}

      {!activeSection?.multi_strategy && !scanMutation.isPending && scanMutation.data && (
        <Card>
          <TradingHubResultsPanel data={scanMutation.data as Record<string, unknown>} sectionId={sectionId} />
        </Card>
      )}
    </div>
    </WatchlistMarketProvider>
  )
}
