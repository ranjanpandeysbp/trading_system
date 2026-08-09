import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  apiErrorMessage,
  fetchTickerSuggestions,
  runOptionsCallPutWriting,
  runOptionsDeltaNeutral,
  runOptionsDoubleCalendar,
  runOptionsGokulChhabra,
  runOptionsHedging,
  runOptionsMarketPrediction,
  runOptionsZeroToHero,
} from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import { AssetClassTickerPicker, type TickerPickerValue } from '../components/command-center/AssetClassTickerPicker'
import {
  OptionsBackgroundControls,
  OptionsBackgroundJobsAndReports,
  useOptionsBackground,
  type OptionsSectionId,
} from '../components/options/OptionsBackground'
import { DeltaNeutralPanel, DoubleCalendarPanel, GokulChhabraPanel, HedgingPanel, MarketPredictionPanel, CallPutWritingPanel, ZeroToHeroPanel } from '../components/options/OptionsPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { StrategyDataSourceBar } from '../components/ui/StrategyDataSourceBar'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

const SECTIONS = [
  { id: 'double_calendar', label: '📅 Double Calendar' },
  { id: 'delta_neutral', label: '🎰 Delta Neutral' },
  { id: 'hedging', label: '🛡️ Hedging' },
  { id: 'gokul_chhabra', label: '🎯 Gokul Chhabra 3m ITM' },
  { id: 'zero_to_hero', label: '🚀 Zero to Hero' },
  { id: 'market_prediction', label: '🔮 Market Prediction' },
  { id: 'call_put_writing', label: '✍️ Call Put Writing' },
] as const

// Mirrors market_prediction_engine.FURTHER_ANALYSIS_OPTIONS on the backend — stock mode only.
const MARKET_PREDICTION_FURTHER_ANALYSIS_OPTIONS: { id: string; label: string }[] = [
  { id: 'pa_vp_smc', label: 'PA-VP-SMC' },
  { id: 'volume_spread_next_candle', label: 'Volume Spread - Next Candle' },
  { id: 'elliott_wave', label: 'Elliott Wave' },
  { id: 'bb_mean_reversion', label: 'BB Mean Reversion' },
  { id: 'support_resistance', label: 'Support & Resistance' },
  { id: 'mtf_trend_strength', label: 'Trend & Strength (MTF)' },
]

const MARKET_PREDICTION_EXPLANATION = `Checks whether the move on the "as of" trading day shown on the result is actually backed by conviction in
the derivatives data, or is a "hollow" move — price rising while the options market quietly prices in doubt —
the same read a derivatives desk makes before trusting a rally or a selloff. Data comes from NSE's live option
chain (the same feed that powers nseindia.com/option-chain), refreshed daily.

Works on an index OR a single stock — pick "Index" for one of the 5 NSE indices with listed F&O contracts
(Nifty 50, Bank Nifty, Nifty Financial Services, Nifty Midcap Select, Nifty Next 50 — BSE's Sensex/Bankex have
no working options-chain data source in this app, verified live rather than assumed), or "Stock" for any NSE
stock that has a listed options chain.

Signals combined:
1. Synthetic futures premium/discount — a Put-Call-Parity synthetic futures price (Spot + ATM Call LTP - ATM
   Put LTP), standing in for a live NSE futures feed this app doesn't have. A discount during a rally (or
   premium during a selloff) is a classic bearish/bullish divergence.
2. OI buildup — Long/Short Buildup (fresh conviction) vs Short Covering/Long Unwinding (existing positions
   being cut, not fresh ones opened), read off the options chain's aggregate OI change vs price.
3. IV skew — elevated ATM Put IV vs Call IV (hedging demand) during a rally, or the reverse during a selloff.
3b. PCR (OI) / Max Pain read — the same put-call-ratio-by-open-interest and max-pain-pull logic used
   elsewhere in this app's option-chain tools, applied here as an extra independent check: does the broader
   positioning picture (not just the ATM strikes) agree with today's move?
4. India VIX — rising fear alongside a rally (or falling fear alongside a selloff) is a mismatch (index only).
5. Late-session move check — today's last-5-minute move compared against the day's own typical 5-minute
   swing, flagging an outsized, low-context late move.
6. FII/DII cash-market flow (NSE/StockEdge) — net institutional buying/selling that contradicts the move.

This app has no live NSE index-futures price feed or FII index-derivative (not cash) positioning data — if
you have today's actual futures LTP or know FII index positions were cut, enter them below to fold in real
numbers instead of the built-in stand-ins; otherwise the synthetic-futures and cash-market FII/DII reads are
used, clearly labeled as such in every reason shown.

The result also shows a plain-English paragraph up front summarizing how many independent checks agree vs
disagree with the day's move, plus the exact "as of" date and option-chain expiry the read is based on.

Research / education only — not financial advice.`

type SectionId = (typeof SECTIONS)[number]['id']
type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: ['1d'] }

const STRATEGY_EXPLANATION = `A delta-neutral, theta-positive options strategy for a range-bound market. It profits from the
difference in time decay (theta) between a near-term short option and a longer-dated long option at the same
(or a wider) strike — the near-term leg decays faster, so the spread gains value as time passes, as long as
price stays roughly between the strikes.

Setup: sell a Call and a Put ~2 weeks out (short legs); buy a Call and a Put ~1 week later, ~3 weeks out
(long legs). Short legs sit a fixed % out of the money; long legs sit at the same strikes (Double Calendar)
or slightly further OTM (Double Diagonal, which widens the profit zone).

Entry criteria: enter only in a low-IV environment — this is a positive-Vega trade that benefits if IV rises
after entry but loses value quickly if IV crashes.

Management: target 20-40% profit — start scaling out at 20%, close the majority by 40%. Don't hold until
expiration. Use a 30% mental stop — don't set a hard stop in your broker, since wide bid-ask spreads on
multi-leg spreads can trigger it prematurely on a bad print.

Data sources: India (NSE indices/stocks) uses live NSE option-chain strikes/premiums/IV for the listed
expiries nearest your chosen short/long DTE. US uses live Yahoo Finance option chain. Crypto/Commodities
have no listed options-chain feed here, so legs are priced with Black-Scholes using the underlying's own
realized volatility as an IV proxy — every simulated leg is labeled "Simulated". The VIX gate uses real
India VIX / US VIX for India/US; Crypto/Commodities use a realized-volatility percentile rank instead.

Heuristic framework, not a fill guarantee — research / education only, not financial advice.`

const DELTA_NEUTRAL_EXPLANATION = `A defined-risk premium-selling strategy that profits if the underlying simply stays inside a range,
regardless of direction. You act as "the casino": collect Theta (time decay) from OTM option buyers, with
your probability of winning approximated by Delta.

Setup: sell an out-of-the-money Put and an out-of-the-money Call at the same expiry ("sell the inner
range") — both expire worthless, you keep the premium, as long as price stays between the two short
strikes. Target short-strike Delta ~0.15-0.25 (~70-80% mathematical probability of profit), not a chart
read — the whole edge is the risk premium baked into option pricing, not direction prediction.

Risk cap: a naked short strangle carries infinite risk on a gap. Buy further-OTM "wings" (long call above
the short call, long put below the short put) immediately after — this caps max loss at (wing width - net
credit), turning it into a defined-risk Iron Condor (or Iron Fly, if the short strikes are placed
at-the-money instead of OTM).

Best in a choppy/range-bound market — avoid holding through major macro events (FOMC, earnings,
geopolitical shocks). Take profit early: close at 30-50% of max credit captured. Don't hold to expiry, and
don't chase the last few % of premium.

Data sources: India (NSE indices/stocks) uses live NSE option-chain strikes/premiums/IV for the nearest
listed expiry to the target DTE; short strikes are chosen by matching each strike's own listed IV to a
Black-Scholes delta target. US uses live Yahoo Finance option chain, same delta-matching. Crypto/Commodities
have no listed options-chain feed here, so strikes are placed by inverting Black-Scholes delta directly and
priced with Black-Scholes using the underlying's own realized volatility as an IV proxy — every simulated
leg is labeled "Simulated". The VIX/choppy gate reuses the same real India VIX / US VIX check as Double
Calendar, plus a trend-strength (ADX) read.

Heuristic framework, not a fill guarantee — research / education only, not financial advice.`

const HEDGING_EXPLANATION = `Non-Directional Delta-Neutral Options Hedging — intraday income strategy from Vikas
(https://www.youtube.com/watch?v=FXhudoBZ5SU). Profits from premium decay in a sideways market while capping
catastrophic risk with hedges bought up front.

Clear signal on every scan:
  BUY  = enter the hedge (zones intact + favorable vol/chop) — shown with confidence %, SL% and TP% of total capital
  SELL = exit / adjust now (a candle closed beyond Demand or Supply) — close the losing short leg, keep hedges
  WAIT = stand by (zone only being tested, missing data, or environment not favorable yet)

Pre-requisite — chart Demand/Supply zones: on a 15-minute chart, the strong swing low below the session's
opening price is your Demand Zone; the strong swing high above it is your Supply Zone. If no clear zone has
formed yet (early session), this falls back to the 1-hour chart to find recent major reversal areas. Mark
these BEFORE entering, so later decisions aren't "fake adjustments" made in the heat of the moment.

Setup (Delta N): short one ATM Call + one ATM Put (each ~0.5 delta, canceling out — Delta Neutral at entry).
Immediately buy deep OTM Call + Put hedges, ~4% away from spot (cheap, ~₹5-7 premium in the video's Nifty
example) — this caps the max loss against a gap, black-swan move, or broker glitch.

Adjustment — the crucial step: do NOT adjust on a small mark-to-market wiggle, and do NOT adjust just because
price is touching a zone — wait for a candle to strictly CLOSE beyond the Demand/Supply zone. Once broken:
exit the losing leg (the one whose delta spiked), keep the hedges exactly as they are, sell a fresh ATM leg on
the broken side. This deliberately leaves a small residual delta rather than re-flattening to zero — a
snap-back safety net if price returns to the original range. Maximum one adjustment per day.

Risk management (the "brain" of the strategy): hard stop at 2-3% of TOTAL capital (not margin deployed) — exit
everything immediately if touched. Take profit around 1-1.5% of total capital — an inverted risk:reward
offset by a high win rate; frequent small losses are normal, large losses should only happen in extreme,
unmanaged conditions. Size positions so the capital-based stop doesn't feel threatening — hedging needing
less margin is not a reason to deploy all of it.

Data sources: leg pricing/selection reuses this app's Delta-Neutral (Iron Fly) engine — live NSE option-chain
for India, live Yahoo option chain for US, Black-Scholes-simulated (clearly labeled "Simulated") for
Crypto/Commodities. Demand/Supply zones use this app's own OHLCV feed on the selected intraday timeframe —
this app can't track your live open position, so the adjustment signal and P&L check are read-only tools, not
an automated trade manager.

Heuristic framework, not a fill guarantee — research / education only, not financial advice.`

const GOKUL_EXPLANATION = `Dr. Gokul Chhabra option-buying masterclass (https://www.youtube.com/watch?v=2RnBT9DDDNI).

Analyse Nifty / Bank Nifty on a 3-minute chart (futures proxied via index OHLC; 1m bars resampled
to 3m). Indicators: session VWAP, VWMA(20), SuperTrend(10, 3). Trade only 09:45–15:15 IST — ignore
the first 30 minutes, flat by 15:15, no BTST.

Buy Call when close is strictly above VWAP, VWMA, and SuperTrend. Buy Put when strictly below all
three. If price is trapped between the indicators, stay flat. Prefer a VWMA pullback entry if you
missed the initial breakout.

Initial stop: a 3-minute candle closing beyond SuperTrend. At 1:1 R:R move the stop to cost-to-cost.
Target at least 1:2. Execute by buying ITM options targeting delta 0.60–0.75 from the live NSE chain.

Research / education only — not financial advice.`

const ZERO_TO_HERO_EXPLANATION = `"Zero to Hero" intraday option buying strategy — AbhishekXTrades (https://www.youtube.com/watch?v=slAtZyGfAlI).

Step 1 — Mark levels: on a 15-minute chart, draw a line at the previous trading day's high and low.
Only the previous day matters, not older history.

Step 2 — Bias: trading above the previous day's high -> buy-side (Call) setups only. Trading below the
previous day's low -> sell-side (Put) setups only. Trading between the two is a sideways trap zone where
option buyers lose money — take no trades there.

Step 3 — Entry: wait for a pullback against your bias to close (a red candle while buying, a green candle
while selling), then wait for a later candle to close back through that pullback candle's OPEN in your
bias direction. A pullback should resolve in 1-2 candles — if three same-colour pullback candles form in a
row, the setup is cancelled (that's a trend reversal, not a pullback).

Step 4 — Stop-loss & exit: stop just beyond the entry candle's extreme (low for a buy, high for a sell),
with a small buffer so an exact double-top/bottom wick doesn't stop you out. The moment the trade reaches
1:1 risk:reward, book ~50-60% of the position. Put NO fixed target on the remainder — let it run, uncapped,
until 3:15 PM IST. Some days it gives back the 1:1 gain on the runner; on trending days it captures a
200-400 point Nifty move. If stopped out before 1:1, you can re-enter on a fresh setup; once 1:1 is
already booked, don't re-enter that session's move.

Fixed universe: Nifty 50 / Bank Nifty (futures proxied via index OHLC), since this is specifically an
index option-buying strategy. This scanner reports whether a fresh entry signal exists right now — it
does not track your own open position, so use the reasons/exit rule shown as your manual management
checklist for the 1:1 partial-book and re-entry rules above.

Research / education only — not financial advice.`

const CALL_PUT_WRITING_EXPLANATION = `Call / Put Writing — OI walls & short-covering risk.

Inspired by weekly index outlooks that frame near-term resistance from aggressive Call writing
(open-interest walls at key strikes), support from Put writing, and short-covering if Call walls break.
Also contrasts institutional-style hedges (buy Puts / sell Calls) vs retail Put selling — this app
reads the live option chain; NSE FII/Pro/Client participant OI is not auto-fetched.

Works on an index OR a single stock — pick "Index" for NSE F&O indices (Nifty 50, Bank Nifty,
FINNIFTY, MIDCPNIFTY, NIFTYNXT50) or "Stock" for any NSE name with a listed options chain.

What we compute:
1. Primary Call wall — highest Call OI overhead → resistance writers are defending.
2. Primary Put floor — highest Put OI below → support.
3. Fresh writing tilt — Call ΔOI vs Put ΔOI (who is writing more today).
4. PCR (OI) / Max Pain — broader positioning + expiry magnet.
5. OI buildup — Long/Short Buildup vs covering / unwinding.
6. Short-covering risk — spot testing or clearing the Call wall.

Trade lean (BUY / SELL / WAIT) fades heavy Call writing into the wall, buys dips when Put writing
dominates, or watches covering if the wall breaks. Always pair with price structure.

Research / education only — not financial advice.`

export default function Options() {
  const [searchParams, setSearchParams] = useSearchParams()
  const sectionFromUrl = searchParams.get('section')
  const initialSection: SectionId =
    sectionFromUrl && SECTIONS.some((s) => s.id === sectionFromUrl)
      ? (sectionFromUrl as SectionId)
      : 'double_calendar'
  const [section, setSection] = useState<SectionId>(initialSection)
  const bg = useOptionsBackground(section as OptionsSectionId)

  useEffect(() => {
    const next = searchParams.get('section')
    if (next && SECTIONS.some((s) => s.id === next) && next !== section) {
      setSection(next as SectionId)
    }
  }, [searchParams, section])

  const selectSection = useCallback(
    (id: SectionId) => {
      setSection(id)
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          p.set('section', id)
          return p
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [error, setError] = useState('')

  const [shortDte, setShortDte] = useState(14)
  const [longDte, setLongDte] = useState(21)
  const [otmOffsetPct, setOtmOffsetPct] = useState(1.5)
  const [isDiagonal, setIsDiagonal] = useState(false)
  const [diagonalWidenPct, setDiagonalWidenPct] = useState(1.0)
  const [tpStart, setTpStart] = useState(20)
  const [tpMax, setTpMax] = useState(40)
  const [stopLossPct, setStopLossPct] = useState(30)
  const [vixMax, setVixMax] = useState(20)

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
    setPicker(DEFAULT_PICKER)
    setError('')
  }

  const runMutation = useMutation({
    mutationFn: () => {
      const { tickers, durations } = picker
      if (!tickers.length) throw new Error('Select at least one ticker')
      return runOptionsDoubleCalendar({
        tickers, asset_class: assetClass, timeframes: durations.length ? durations : ['1d'],
        short_dte: shortDte, long_dte: longDte, otm_offset_pct: otmOffsetPct,
        diagonal_widen_pct: isDiagonal ? diagonalWidenPct : 0,
        take_profit_start: tpStart / 100, take_profit_max: tpMax / 100, stop_loss: -stopLossPct / 100,
        vix_max_threshold: vixMax, vol_percentile_max: vixMax,
      })
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMutation.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Double Calendar', data) : ''
  const showDcResults = !!data && (!runMutation.isPending || bg.viewedReportId != null)

  const [dnAssetClass, setDnAssetClass] = useState<AssetClass>('india')
  const [dnPicker, setDnPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [dnError, setDnError] = useState('')

  const [dte, setDte] = useState(30)
  const [deltaTarget, setDeltaTarget] = useState(0.20)
  const [wingWidthPct, setWingWidthPct] = useState(5.0)
  const [ironFly, setIronFly] = useState(false)
  const [dnTpPct, setDnTpPct] = useState(50)
  const [slMultiple, setSlMultiple] = useState(1.0)
  const [dnVixMax, setDnVixMax] = useState(20)
  const [adxMax, setAdxMax] = useState(25)

  const handleDnPickerChange = useCallback((v: TickerPickerValue) => setDnPicker(v), [])

  const handleDnAssetClassChange = (next: AssetClass) => {
    setDnAssetClass(next)
    setDnPicker(DEFAULT_PICKER)
    setDnError('')
  }

  const runDnMutation = useMutation({
    mutationFn: () => {
      const { tickers, durations } = dnPicker
      if (!tickers.length) throw new Error('Select at least one ticker')
      return runOptionsDeltaNeutral({
        tickers, asset_class: dnAssetClass, timeframes: durations.length ? durations : ['1d'],
        dte, short_delta_target: deltaTarget, wing_width_pct: wingWidthPct, iron_fly: ironFly,
        profit_target_pct: dnTpPct / 100, stop_loss_multiple: slMultiple,
        vix_max_threshold: dnVixMax, vol_percentile_max: dnVixMax, adx_trend_max: adxMax,
      })
    },
    onSuccess: () => setDnError(''),
    onError: (e) => setDnError(apiErrorMessage(e)),
  })

  const dnData = (bg.viewedPayload ?? runDnMutation.data) as Record<string, unknown> | undefined
  const dnAskContext = dnData ? buildAskContext('Delta Neutral', dnData) : ''
  const showDnResults = !!dnData && (!runDnMutation.isPending || bg.viewedReportId != null)

  const [hgAssetClass, setHgAssetClass] = useState<AssetClass>('india')
  const [hgPicker, setHgPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [hgError, setHgError] = useState('')

  const [hgDte, setHgDte] = useState(2)
  const [hedgeDistancePct, setHedgeDistancePct] = useState(4.0)
  const [zoneTf, setZoneTf] = useState('15m')
  const [zoneFallbackTf, setZoneFallbackTf] = useState('1h')
  const [totalCapital, setTotalCapital] = useState(500000)
  const [hgTpPct, setHgTpPct] = useState(1.25)
  const [hgSlPct, setHgSlPct] = useState(2.5)

  const handleHgPickerChange = useCallback((v: TickerPickerValue) => setHgPicker(v), [])

  const handleHgAssetClassChange = (next: AssetClass) => {
    setHgAssetClass(next)
    setHgPicker(DEFAULT_PICKER)
    setHgError('')
  }

  const runHgMutation = useMutation({
    mutationFn: () => {
      const { tickers } = hgPicker
      if (!tickers.length) throw new Error('Select at least one ticker')
      return runOptionsHedging({
        tickers, asset_class: hgAssetClass,
        dte: hgDte, hedge_distance_pct: hedgeDistancePct,
        zone_timeframe: zoneTf, zone_fallback_timeframe: zoneFallbackTf,
        total_capital: totalCapital,
        profit_target_pct_of_capital: hgTpPct / 100, max_loss_pct_of_capital: hgSlPct / 100,
      })
    },
    onSuccess: () => setHgError(''),
    onError: (e) => setHgError(apiErrorMessage(e)),
  })

  const hgData = (bg.viewedPayload ?? runHgMutation.data) as Record<string, unknown> | undefined
  const hgAskContext = hgData ? buildAskContext('Hedging', hgData) : ''
  const showHgResults = !!hgData && (!runHgMutation.isPending || bg.viewedReportId != null)

  const [gkError, setGkError] = useState('')
  const [vwmaLen, setVwmaLen] = useState(20)
  const [stPeriod, setStPeriod] = useState(10)
  const [stMult, setStMult] = useState(3)
  const [minRr, setMinRr] = useState(2)
  const [deltaLo, setDeltaLo] = useState(0.6)
  const [deltaHi, setDeltaHi] = useState(0.75)

  const runGkMutation = useMutation({
    mutationFn: () =>
      runOptionsGokulChhabra({
        tickers: ['Nifty 50', 'Bank Nifty'],
        vwma_length: vwmaLen,
        st_period: stPeriod,
        st_multiplier: stMult,
        min_rr: minRr,
        target_delta_min: deltaLo,
        target_delta_max: deltaHi,
      }),
    onSuccess: () => setGkError(''),
    onError: (e) => setGkError(apiErrorMessage(e)),
  })
  const gkData = (bg.viewedPayload ?? runGkMutation.data) as Record<string, unknown> | undefined
  const gkAskContext = gkData ? buildAskContext('Gokul Chhabra', gkData) : ''
  const showGkResults = !!gkData && (!runGkMutation.isPending || bg.viewedReportId != null)

  const [mpError, setMpError] = useState('')
  const [mpMode, setMpMode] = useState<'index' | 'stock'>('index')
  const [mpSymbol, setMpSymbol] = useState('NIFTY')
  const [mpStockTicker, setMpStockTicker] = useState('')
  const [mpStockDebounced, setMpStockDebounced] = useState('')
  const [mpSuggestOpen, setMpSuggestOpen] = useState(false)
  const [mpFuturesPrice, setMpFuturesPrice] = useState('')
  const [mpFiiCut, setMpFiiCut] = useState<'unset' | 'yes' | 'no'>('unset')
  const [mpFurtherAnalysis, setMpFurtherAnalysis] = useState<string[]>([])

  useEffect(() => {
    const t = setTimeout(() => setMpStockDebounced(mpStockTicker.trim()), 200)
    return () => clearTimeout(t)
  }, [mpStockTicker])

  const mpSuggestQuery = useQuery({
    queryKey: ['mp-stock-suggest', mpStockDebounced],
    queryFn: () => fetchTickerSuggestions('india', mpStockDebounced, 10),
    enabled: mpMode === 'stock' && mpStockDebounced.length >= 1,
  })
  const mpSuggestions = mpSuggestQuery.data?.tickers ?? []
  const mpActiveSymbol = mpMode === 'stock' ? mpStockTicker.trim().toUpperCase() : mpSymbol

  const runMpMutation = useMutation({
    mutationFn: () =>
      runOptionsMarketPrediction({
        symbol: mpActiveSymbol,
        is_index: mpMode === 'index',
        futures_price: mpFuturesPrice.trim() ? Number(mpFuturesPrice) : undefined,
        fii_index_position_cut: mpFiiCut === 'unset' ? undefined : mpFiiCut === 'yes',
        further_analysis: mpMode === 'stock' && mpFurtherAnalysis.length ? mpFurtherAnalysis : undefined,
      }),
    onSuccess: () => setMpError(''),
    onError: (e) => setMpError(apiErrorMessage(e)),
  })
  const mpData = (bg.viewedPayload ?? runMpMutation.data) as Record<string, unknown> | undefined
  const mpAskContext = mpData ? buildAskContext('Market Prediction', mpData) : ''
  const showMpResults = !!mpData && (!runMpMutation.isPending || bg.viewedReportId != null)

  const [cpwError, setCpwError] = useState('')
  const [cpwMode, setCpwMode] = useState<'index' | 'stock'>('index')
  const [cpwSymbol, setCpwSymbol] = useState('NIFTY')
  const [cpwStockTicker, setCpwStockTicker] = useState('')
  const [cpwStockDebounced, setCpwStockDebounced] = useState('')
  const [cpwSuggestOpen, setCpwSuggestOpen] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setCpwStockDebounced(cpwStockTicker.trim()), 200)
    return () => clearTimeout(t)
  }, [cpwStockTicker])

  const cpwSuggestQuery = useQuery({
    queryKey: ['cpw-stock-suggest', cpwStockDebounced],
    queryFn: () => fetchTickerSuggestions('india', cpwStockDebounced, 10),
    enabled: cpwMode === 'stock' && cpwStockDebounced.length >= 1,
  })
  const cpwSuggestions = cpwSuggestQuery.data?.tickers ?? []
  const cpwActiveSymbol = cpwMode === 'stock' ? cpwStockTicker.trim().toUpperCase() : cpwSymbol

  const runCpwMutation = useMutation({
    mutationFn: () =>
      runOptionsCallPutWriting({
        symbol: cpwActiveSymbol,
        is_index: cpwMode === 'index',
      }),
    onSuccess: () => setCpwError(''),
    onError: (e) => setCpwError(apiErrorMessage(e)),
  })
  const cpwData = (bg.viewedPayload ?? runCpwMutation.data) as Record<string, unknown> | undefined
  const cpwAskContext = cpwData ? buildAskContext('Call Put Writing', cpwData) : ''
  const showCpwResults = !!cpwData && (!runCpwMutation.isPending || bg.viewedReportId != null)

  const [zthError, setZthError] = useState('')
  const [zthTf, setZthTf] = useState('15m')
  const [zthSlBuffer, setZthSlBuffer] = useState(0.05)
  const [zthMaxPullback, setZthMaxPullback] = useState(3)
  const [zthPartialRr, setZthPartialRr] = useState(1.0)
  const [zthPartialPct, setZthPartialPct] = useState(55)
  const [zthSessionEnd, setZthSessionEnd] = useState('15:15')

  const runZthMutation = useMutation({
    mutationFn: () =>
      runOptionsZeroToHero({
        tickers: ['Nifty 50', 'Bank Nifty'],
        execution_tf: zthTf,
        sl_buffer_pct: zthSlBuffer,
        max_pullback_candles: zthMaxPullback,
        partial_book_rr: zthPartialRr,
        partial_book_pct: zthPartialPct,
        session_end: zthSessionEnd,
      }),
    onSuccess: () => setZthError(''),
    onError: (e) => setZthError(apiErrorMessage(e)),
  })
  const zthData = (bg.viewedPayload ?? runZthMutation.data) as Record<string, unknown> | undefined
  const zthAskContext = zthData ? buildAskContext('Zero to Hero', zthData) : ''
  const showZthResults = !!zthData && (!runZthMutation.isPending || bg.viewedReportId != null)

  return (
    <div>
      <PageHeader title="Options" description="Options income & directional buying — Double Calendar · Delta Neutral · Hedging · Gokul Chhabra · Zero to Hero · Market Prediction · Call Put Writing" />

      <div className="mb-4 flex flex-wrap gap-2">
        {SECTIONS.map(({ id, label }) => (
          <Chip key={id} selected={section === id} onClick={() => selectSection(id)}>{label}</Chip>
        ))}
      </div>

      {section === 'double_calendar' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Sell near-term calls/puts, buy longer-dated calls/puts at the same (or wider) strikes — a
            theta-positive, range-bound income spread. Low-IV entry gate, 20-40% take-profit, 30% mental stop.
          </p>

          <CollapsibleSection title="📖 How the Double Calendar works" copyText={STRATEGY_EXPLANATION}>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-400">{STRATEGY_EXPLANATION}</p>
          </CollapsibleSection>

          <Card>
            <FormField label="Asset class">
              <select
                className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                value={assetClass}
                onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}
              >
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
                <option value="commodity">🛢️ Commodity futures</option>
              </select>
            </FormField>

            <AssetClassTickerPicker
              key={assetClass}
              assetClass={assetClass}
              showDurations
              defaultSelectCount="All"
              onChange={handlePickerChange}
            />

            <div className="mt-4">
              <CollapsibleSection title="⚙️ Setup & Management Rules">
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="Short leg DTE (days)">
                    <Input type="number" min={1} max={60} value={shortDte} onChange={(e) => setShortDte(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Long leg DTE (days)">
                    <Input type="number" min={2} max={90} value={longDte} onChange={(e) => setLongDte(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Short strikes % OTM">
                    <Input type="number" step={0.1} min={0.1} max={15} value={otmOffsetPct} onChange={(e) => setOtmOffsetPct(Number(e.target.value))} />
                  </FormField>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input type="checkbox" checked={isDiagonal} onChange={(e) => setIsDiagonal(e.target.checked)} />
                    Double Diagonal (widen long-leg strikes)
                  </label>
                  <FormField label="Extra % OTM for long legs">
                    <Input
                      type="number" step={0.1} min={0} max={10} value={diagonalWidenPct} disabled={!isDiagonal}
                      onChange={(e) => setDiagonalWidenPct(Number(e.target.value))}
                    />
                  </FormField>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="Scale-out starts at (%)">
                    <Input type="number" min={5} max={60} value={tpStart} onChange={(e) => setTpStart(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Close majority by (%)">
                    <Input type="number" min={10} max={100} value={tpMax} onChange={(e) => setTpMax(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Mental stop-loss (%)">
                    <Input type="number" min={5} max={80} value={stopLossPct} onChange={(e) => setStopLossPct(Number(e.target.value))} />
                  </FormField>
                </div>
                <FormField label="Max VIX / vol-percentile ceiling for entry">
                  <Input type="number" min={5} max={100} value={vixMax} onChange={(e) => setVixMax(Number(e.target.value))} />
                </FormField>
              </CollapsibleSection>
            </div>

            <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || bg.runInBackground}>
              {runMutation.isPending
                ? `Building ${picker.tickers.length || ''}…`
                : `📅 Build Double Calendar${picker.tickers.length ? ` (${picker.tickers.length})` : ''}`}
            </Button>
            <OptionsBackgroundControls
              bg={bg}
              placeholder={`Double Calendar · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(
                {
                  tickers: picker.tickers,
                  asset_class: assetClass,
                  timeframes: picker.durations.length ? picker.durations : ['1d'],
                  short_dte: shortDte,
                  long_dte: longDte,
                  otm_offset_pct: otmOffsetPct,
                  diagonal_widen_pct: isDiagonal ? diagonalWidenPct : 0,
                  take_profit_start: tpStart / 100,
                  take_profit_max: tpMax / 100,
                  stop_loss: -stopLossPct / 100,
                  vix_max_threshold: vixMax,
                  vol_percentile_max: vixMax,
                },
                () => (!picker.tickers.length ? 'Select at least one ticker' : null),
              )}
            />
            {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          </Card>

          <OptionsBackgroundJobsAndReports bg={bg} />

          {runMutation.isPending && <Loading message="Building Double Calendar…" />}

          {showDcResults && (
            <Card>
              {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
                <p className="mb-3 text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
                </p>
              )}
              <StrategyDataSourceBar data={(data ?? undefined) as Record<string, unknown> | undefined} assetClass="india" />
              <DoubleCalendarPanel
                data={data!} stopLoss={-stopLossPct / 100} takeProfitStart={tpStart / 100} takeProfitMax={tpMax / 100}
              />
            </Card>
          )}

          {askContext && showDcResults && (
            <AskAIPanel context={askContext} section="options/double_calendar" />
          )}
        </div>
      )}

      {section === 'delta_neutral' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Sell an OTM Call + OTM Put, buy further-OTM wings to cap risk — a defined-risk, range-bound
            income spread (Iron Condor / Iron Fly). ~70-80% target probability of profit, close at 30-50%
            of max credit.
          </p>

          <CollapsibleSection title="📖 How Delta-Neutral (Iron Condor / Iron Fly) works" copyText={DELTA_NEUTRAL_EXPLANATION}>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-400">{DELTA_NEUTRAL_EXPLANATION}</p>
          </CollapsibleSection>

          <Card>
            <FormField label="Asset class">
              <select
                className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                value={dnAssetClass}
                onChange={(e) => handleDnAssetClassChange(e.target.value as AssetClass)}
              >
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
                <option value="commodity">🛢️ Commodity futures</option>
              </select>
            </FormField>

            <AssetClassTickerPicker
              key={dnAssetClass}
              assetClass={dnAssetClass}
              showDurations
              defaultSelectCount="All"
              onChange={handleDnPickerChange}
            />

            <div className="mt-4">
              <CollapsibleSection title="⚙️ Setup & Management Rules">
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="Expiry DTE (days)">
                    <Input type="number" min={1} max={90} value={dte} onChange={(e) => setDte(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Short-strike target Delta">
                    <Input type="number" step={0.01} min={0.05} max={0.45} value={deltaTarget} onChange={(e) => setDeltaTarget(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Wing width (% beyond short strike)">
                    <Input type="number" step={0.5} min={0.5} max={30} value={wingWidthPct} onChange={(e) => setWingWidthPct(Number(e.target.value))} />
                  </FormField>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input type="checkbox" checked={ironFly} onChange={(e) => setIronFly(e.target.checked)} />
                    Iron Fly (ATM short strikes)
                  </label>
                  <FormField label="Close at (% of max credit)">
                    <Input type="number" min={10} max={90} value={dnTpPct} onChange={(e) => setDnTpPct(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Defensive close (x credit received, 0=off)">
                    <Input type="number" step={0.1} min={0} max={5} value={slMultiple} onChange={(e) => setSlMultiple(Number(e.target.value))} />
                  </FormField>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <FormField label="Max VIX / vol-percentile ceiling">
                    <Input type="number" min={5} max={100} value={dnVixMax} onChange={(e) => setDnVixMax(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Max ADX to call the market 'choppy'">
                    <Input type="number" min={10} max={60} value={adxMax} onChange={(e) => setAdxMax(Number(e.target.value))} />
                  </FormField>
                </div>
              </CollapsibleSection>
            </div>

            <Button className="mt-4" onClick={() => runDnMutation.mutate()} disabled={runDnMutation.isPending || bg.runInBackground}>
              {runDnMutation.isPending
                ? `Building ${dnPicker.tickers.length || ''}…`
                : `🎯 Build Delta-Neutral Spread${dnPicker.tickers.length ? ` (${dnPicker.tickers.length})` : ''}`}
            </Button>
            <OptionsBackgroundControls
              bg={bg}
              placeholder={`Delta Neutral · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(
                {
                  tickers: dnPicker.tickers,
                  asset_class: dnAssetClass,
                  timeframes: dnPicker.durations.length ? dnPicker.durations : ['1d'],
                  dte,
                  short_delta_target: deltaTarget,
                  wing_width_pct: wingWidthPct,
                  iron_fly: ironFly,
                  profit_target_pct: dnTpPct / 100,
                  stop_loss_multiple: slMultiple,
                  vix_max_threshold: dnVixMax,
                  vol_percentile_max: dnVixMax,
                  adx_trend_max: adxMax,
                },
                () => (!dnPicker.tickers.length ? 'Select at least one ticker' : null),
              )}
            />
            {dnError && <div className="mt-3"><Alert type="error">{dnError}</Alert></div>}
          </Card>

          <OptionsBackgroundJobsAndReports bg={bg} />

          {runDnMutation.isPending && <Loading message="Building Delta-Neutral spread…" />}

          {showDnResults && (
            <Card>
              {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
                <p className="mb-3 text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
                </p>
              )}
              <StrategyDataSourceBar data={(dnData ?? undefined) as Record<string, unknown> | undefined} assetClass="india" />
              <DeltaNeutralPanel data={dnData!} profitTargetPct={dnTpPct / 100} stopLossMultiple={slMultiple} />
            </Card>
          )}

          {dnAskContext && showDnResults && (
            <AskAIPanel context={dnAskContext} section="options/delta_neutral" />
          )}
        </div>
      )}

      {section === 'hedging' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Short ATM Call + Put, hedged with far-OTM Call + Put ~4% away — non-directional, intraday premium
            decay. Chart Demand/Supply zones off the session open first; only adjust on a strict candle close
            beyond a zone. Hard stop at 2-3% of total capital, take profit ~1-1.5%.
          </p>

          <CollapsibleSection title="📖 How the Hedging strategy works" copyText={HEDGING_EXPLANATION}>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-400">{HEDGING_EXPLANATION}</p>
          </CollapsibleSection>

          <Card>
            <FormField label="Asset class">
              <select
                className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                value={hgAssetClass}
                onChange={(e) => handleHgAssetClassChange(e.target.value as AssetClass)}
              >
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
                <option value="commodity">🛢️ Commodity futures</option>
              </select>
            </FormField>

            <AssetClassTickerPicker
              key={hgAssetClass}
              assetClass={hgAssetClass}
              defaultSelectCount="All"
              onChange={handleHgPickerChange}
            />

            <div className="mt-4">
              <CollapsibleSection title="⚙️ Setup & Risk Management">
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="Target DTE (days, → nearest listed expiry)">
                    <Input type="number" min={0} max={14} value={hgDte} onChange={(e) => setHgDte(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Hedge distance (% away from spot)">
                    <Input type="number" step={0.5} min={1} max={15} value={hedgeDistancePct} onChange={(e) => setHedgeDistancePct(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Total capital">
                    <Input type="number" min={1000} value={totalCapital} onChange={(e) => setTotalCapital(Number(e.target.value))} />
                  </FormField>
                </div>
                <div className="grid gap-4 sm:grid-cols-4">
                  <FormField label="Zone timeframe">
                    <select
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                      value={zoneTf}
                      onChange={(e) => setZoneTf(e.target.value)}
                    >
                      <option value="15m">15 minutes</option>
                      <option value="30m">30 minutes</option>
                      <option value="1h">1 hour</option>
                    </select>
                  </FormField>
                  <FormField label="Fallback timeframe">
                    <select
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                      value={zoneFallbackTf}
                      onChange={(e) => setZoneFallbackTf(e.target.value)}
                    >
                      <option value="1h">1 hour</option>
                      <option value="4h">4 hours</option>
                    </select>
                  </FormField>
                  <FormField label="Take profit (% of total capital)">
                    <Input type="number" step={0.1} min={0.1} max={10} value={hgTpPct} onChange={(e) => setHgTpPct(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Hard stop (% of total capital)">
                    <Input type="number" step={0.1} min={0.1} max={20} value={hgSlPct} onChange={(e) => setHgSlPct(Number(e.target.value))} />
                  </FormField>
                </div>
              </CollapsibleSection>
            </div>

            <Button className="mt-4" onClick={() => runHgMutation.mutate()} disabled={runHgMutation.isPending || bg.runInBackground}>
              {runHgMutation.isPending
                ? `Building ${hgPicker.tickers.length || ''}…`
                : `🛡️ Build Hedge${hgPicker.tickers.length ? ` (${hgPicker.tickers.length})` : ''}`}
            </Button>
            <OptionsBackgroundControls
              bg={bg}
              placeholder={`Hedging · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(
                {
                  tickers: hgPicker.tickers,
                  asset_class: hgAssetClass,
                  dte: hgDte,
                  hedge_distance_pct: hedgeDistancePct,
                  zone_timeframe: zoneTf,
                  zone_fallback_timeframe: zoneFallbackTf,
                  total_capital: totalCapital,
                  profit_target_pct_of_capital: hgTpPct / 100,
                  max_loss_pct_of_capital: hgSlPct / 100,
                },
                () => (!hgPicker.tickers.length ? 'Select at least one ticker' : null),
              )}
            />
            {hgError && <div className="mt-3"><Alert type="error">{hgError}</Alert></div>}
          </Card>

          <OptionsBackgroundJobsAndReports bg={bg} />

          {runHgMutation.isPending && <Loading message="Building Hedging setup…" />}

          {showHgResults && (
            <Card>
              {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
                <p className="mb-3 text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
                </p>
              )}
              <StrategyDataSourceBar data={(hgData ?? undefined) as Record<string, unknown> | undefined} assetClass="india" />
              <HedgingPanel
                data={hgData!} totalCapital={totalCapital}
                profitTargetPctOfCapital={hgTpPct / 100} maxLossPctOfCapital={hgSlPct / 100}
              />
            </Card>
          )}

          {hgAskContext && showHgResults && (
            <AskAIPanel context={hgAskContext} section="options/hedging" />
          )}
        </div>
      )}

      {section === 'gokul_chhabra' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            3-minute VWAP · VWMA(20) · SuperTrend(10,3) alignment on Nifty / Bank Nifty — buy ITM calls/puts
            (delta 0.60–0.75) after 09:45 IST. Flat by 15:15. No BTST.
          </p>

          <CollapsibleSection title="📖 How Gokul Chhabra option buying works" copyText={GOKUL_EXPLANATION}>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-400">{GOKUL_EXPLANATION}</p>
          </CollapsibleSection>

          <Card>
            <div className="rounded-lg border border-slate-700/80 bg-slate-900/50 px-4 py-3">
              <p className="text-sm font-medium text-slate-200">Fixed universe — India index options</p>
              <p className="mt-1 text-xs text-slate-400">
                Always scans <span className="text-slate-300">Nifty 50 · Bank Nifty</span> (futures proxied via index OHLC).
                No Crypto / US ticker picker for this strategy.
              </p>
            </div>

            <div className="mt-4">
              <CollapsibleSection title="⚙️ Parameters">
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="VWMA length">
                    <Input type="number" min={5} max={50} value={vwmaLen} onChange={(e) => setVwmaLen(Number(e.target.value))} />
                  </FormField>
                  <FormField label="SuperTrend length">
                    <Input type="number" min={5} max={30} value={stPeriod} onChange={(e) => setStPeriod(Number(e.target.value))} />
                  </FormField>
                  <FormField label="SuperTrend multiplier">
                    <Input type="number" step={0.5} min={1} max={6} value={stMult} onChange={(e) => setStMult(Number(e.target.value))} />
                  </FormField>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="Min R:R target">
                    <Input type="number" step={0.5} min={1} max={5} value={minRr} onChange={(e) => setMinRr(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Delta min">
                    <Input type="number" step={0.01} min={0.4} max={0.9} value={deltaLo} onChange={(e) => setDeltaLo(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Delta max">
                    <Input type="number" step={0.01} min={0.4} max={0.9} value={deltaHi} onChange={(e) => setDeltaHi(Number(e.target.value))} />
                  </FormField>
                </div>
              </CollapsibleSection>
            </div>

            <Button className="mt-4" onClick={() => runGkMutation.mutate()} disabled={runGkMutation.isPending || bg.runInBackground}>
              {runGkMutation.isPending ? 'Scanning…' : '🔍 Scan Gokul Chhabra setups'}
            </Button>
            <OptionsBackgroundControls
              bg={bg}
              placeholder={`Gokul Chhabra · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground({
                tickers: ['Nifty 50', 'Bank Nifty'],
                vwma_length: vwmaLen,
                st_period: stPeriod,
                st_multiplier: stMult,
                min_rr: minRr,
                target_delta_min: deltaLo,
                target_delta_max: deltaHi,
              })}
            />
            {gkError && <div className="mt-3"><Alert type="error">{gkError}</Alert></div>}
          </Card>

          <OptionsBackgroundJobsAndReports bg={bg} />

          {runGkMutation.isPending && <Loading message="Scanning 3m VWAP / VWMA / SuperTrend setups…" />}

          {showGkResults && (
            <Card>
              {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
                <p className="mb-3 text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
                </p>
              )}
              <StrategyDataSourceBar data={(gkData ?? undefined) as Record<string, unknown> | undefined} assetClass="india" />
              <GokulChhabraPanel data={gkData!} />
            </Card>
          )}

          {gkAskContext && showGkResults && (
            <AskAIPanel context={gkAskContext} section="options/gokul_chhabra" />
          )}
        </div>
      )}

      {section === 'zero_to_hero' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Previous day's high/low sets the bias on a 15-minute chart — buy-side above the high, sell-side
            below the low, no trades in between. Enter on a pullback-and-reversal-through-open, book ~55% at
            1:1, let the rest ride uncapped to 15:15 IST.
          </p>

          <CollapsibleSection title="📖 How Zero to Hero works" copyText={ZERO_TO_HERO_EXPLANATION}>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-400">{ZERO_TO_HERO_EXPLANATION}</p>
          </CollapsibleSection>

          <Card>
            <div className="rounded-lg border border-slate-700/80 bg-slate-900/50 px-4 py-3">
              <p className="text-sm font-medium text-slate-200">Fixed universe — India index options</p>
              <p className="mt-1 text-xs text-slate-400">
                Always scans <span className="text-slate-300">Nifty 50 · Bank Nifty</span> (futures proxied via index OHLC).
                No Crypto / US ticker picker for this strategy.
              </p>
            </div>

            <div className="mt-4">
              <CollapsibleSection title="⚙️ Parameters">
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="Execution timeframe">
                    <select
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                      value={zthTf}
                      onChange={(e) => setZthTf(e.target.value)}
                    >
                      <option value="5m">5 minutes</option>
                      <option value="15m">15 minutes</option>
                      <option value="30m">30 minutes</option>
                    </select>
                  </FormField>
                  <FormField label="Max pullback candles (3-candle rule)">
                    <Input type="number" min={2} max={5} value={zthMaxPullback} onChange={(e) => setZthMaxPullback(Number(e.target.value))} />
                  </FormField>
                  <FormField label="SL buffer beyond entry candle (%)">
                    <Input type="number" step={0.01} min={0} max={1} value={zthSlBuffer} onChange={(e) => setZthSlBuffer(Number(e.target.value))} />
                  </FormField>
                </div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <FormField label="Partial book at R:R">
                    <Input type="number" step={0.25} min={0.5} max={2} value={zthPartialRr} onChange={(e) => setZthPartialRr(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Partial book size (%)">
                    <Input type="number" min={10} max={100} value={zthPartialPct} onChange={(e) => setZthPartialPct(Number(e.target.value))} />
                  </FormField>
                  <FormField label="Flat / let-it-ride-until (IST)">
                    <Input value={zthSessionEnd} onChange={(e) => setZthSessionEnd(e.target.value)} />
                  </FormField>
                </div>
              </CollapsibleSection>
            </div>

            <Button className="mt-4" onClick={() => runZthMutation.mutate()} disabled={runZthMutation.isPending || bg.runInBackground}>
              {runZthMutation.isPending ? 'Scanning…' : '🔍 Scan Zero to Hero setups'}
            </Button>
            <OptionsBackgroundControls
              bg={bg}
              placeholder={`Zero to Hero · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground({
                tickers: ['Nifty 50', 'Bank Nifty'],
                execution_tf: zthTf,
                sl_buffer_pct: zthSlBuffer,
                max_pullback_candles: zthMaxPullback,
                partial_book_rr: zthPartialRr,
                partial_book_pct: zthPartialPct,
                session_end: zthSessionEnd,
              })}
            />
            {zthError && <div className="mt-3"><Alert type="error">{zthError}</Alert></div>}
          </Card>

          <OptionsBackgroundJobsAndReports bg={bg} />

          {runZthMutation.isPending && <Loading message="Scanning previous-day-range pullback setups…" />}

          {showZthResults && (
            <Card>
              {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
                <p className="mb-3 text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
                </p>
              )}
              <StrategyDataSourceBar data={(zthData ?? undefined) as Record<string, unknown> | undefined} assetClass="india" />
              <ZeroToHeroPanel data={zthData!} />
            </Card>
          )}

          {zthAskContext && showZthResults && (
            <AskAIPanel context={zthAskContext} section="options/zero_to_hero" />
          )}
        </div>
      )}

      {section === 'market_prediction' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Is today's move backed by real conviction in the derivatives data, or is it hollow? Combines
            synthetic futures premium/discount, OI buildup, IV skew, India VIX, a late-session move check, and
            FII/DII flow into one divergence read.
          </p>

          <CollapsibleSection title="📖 How Market Prediction works" copyText={MARKET_PREDICTION_EXPLANATION}>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-400">{MARKET_PREDICTION_EXPLANATION}</p>
          </CollapsibleSection>

          <Card>
            <div className="mb-3 flex flex-wrap gap-2">
              <Chip selected={mpMode === 'index'} onClick={() => setMpMode('index')}>Index</Chip>
              <Chip selected={mpMode === 'stock'} onClick={() => { setMpMode('stock'); setMpSuggestOpen(true) }}>Stock</Chip>
            </div>

            {mpMode === 'index' ? (
              <FormField label="Index">
                <select
                  className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                  value={mpSymbol}
                  onChange={(e) => setMpSymbol(e.target.value)}
                >
                  <option value="NIFTY">Nifty 50</option>
                  <option value="BANKNIFTY">Bank Nifty</option>
                  <option value="FINNIFTY">Nifty Financial Services</option>
                  <option value="MIDCPNIFTY">Nifty Midcap Select</option>
                  <option value="NIFTYNXT50">Nifty Next 50</option>
                </select>
                <p className="mt-1.5 text-xs text-slate-500">
                  These 5 are the indices NSE currently lists F&amp;O contracts for (verified live against NSE's own
                  data — same source as nseindia.com/option-chain). BSE's Sensex/Bankex aren't available: this app
                  has no working options-chain data source for them (BSE's own API and Groww's API both return
                  nothing for BSE index derivatives — tested live, not assumed).
                </p>
              </FormField>
            ) : (
              <FormField label="Stock (India, NSE)">
                <div className="relative">
                  <Input
                    value={mpStockTicker}
                    onChange={(e) => { setMpStockTicker(e.target.value.toUpperCase()); setMpSuggestOpen(true) }}
                    onFocus={() => setMpSuggestOpen(true)}
                    onBlur={() => setTimeout(() => setMpSuggestOpen(false), 120)}
                    placeholder="e.g. RELIANCE"
                    autoComplete="off"
                  />
                  {mpSuggestOpen && mpStockDebounced.length >= 1 && (mpSuggestions.length > 0 || mpSuggestQuery.isFetching) && (
                    <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-slate-700/80 bg-slate-900 shadow-lg">
                      {mpSuggestQuery.isFetching && mpSuggestions.length === 0 && (
                        <li className="px-3 py-2 text-xs text-slate-500">Searching…</li>
                      )}
                      {mpSuggestions.map((s) => (
                        <li key={s}>
                          <button
                            type="button"
                            onMouseDown={(e) => { e.preventDefault(); setMpStockTicker(s); setMpSuggestOpen(false) }}
                            className="block w-full px-3 py-1.5 text-left text-sm text-slate-200 hover:bg-slate-800"
                          >
                            {s}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <p className="mt-1.5 text-xs text-slate-500">
                  Only stocks with listed F&amp;O contracts have a usable options chain — most large/liquid NSE
                  names do. If a ticker has no options chain, the run will report that clearly rather than guessing.
                </p>
              </FormField>
            )}

            {mpMode === 'stock' && (
              <div className="mt-4">
                <FormField label="Optional further analysis (confidence boost/penalty on the BUY/SELL trade idea)">
                  <div className="flex flex-wrap gap-2">
                    {MARKET_PREDICTION_FURTHER_ANALYSIS_OPTIONS.map((opt) => {
                      const checked = mpFurtherAnalysis.includes(opt.id)
                      return (
                        <label
                          key={opt.id}
                          className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${
                            checked
                              ? 'border-teal-500/60 bg-teal-500/10 text-teal-300'
                              : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'
                          }`}
                        >
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-800 text-teal-500"
                            checked={checked}
                            onChange={(e) =>
                              setMpFurtherAnalysis((prev) =>
                                e.target.checked ? [...prev, opt.id] : prev.filter((id) => id !== opt.id),
                              )
                            }
                          />
                          {opt.label}
                        </label>
                      )
                    })}
                  </div>
                  <span className="mt-1 block text-xs text-slate-500">
                    Each checked engine runs its own live read on this stock and nudges the trade idea's
                    confidence up or down based on whether it agrees — extra confirmation, not a new filter.
                  </span>
                </FormField>
              </div>
            )}

            <div className="mt-4">
              <CollapsibleSection title="⚙️ Optional — your own futures / FII data (real numbers, if you have them)">
                <div className="grid gap-4 sm:grid-cols-2">
                  <FormField label="Today's NSE futures LTP (optional)">
                    <Input
                      type="number" step={0.05} placeholder="Leave blank to use options-implied synthetic futures"
                      value={mpFuturesPrice} onChange={(e) => setMpFuturesPrice(e.target.value)}
                    />
                  </FormField>
                  <FormField label="FII index derivative positions cut today? (optional)">
                    <select
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                      value={mpFiiCut}
                      onChange={(e) => setMpFiiCut(e.target.value as typeof mpFiiCut)}
                    >
                      <option value="unset">Unknown / not entering</option>
                      <option value="yes">Yes — being cut</option>
                      <option value="no">No — not being cut</option>
                    </select>
                  </FormField>
                </div>
              </CollapsibleSection>
            </div>

            <Button className="mt-4" onClick={() => runMpMutation.mutate()} disabled={runMpMutation.isPending || !mpActiveSymbol || bg.runInBackground}>
              {runMpMutation.isPending ? 'Analyzing…' : `🔮 Run Market Prediction (${mpActiveSymbol || '…'})`}
            </Button>
            <OptionsBackgroundControls
              bg={bg}
              placeholder={`Market Prediction · ${mpActiveSymbol || 'NIFTY'} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(
                {
                  symbol: mpActiveSymbol,
                  is_index: mpMode === 'index',
                  futures_price: mpFuturesPrice.trim() ? Number(mpFuturesPrice) : undefined,
                  fii_index_position_cut: mpFiiCut === 'unset' ? undefined : mpFiiCut === 'yes',
                  further_analysis: mpMode === 'stock' && mpFurtherAnalysis.length ? mpFurtherAnalysis : undefined,
                },
                () => (!mpActiveSymbol ? 'Select an index or stock symbol' : null),
              )}
            />
            {mpError && <div className="mt-3"><Alert type="error">{mpError}</Alert></div>}
          </Card>

          <OptionsBackgroundJobsAndReports bg={bg} />

          {runMpMutation.isPending && <Loading message="Fetching option chain, VIX, and intraday data…" />}

          {showMpResults && (
            <Card>
              {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
                <p className="mb-3 text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
                </p>
              )}
              <StrategyDataSourceBar data={(mpData ?? undefined) as Record<string, unknown> | undefined} assetClass="india" />
              <MarketPredictionPanel data={mpData!} />
            </Card>
          )}

          {mpAskContext && showMpResults && (
            <AskAIPanel context={mpAskContext} section="options/market_prediction" />
          )}
        </div>
      )}

      {section === 'call_put_writing' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Map Call writing resistance walls and Put writing support floors from live OI — and flag
            short-covering risk if the Call wall is tested or broken.
          </p>

          <CollapsibleSection title="📖 How Call Put Writing works" copyText={CALL_PUT_WRITING_EXPLANATION}>
            <p className="whitespace-pre-line text-xs leading-relaxed text-slate-400">{CALL_PUT_WRITING_EXPLANATION}</p>
          </CollapsibleSection>

          <Card>
            <div className="mb-3 flex flex-wrap gap-2">
              <Chip selected={cpwMode === 'index'} onClick={() => setCpwMode('index')}>Index</Chip>
              <Chip selected={cpwMode === 'stock'} onClick={() => { setCpwMode('stock'); setCpwSuggestOpen(true) }}>Stock</Chip>
            </div>

            {cpwMode === 'index' ? (
              <FormField label="Index">
                <select
                  className="w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100"
                  value={cpwSymbol}
                  onChange={(e) => setCpwSymbol(e.target.value)}
                >
                  <option value="NIFTY">Nifty 50</option>
                  <option value="BANKNIFTY">Bank Nifty</option>
                  <option value="FINNIFTY">Nifty Financial Services</option>
                  <option value="MIDCPNIFTY">Nifty Midcap Select</option>
                  <option value="NIFTYNXT50">Nifty Next 50</option>
                </select>
              </FormField>
            ) : (
              <FormField label="Stock (India, NSE)">
                <div className="relative">
                  <Input
                    value={cpwStockTicker}
                    onChange={(e) => { setCpwStockTicker(e.target.value.toUpperCase()); setCpwSuggestOpen(true) }}
                    onFocus={() => setCpwSuggestOpen(true)}
                    onBlur={() => setTimeout(() => setCpwSuggestOpen(false), 120)}
                    placeholder="e.g. RELIANCE"
                    autoComplete="off"
                  />
                  {cpwSuggestOpen && cpwStockDebounced.length >= 1 && (cpwSuggestions.length > 0 || cpwSuggestQuery.isFetching) && (
                    <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-slate-700/80 bg-slate-900 shadow-lg">
                      {cpwSuggestQuery.isFetching && cpwSuggestions.length === 0 && (
                        <li className="px-3 py-2 text-xs text-slate-500">Searching…</li>
                      )}
                      {cpwSuggestions.map((s) => (
                        <li key={s}>
                          <button
                            type="button"
                            onMouseDown={(e) => { e.preventDefault(); setCpwStockTicker(s); setCpwSuggestOpen(false) }}
                            className="block w-full px-3 py-1.5 text-left text-sm text-slate-200 hover:bg-slate-800"
                          >
                            {s}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </FormField>
            )}

            <Button className="mt-4" onClick={() => runCpwMutation.mutate()} disabled={runCpwMutation.isPending || !cpwActiveSymbol || bg.runInBackground}>
              {runCpwMutation.isPending ? 'Analyzing…' : `✍️ Run Call Put Writing (${cpwActiveSymbol || '…'})`}
            </Button>
            <OptionsBackgroundControls
              bg={bg}
              placeholder={`Call Put Writing · ${cpwActiveSymbol || 'NIFTY'} · ${new Date().toLocaleDateString()}`}
              onStart={() => bg.startBackground(
                {
                  symbol: cpwActiveSymbol,
                  is_index: cpwMode === 'index',
                },
                () => (!cpwActiveSymbol ? 'Select an index or stock symbol' : null),
              )}
            />
            {cpwError && <div className="mt-3"><Alert type="error">{cpwError}</Alert></div>}
          </Card>

          <OptionsBackgroundJobsAndReports bg={bg} />

          {runCpwMutation.isPending && <Loading message="Fetching option chain OI walls…" />}

          {showCpwResults && (
            <Card>
              {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
                <p className="mb-3 text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
                </p>
              )}
              <StrategyDataSourceBar data={(cpwData ?? undefined) as Record<string, unknown> | undefined} assetClass="india" />
              <CallPutWritingPanel data={cpwData!} />
            </Card>
          )}

          {cpwAskContext && showCpwResults && (
            <AskAIPanel context={cpwAskContext} section="options/call_put_writing" />
          )}
        </div>
      )}
    </div>
  )
}
