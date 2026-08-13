import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Trash2 } from 'lucide-react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import {
  apiErrorMessage,
  deleteBtstReport,
  fetchBtstJob,
  fetchBtstJobs,
  fetchBtstReport,
  fetchBtstReports,
  runProTradeBbMeanReversion,
  runProTradeTrafficLight,
  runProTradeBuyLowSellHigh,
  runProTradeRlbBreakout,
  runProTradeThreeInOne,
  runProTradeSimpleEffective,
  runProTradeBbRsiVol,
  runProTradeEma9Cross,
  runProTradeEma5Cross,
  runProTradeEma59Cross,
  runProTradeFlatRetest,
  runProTradeBtst,
  runProTradeElliottWave,
  runProTradeFibonacciPro,
  runProTradePaVolumeProfile,
  runProTradePaVpSmc,
  runProTradeVolumeProfileCe,
  runProTradeVolumeProfilePoc,
  runProTradeVolumeSpreadNextCandle,
  saveBtstReport,
  startBtstJob,
} from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../components/analysis/AnalysisBackground'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { BbMeanReversionPanel } from '../components/pro-trade/BbMeanReversionPanel'
import { TrafficLightIndicatorPanel } from '../components/pro-trade/TrafficLightIndicatorPanel'
import { BuyLowSellHighPanel } from '../components/pro-trade/BuyLowSellHighPanel'
import { RlbBreakoutPanel } from '../components/pro-trade/RlbBreakoutPanel'
import { ThreeInOneTradeSystemPanel } from '../components/pro-trade/ThreeInOneTradeSystemPanel'
import { SimpleEffectivePanel } from '../components/pro-trade/SimpleEffectivePanel'
import { BbRsiVolPanel } from '../components/pro-trade/BbRsiVolPanel'
import { Ema9CrossPanel, Ema5CrossPanel, Ema59CrossPanel } from '../components/pro-trade/Ema9CrossPanel'
import { FlatRetestPanel } from '../components/pro-trade/FlatRetestPanel'
import { BtstPanel } from '../components/pro-trade/BtstPanel'
import { ChartsToggle } from '../components/pro-trade/ChartsToggle'
import { UseAiCheckbox, useTradeSetupAi } from '../components/pro-trade/UseAiCheckbox'
import { StrategyDataSourceBar } from '../components/ui/StrategyDataSourceBar'
import { ElliottWavePanel } from '../components/pro-trade/ElliottWavePanel'
import { FibonacciProPanel } from '../components/pro-trade/FibonacciProPanel'
import { PaVolumeProfilePanel } from '../components/pro-trade/PaVolumeProfilePanel'
import { PaVpSmcPanel } from '../components/pro-trade/PaVpSmcPanel'
import { TickerChartPage } from '../components/pro-trade/TickerChartPanel'
import { VolumeProfileCePanel } from '../components/pro-trade/VolumeProfileCePanel'
import { VolumeProfilePocPanel } from '../components/pro-trade/VolumeProfilePocPanel'
import { VolumeSpreadNextCandlePanel } from '../components/pro-trade/VolumeSpreadNextCandlePanel'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

const YOUTUBE = 'https://youtu.be/67u8mdQ8f08'
const CE_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1wk'] as const
const POC_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1wk'] as const
const PA_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1wk'] as const
const SMC_HTF_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1w'] as const
const SMC_LTF_TFS = ['1m', '3m', '5m', '15m', '30m', '1h', '4h'] as const
const VSA_TFS = ['5m', '15m', '30m', '1h', '4h', '1d'] as const
const EW_TFS = ['15m', '30m', '1h', '4h', '1d', '1wk'] as const
const BB_EXTRA_CHECK_OPTIONS: { value: string; label: string }[] = [
  { value: 'fibonacci', label: 'Fibonacci retracement' },
  { value: 'ema_position', label: 'EMA position (20/50 stack)' },
  { value: 'ema_crossover', label: 'EMA crossover (9/21)' },
  { value: 'stochastic_rsi', label: 'Stochastic RSI' },
  { value: 'vwap', label: 'VWAP' },
  { value: 'volume_profile', label: 'Volume Profile (POC/VAH/VAL)' },
  { value: 'smart_money', label: 'Smart Money (Order Blocks)' },
  { value: 'reversal_strategy', label: 'Reversal strategy (chart pattern + divergence)' },
  { value: 'macd', label: 'MACD' },
  { value: 'support_resistance', label: 'Support & Resistance zone' },
  { value: 'trend_direction_strength', label: 'Trend direction & strength (ADX)' },
  { value: 'mtf_trend_strength', label: 'MTF Trend & Strength' },
  { value: 'candlestick_chart_patterns', label: 'Candlestick & Chart Patterns' },
]
const ASSET_CLASSES: { id: AssetClass; label: string }[] = [
  { id: 'india', label: 'India' },
  { id: 'us', label: 'US' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'commodity', label: 'Commodities' },
]

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: ['15m'] }

const OVERVIEW = `How Professional Traders Make Crores Using Volume Profiles — Abhishek Kar masterclass
${YOUTUBE}

Volume Profile maps traded volume across price (not time). Core levels:
• POC (Point of Control) — price with the most volume (magnetic / fair value)
• VAH / VAL (Value Area High / Low) — bounds of the ~70% volume "color zone"
• LVN / 'I' profile — thin volume gaps that price often slices through quickly

This scanner builds a session Volume Profile from your intraday bars, tracks multi-day POC compression on daily closes, and surfaces three setups plus synthetic-futures execution hints.

Research / education only — not financial advice.`

const STRAT1 = `Strategy 1 — Value Area Reversal (intraday / short-term)

1. Let the session open and form a Value Area (heavy volume "color zone"; ignore thin extremes).
2. Wait for price to tag VAL (long) or VAH (short). Do not enter blindly.
3. Require price-action confirmation: hammer / pin bar / doji at VAL (bullish), or shooting star at VAH (bearish).
4. Stop: just beyond the rejection wick (below VAL for longs, above VAH for shorts).
5. Targets: T1 = POC (often consolidates), T2 = opposite edge of the value area (VAH for longs / VAL for shorts).

Scanner: last closed intraday bar near VAL/VAH within tolerance + hammer/shooting-star geometry.`

const STRAT2 = `Strategy 2 — POC Compression Breakout (stocks & indices)

1. Spot several consecutive days where daily POCs (here proxied by daily closes + today's session POC) sit in a tight band (e.g. ~0.2% — roughly 10–20 Nifty points near 20k).
2. Merge that band into one magnetic support/resistance zone.
3. Trade only a decisive breakout above or breakdown below the merged zone — moves are often fast and one-sided.
4. Pro tip: avoid naked option buying while compressed (theta decay). Prefer synthetic futures.

Scanner: compression_days POC span ≤ threshold → WATCH; price outside zone → BREAKOUT_BUY / BREAKDOWN_SELL.`

const STRAT3 = `Strategy 3 — 'I' Profile / Liquidity Void (LVN)

1. An 'I' profile appears after a sharp gap / runaway move that leaves Low Volume Nodes (almost no traded volume).
2. Those zones have little trapped inventory → liquidity voids.
3. When price re-enters an LVN (often after leaving compression), it tends to traverse the void quickly.
4. Trade the slice: enter near the near edge of the void, target the far edge; keep a tight invalidation stop.

Scanner: bins with volume < lvn_threshold × max bin volume; signal when price sits on the entering edge.`

const RULES = `Risk & execution rules from the masterclass

• Never swing trade naked — always hedge overnight. Black swans will eventually hit.
• Synthetic futures: LONG = buy ATM CE + sell ATM PE; SHORT = buy ATM PE + sell ATM CE (same expiry). Capital-efficient futures proxy.
• For directional Volume Profile bounces (VAL/POC), prefer ITM options — they track the level better than OTM lottery tickets.
• POC compression → synthetic futures, not premium buying while you wait.

Heuristic scanner — not a fill guarantee.`

function VolumeProfileCePage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [error, setError] = useState('')
  const [numBins, setNumBins] = useState(50)
  const [valueAreaPct, setValueAreaPct] = useState(70)
  const [compressionDays, setCompressionDays] = useState(3)
  const [compressionPct, setCompressionPct] = useState(0.2)
  const [valTol, setValTol] = useState(0.15)
  const [lvnPct, setLvnPct] = useState(10)
  const [intradayTf, setIntradayTf] = useState('15m')
  const [showCharts, setShowCharts] = useState(false)
  const bg = useAnalysisBackground('pro_trade', 'volume_profile_ce')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    intraday_tf: intradayTf,
    daily_tf: '1d',
    num_bins: numBins,
    value_area_pct: valueAreaPct / 100,
    compression_days: compressionDays,
    compression_threshold_pct: compressionPct,
    val_touch_tol_pct: valTol,
    lvn_threshold_pct: lvnPct / 100,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeVolumeProfileCe(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Volume Profile CE', data) : ''

  return (
    <div>
      <PageHeader
        title="Volume Profile CE"
        description="Value Area Reversal · POC Compression · I-Profile LVN · synthetic futures hints"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="Overview & source video" defaultOpen>
          {OVERVIEW}
          <p className="mt-3">
            <a
              href={YOUTUBE}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-blue-400 hover:underline"
            >
              Watch masterclass <ExternalLink size={12} />
            </a>
          </p>
        </CollapsibleSection>
        <CollapsibleSection title="Strategy 1 — Value Area Reversal">{STRAT1}</CollapsibleSection>
        <CollapsibleSection title="Strategy 2 — POC Compression Breakout">{STRAT2}</CollapsibleSection>
        <CollapsibleSection title="Strategy 3 — I-Profile / Liquidity Void">{STRAT3}</CollapsibleSection>
        <CollapsibleSection title="Risk management & synthetic futures">{RULES}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker(DEFAULT_PICKER)
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Chart TF (session VP)">
            <Select value={intradayTf} onChange={(e) => setIntradayTf(e.target.value)}>
              {CE_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="VP bins">
            <Input type="number" value={numBins} onChange={(e) => setNumBins(Number(e.target.value) || 50)} />
          </FormField>
          <FormField label="Value area %">
            <Input type="number" value={valueAreaPct} onChange={(e) => setValueAreaPct(Number(e.target.value) || 70)} />
          </FormField>
          <FormField label="Compression days">
            <Input
              type="number"
              value={compressionDays}
              onChange={(e) => setCompressionDays(Number(e.target.value) || 3)}
            />
          </FormField>
          <FormField label="POC compression max span %">
            <Input
              type="number"
              step="0.05"
              value={compressionPct}
              onChange={(e) => setCompressionPct(Number(e.target.value) || 0.2)}
            />
          </FormField>
          <FormField label="VAL/VAH touch tol %">
            <Input type="number" step="0.05" value={valTol} onChange={(e) => setValTol(Number(e.target.value) || 0.15)} />
          </FormField>
          <FormField label="LVN volume threshold % of max">
            <Input type="number" value={lvnPct} onChange={(e) => setLvnPct(Number(e.target.value) || 10)} />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan Volume Profile (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Volume Profile CE · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => (!picker.tickers.length ? 'Select at least one ticker' : null))}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Building session Volume Profiles and scoring setups…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <VolumeProfileCePanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/volume-profile-ce" />}
        </>
      )}
    </div>
  )
}

const POC_YOUTUBE = 'https://www.youtube.com/watch?v=ooHX6tf5RVI'

const POC_OVERVIEW = `How to MASTER Volume Profile Trading — AKTV
${POC_YOUTUBE}

Traditional volume shows activity over time. Volume Profile shows volume at price.
• POC — red center / peak volume level; acts like a price magnet
• High Volume Node (HVN) — thick cluster around POC that institutions defend
• Low Volume Node (LVN) — thin areas ideal for parking stop losses

This scanner builds a lookback Volume Profile, finds the HVN zone edges, then looks for a breakout followed by the FIRST retest of the zone edge (not later touches).

Research / education only — not financial advice.`

const POC_FIRST_TOUCH = `The "First Touch" entry

1. Identify the POC / widest volume histogram bars (HVN cluster).
2. Wait for price to break out and move away from this zone.
3. Enter on the very first pullback/retest of the zone edge (buy after upside breakout; short after downside breakdown).
4. Do NOT trade subsequent retests — the level weakens after the first bounce.

Scanner waits for close beyond the zone by breakout_buffer_pct, then triggers on the first bar that tags the zone edge.`

const POC_ZONE_EDGE = `Zone Edge pro tip

Retail often waits for an exact touch of the POC center line and misses the move.
Treat the high-volume cluster as a thick zone and enter at the outer boundary (zone upper for longs after breakout, zone lower for shorts after breakdown). Price often reverses at the edge before reaching the exact POC.`

const POC_RISK = `Risk management

• Stop loss: place in an LVN behind the HVN barrier (below zone for longs, above for shorts) so price has to chew through heavy volume to stop you out.
• Take profit: just before the next heavy volume zone on the chart — book before colliding with the next institutional shelf.

Heuristic scanner — not a fill guarantee.`

function VolumeProfilePocPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [error, setError] = useState('')
  const [timeframe, setTimeframe] = useState('1d')
  const [lookback, setLookback] = useState(120)
  const [profileBars, setProfileBars] = useState(60)
  const [numBins, setNumBins] = useState(40)
  const [clusterPct, setClusterPct] = useState(70)
  const [breakoutBuf, setBreakoutBuf] = useState(1)
  const [showCharts, setShowCharts] = useState(false)
  const bg = useAnalysisBackground('pro_trade', 'volume_profile_poc')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe,
    lookback_bars: lookback,
    profile_bars: profileBars,
    num_bins: numBins,
    cluster_vol_pct: clusterPct / 100,
    breakout_buffer_pct: breakoutBuf,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeVolumeProfilePoc(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Volume Profile POC', data) : ''

  return (
    <div>
      <PageHeader
        title="Volume Profile POC"
        description="First-touch pullback to HVN zone edge · LVN stops · next-HVN targets"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="Overview & source video" defaultOpen>
          {POC_OVERVIEW}
          <p className="mt-3">
            <a
              href={POC_YOUTUBE}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-blue-400 hover:underline"
            >
              Watch masterclass <ExternalLink size={12} />
            </a>
          </p>
        </CollapsibleSection>
        <CollapsibleSection title="First Touch entry strategy">{POC_FIRST_TOUCH}</CollapsibleSection>
        <CollapsibleSection title="Zone Edge trick">{POC_ZONE_EDGE}</CollapsibleSection>
        <CollapsibleSection title="Risk management (SL & TP)">{POC_RISK}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['1d'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {POC_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Lookback bars">
            <Input type="number" value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 120)} />
          </FormField>
          <FormField label="Profile bars (build VP)">
            <Input type="number" value={profileBars} onChange={(e) => setProfileBars(Number(e.target.value) || 60)} />
          </FormField>
          <FormField label="VP bins">
            <Input type="number" value={numBins} onChange={(e) => setNumBins(Number(e.target.value) || 40)} />
          </FormField>
          <FormField label="HVN cluster % of POC vol">
            <Input type="number" value={clusterPct} onChange={(e) => setClusterPct(Number(e.target.value) || 70)} />
          </FormField>
          <FormField label="Breakout buffer %">
            <Input
              type="number"
              step="0.1"
              value={breakoutBuf}
              onChange={(e) => setBreakoutBuf(Number(e.target.value) || 1)}
            />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan POC First Touch (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Volume Profile POC · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => (!picker.tickers.length ? 'Select at least one ticker' : null))}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Building Volume Profile POC levels and scanning first-touch…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <VolumeProfilePocPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/volume-profile-poc" />}
        </>
      )}
    </div>
  )
}

const PA_YOUTUBE = 'https://www.youtube.com/watch?v=FVoXWlNkdhs'

const PA_OVERVIEW = `Filter Price Action with Volume Profile — Trader Dale
${PA_YOUTUBE}

Goal: only take simple PA setups when big institutional volume aligns with your price level.

Two setups:
• Fair Value Gap (FVG) + Volume Profile cluster at/behind the gap entry edge
• Support/Resistance flip + volume cluster at the breakout — trade the FIRST retest only

Research / education only — not financial advice.`

const PA_FVG = `Setup 1 — Fair Value Gap + Volume Profile

Price action: look for a 3-candle Fair Value Gap.
• Bullish FVG: gap between High of Candle 1 and Low of Candle 3
• Bearish FVG: gap between Low of Candle 1 and High of Candle 3

Entry: wait for a pullback to the beginning of the gap (High of Candle 1 for bullish; Low of Candle 1 for bearish).

Volume Profile filter: draw a fixed-range VP over the consolidation/rotation just before the FVG.
Trigger: a heavy volume cluster (POC / HVN) must overlap or sit just behind the FVG entry edge — institutions built there before pushing price.

Scanner: detects strict 3-candle FVGs, builds VP on the prior vp_lookback bars, and flags confluence when POC is within poc_tolerance_pct of the entry edge.`

const PA_SR = `Setup 2 — Support/Resistance Flip + Volume Profile

Price action: a strong support breaks and flips to resistance (or resistance flips to support).

Volume Profile filter: look at the VP where the breakout occurred — there must be a significant volume cluster exactly at the breakout point (institutions spent volume to break the level and will likely defend the retest).

Rule: trade only the FIRST retest. Later touches are weaker.

Scanner: finds pivot S/R, requires a close beyond the level with breakout_buffer_pct, checks VP cluster near the break, then signals on the first retest touch.`

const PA_RISK = `Rules of engagement

• Skip PA setups that lack a backing volume cluster — no institutional footprint, no trade.
• FVG: limit at the gap start; invalidate if price closes through the far side of the gap without reacting.
• S/R flip: first retest only; stop beyond the VP cluster / flipped level.
• Heuristic scanner — not a fill guarantee.`

function PaVolumeProfilePage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [timeframe, setTimeframe] = useState('15m')
  const [lookback, setLookback] = useState(200)
  const [vpLookback, setVpLookback] = useState(40)
  const [numBins, setNumBins] = useState(40)
  const [pocTol, setPocTol] = useState(0.35)
  const [breakoutBuf, setBreakoutBuf] = useState(0.15)
  const [showCharts, setShowCharts] = useState(false)
  const bg = useAnalysisBackground('pro_trade', 'pa_volume_profile')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe,
    lookback_bars: lookback,
    vp_lookback: vpLookback,
    num_bins: numBins,
    poc_tolerance_pct: pocTol,
    breakout_buffer_pct: breakoutBuf,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradePaVolumeProfile(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('PA - Volume Profile', data) : ''

  return (
    <div>
      <PageHeader
        title="PA - Volume Profile"
        description="FVG + VP cluster · S/R flip first retest · institutional volume filter"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="Overview & source video" defaultOpen>
          {PA_OVERVIEW}
          <p className="mt-3">
            <a
              href={PA_YOUTUBE}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-blue-400 hover:underline"
            >
              Watch strategy video <ExternalLink size={12} />
            </a>
          </p>
        </CollapsibleSection>
        <CollapsibleSection title="Setup 1 — FVG + Volume Profile">{PA_FVG}</CollapsibleSection>
        <CollapsibleSection title="Setup 2 — S/R Flip + Volume Profile">{PA_SR}</CollapsibleSection>
        <CollapsibleSection title="Rules of engagement">{PA_RISK}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {PA_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Lookback bars">
            <Input type="number" value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 200)} />
          </FormField>
          <FormField label="VP lookback (pre-FVG / break)">
            <Input type="number" value={vpLookback} onChange={(e) => setVpLookback(Number(e.target.value) || 40)} />
          </FormField>
          <FormField label="VP bins">
            <Input type="number" value={numBins} onChange={(e) => setNumBins(Number(e.target.value) || 40)} />
          </FormField>
          <FormField label="POC↔FVG tolerance %">
            <Input
              type="number"
              step="0.05"
              value={pocTol}
              onChange={(e) => setPocTol(Number(e.target.value) || 0.35)}
            />
          </FormField>
          <FormField label="Breakout buffer %">
            <Input
              type="number"
              step="0.05"
              value={breakoutBuf}
              onChange={(e) => setBreakoutBuf(Number(e.target.value) || 0.15)}
            />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan PA + VP (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`PA Volume Profile · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => (!picker.tickers.length ? 'Select at least one ticker' : null))}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Detecting FVGs, S/R flips, and Volume Profile confluence…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <PaVolumeProfilePanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/pa-volume-profile" />}
        </>
      )}
    </div>
  )
}

const SMC_OVERVIEW = `PA-VP-SMC — the best of everything, combined into one confluence score

Rather than trading Price Action, Volume Profile, or Smart Money Concepts alone, this strategy checks how many
independent, well-known institutional techniques agree at the CURRENT price — and only calls a trade once several
of them stack up together.

Pillars scored, each an independent vote:
• Price Action — higher-timeframe trend (EMA stack), a liquidity sweep (stop-hunt wick through a prior swing
  high/low that closes back inside), and a confirming candlestick reversal pattern on the entry timeframe.
• Volume Profile — the higher-timeframe session POC / VAH / VAL (institutional "fair value" and the edges of
  where most volume traded).
• Smart Money Concepts — unmitigated Order Blocks, a nearby unmitigated Fair Value Gap, and whether price sits
  in the discount (favor longs) or premium (favor shorts) half of its recent range.
• Classic swing Support/Resistance — pure swing-high/swing-low geometry, independent of the above.
• Options execution — a synthetic-futures structure (ATM CE+PE) or an ITM-option note, since a Volume-Profile-
  anchored level reacts better to higher-delta options than OTM lottery tickets.

Research / education only — not financial advice.`

const SMC_HOW = `How the confluence score works

Each pillar that lines up with the same direction adds points to one confidence_pct. A trade only becomes
actionable once at least the configured minimum number of pillars agree (default 3 of 7) — fewer matches shows
as WATCH (a direction is forming but not yet confirmed), zero matches shows as WAIT.

Entry uses the current price; stop-loss anchors to the nearest confluence level (Order Block / swing zone /
sweep level) with an ATR buffer; target prioritizes the next Volume Profile level (POC/VAH/VAL), extended if
needed to hold at least the configured minimum reward:risk.`

const SMC_RULES = `Rules of engagement

• The more pillars agree, the higher the confidence — don't chase a single-pillar WATCH as if it were a full setup.
• Prefer ITM options at these levels; they track a Volume-Profile-anchored level far better than OTM options.
• Synthetic futures (ATM CE bought + ATM PE sold, or the mirror) are shown as a capital-efficient route — always hedge overnight swings.
• Heuristic confluence scanner — not a trained model, not a fill guarantee.`

function PaVpSmcPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [error, setError] = useState('')
  const [htf, setHtf] = useState('1h')
  const [ltf, setLtf] = useState('15m')
  const [lookback, setLookback] = useState(300)
  const [swingWindow, setSwingWindow] = useState(5)
  const [numBins, setNumBins] = useState(50)
  const [valueAreaPct, setValueAreaPct] = useState(70)
  const [zoneTol, setZoneTol] = useState(0.5)
  const [minFactors, setMinFactors] = useState(3)
  const [rrMin, setRrMin] = useState(1.5)
  const [showCharts, setShowCharts] = useState(false)
  const bg = useAnalysisBackground('pro_trade', 'pa_vp_smc')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    htf,
    ltf,
    lookback_bars: lookback,
    swing_window: swingWindow,
    vp_num_bins: numBins,
    vp_value_area_pct: valueAreaPct / 100,
    zone_tolerance_pct: zoneTol,
    min_confluence_factors: minFactors,
    rr_min: rrMin,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradePaVpSmc(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('PA-VP-SMC', data) : ''

  return (
    <div>
      <PageHeader
        title="PA-VP-SMC"
        description="Price Action + Volume Profile + Smart Money Concepts confluence · confidence-scored actionable trades"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="Overview" defaultOpen>
          {SMC_OVERVIEW}
        </CollapsibleSection>
        <CollapsibleSection title="How the confluence score works">{SMC_HOW}</CollapsibleSection>
        <CollapsibleSection title="Rules of engagement">{SMC_RULES}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker(DEFAULT_PICKER)
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="HTF (structure / VP / order blocks)">
            <Select value={htf} onChange={(e) => setHtf(e.target.value)}>
              {SMC_HTF_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="LTF (trigger / sweep / candlestick)">
            <Select value={ltf} onChange={(e) => setLtf(e.target.value)}>
              {SMC_LTF_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Lookback bars">
            <Input type="number" value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 300)} />
          </FormField>
          <FormField label="Swing window">
            <Input type="number" value={swingWindow} onChange={(e) => setSwingWindow(Number(e.target.value) || 5)} />
          </FormField>
          <FormField label="VP bins">
            <Input type="number" value={numBins} onChange={(e) => setNumBins(Number(e.target.value) || 50)} />
          </FormField>
          <FormField label="Value area %">
            <Input type="number" value={valueAreaPct} onChange={(e) => setValueAreaPct(Number(e.target.value) || 70)} />
          </FormField>
          <FormField label="Zone tolerance %">
            <Input type="number" step="0.1" value={zoneTol} onChange={(e) => setZoneTol(Number(e.target.value) || 0.5)} />
          </FormField>
          <FormField label="Min confluence pillars">
            <Input type="number" min={1} max={7} value={minFactors} onChange={(e) => setMinFactors(Number(e.target.value) || 3)} />
          </FormField>
          <FormField label="Min reward:risk">
            <Input type="number" step="0.1" value={rrMin} onChange={(e) => setRrMin(Number(e.target.value) || 1.5)} />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan PA-VP-SMC (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`PA-VP-SMC · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => (!picker.tickers.length ? 'Select at least one ticker' : null))}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Building confluence across Price Action, Volume Profile, and Smart Money Concepts…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <PaVpSmcPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/pa-vp-smc" />}
        </>
      )}
    </div>
  )
}

const VSA_YOUTUBE = 'https://www.youtube.com/watch?v=ncrqXFCQKOU&list=PLXWi52aRZnNF_HW-TedxAE1Tyx1C8XrGn'

const VSA_OVERVIEW = `Volume Spread Analysis (VSA) — Wyckoff smart-money supply & demand
${VSA_YOUTUBE}

VSA reads the relationship between candle **spread** (|Close − Open|) and **volume** to spot where banks/funds are absorbing or dumping.

Volume states:
• Average — near the 20-period volume MA
• Above average — Volume > 20 MA
• Ultra-high — Volume above the prior peak in a ~50-bar window

This scanner flags the four core bars and treats each as a **next-candle** prediction (SOS → expect up; SOW → expect down).

Research / education only — not financial advice.`

const VSA_SOS = `Signs of Strength (bullish — next candle expected up)

• Downthrust — low-spread bullish pin/doji + above-average or ultra-high volume (demand absorbing supply).
• No Supply — low-spread bearish candle with a lower wick + volume lower than the previous two bars (sellers drying up).`

const VSA_SOW = `Signs of Weakness (bearish — next candle expected down)

• Upthrust — low-spread bearish pin/doji + above-average or ultra-high volume (supply overwhelming buyers).
• No Demand — low-spread bullish candle with an upper wick + volume lower than the previous two bars (buyers drying up).`

const VSA_RULES = `Execution

• Actionable TAKE only when a VSA signal prints on the **latest closed bar** (next-candle edge).
• Entry at signal close; stop beyond the signal candle extreme (+ ATR buffer); target at configured R:R.
• Historical setups show whether the following candle confirmed (Win) or failed (Loss) — hit-rate is informational only.
• Heuristic scanner — not a fill guarantee.`

function VolumeSpreadNextCandlePage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [timeframe, setTimeframe] = useState('15m')
  const [lookback, setLookback] = useState(200)
  const [volMa, setVolMa] = useState(20)
  const [ultraLookback, setUltraLookback] = useState(50)
  const [lowSpreadFactor, setLowSpreadFactor] = useState(0.75)
  const [rrRatio, setRrRatio] = useState(1.5)
  const [showCharts, setShowCharts] = useState(false)
  const bg = useAnalysisBackground('pro_trade', 'volume_spread_next_candle')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe,
    lookback_bars: lookback,
    vol_ma_period: volMa,
    ultra_vol_lookback: ultraLookback,
    low_spread_factor: lowSpreadFactor,
    rr_ratio: rrRatio,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeVolumeSpreadNextCandle(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Volume Spread - Next Candle', data) : ''

  return (
    <div>
      <PageHeader
        title="Volume Spread - Next Candle"
        description="VSA Downthrust · No Supply · Upthrust · No Demand — next-candle Wyckoff edge"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="Overview & source video" defaultOpen>
          {VSA_OVERVIEW}
          <p className="mt-3">
            <a
              href={VSA_YOUTUBE}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-blue-400 hover:underline"
            >
              Watch playlist <ExternalLink size={12} />
            </a>
          </p>
        </CollapsibleSection>
        <CollapsibleSection title="Signs of Strength (SOS)">{VSA_SOS}</CollapsibleSection>
        <CollapsibleSection title="Signs of Weakness (SOW)">{VSA_SOW}</CollapsibleSection>
        <CollapsibleSection title="Execution rules">{VSA_RULES}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {VSA_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Lookback bars">
            <Input type="number" value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 200)} />
          </FormField>
          <FormField label="Volume MA period">
            <Input type="number" value={volMa} onChange={(e) => setVolMa(Number(e.target.value) || 20)} />
          </FormField>
          <FormField label="Ultra-high vol lookback">
            <Input
              type="number"
              value={ultraLookback}
              onChange={(e) => setUltraLookback(Number(e.target.value) || 50)}
            />
          </FormField>
          <FormField label="Low-spread factor (× avg)">
            <Input
              type="number"
              step="0.05"
              value={lowSpreadFactor}
              onChange={(e) => setLowSpreadFactor(Number(e.target.value) || 0.75)}
            />
          </FormField>
          <FormField label="Reward : Risk">
            <Input
              type="number"
              step="0.1"
              value={rrRatio}
              onChange={(e) => setRrRatio(Number(e.target.value) || 1.5)}
            />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan VSA Next Candle (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Volume Spread Next Candle · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => (!picker.tickers.length ? 'Select at least one ticker' : null))}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Detecting Volume Spread signals and next-candle setups…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <VolumeSpreadNextCandlePanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/volume-spread-next-candle" />}
        </>
      )}
    </div>
  )
}

const EW_OVERVIEW = `Elliott Wave Analyzer — algorithmic 5-wave impulse / ABC corrective detection

Elliott Wave theory says price moves in a repeating fractal pattern: a 5-wave "impulse" in the direction of the
larger trend, followed by a 3-wave "ABC" correction against it. This scanner runs a ZigZag pivot filter over the
selected timeframe, then checks whether the resulting swings satisfy the strict validation rules for either pattern.

Research / education only — algorithmic wave counts are estimates, not certified Elliott Wave analysis.`

const EW_RULES = `How the count works & rules of engagement

**5-wave impulse** — Wave 3 can never be the shortest of waves 1/3/5; Wave 2 cannot retrace below Wave 1's start;
Wave 4 cannot overlap Wave 1's price territory. Once a valid impulse completes, this app projects Fibonacci
38.2% / 50% / 61.8% retracement targets for the expected ABC correction.

**ABC correction** — Wave B cannot retrace beyond Wave A's start. Once Wave C completes, the correction is
considered done and a resumption of the prior trend is favored.

**ZigZag sensitivity** — lower % = more pivots (noisier, catches smaller waves); higher % = fewer, larger swings.
Tune this per instrument — a volatile stock needs a wider % than a stable index.

Wave connector lines and numbered labels are drawn directly on the chart (candle or line view) so you can see the
exact swing structure the count is built from.`

const EW_LAYMAN = `In plain English — no jargon

Think of price as walking in a repeating rhythm: it takes 5 steps in one direction (a "trend"), then 3 steps back
(a "correction"), then the cycle can repeat. This tool watches a chart, marks each significant zig-zag turn, and
checks whether the last several turns fit that 5-step-then-3-step rhythm.

• **Numbers 1 → 5** on the chart = the trending move. Each number is one leg of that move.
• **Letters A → B → C** = the pullback against the trend that (usually) follows.
• **Colored connector lines** trace the actual price swings the count is based on — follow them in order.
• **Dashed lines** are projected price levels for where the next move might reach, based on common Fibonacci ratios.
• **Green legs** = price rose in that leg. **Red legs** = price fell.

What the pattern label means for you:
- **IMPULSE** — a clean 5-step trend just wrapped up. Expect a pullback (correction) next, not more of the same move.
- **CORRECTIVE** — an A-B-C pullback just wrapped up. Expect the original trend to resume.
- **INCOMPLETE** — the recent swings don't cleanly fit either pattern. There's nothing reliable to act on yet — wait,
  or try a lower ZigZag sensitivity % to catch a cleaner structure.

This is a mechanical estimate, not a certified wave count — treat it as one input among several, not a standalone
signal.`

function ElliottWavePage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [error, setError] = useState('')
  const [timeframe, setTimeframe] = useState('1d')
  const [lookback, setLookback] = useState(250)
  const [zigzagPct, setZigzagPct] = useState(3.0)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [showCharts, setShowCharts] = useState(false)
  const bg = useAnalysisBackground('pro_trade', 'elliott_wave')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe,
    lookback_bars: lookback,
    zigzag_pct: zigzagPct,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeElliottWave(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Elliott Wave', data) : ''

  return (
    <div>
      <PageHeader
        title="Elliott Wave"
        description="ZigZag-filtered 5-wave impulse / ABC corrective detection · wave lines on candle & line chart"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="In plain English — how to interpret your results" defaultOpen>
          {EW_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="Overview">{EW_OVERVIEW}</CollapsibleSection>
        <CollapsibleSection title="How the count works & rules of engagement">{EW_RULES}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['1d'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-3xl gap-3 sm:grid-cols-3">
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {EW_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Candle history">
            <Input
              type="number"
              min={50}
              max={650}
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value) || 250)}
            />
          </FormField>
          <FormField label="ZigZag sensitivity %">
            <Input
              type="number"
              step="0.5"
              min={1}
              max={10}
              value={zigzagPct}
              onChange={(e) => setZigzagPct(Number(e.target.value) || 3.0)}
            />
          </FormField>
        </div>

        <div className="mt-4 grid max-w-3xl gap-3 sm:grid-cols-2">
          <FormField label="From date (optional)">
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </FormField>
          <FormField label="To date (optional)">
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </FormField>
        </div>
        <p className="mt-1.5 text-xs text-slate-500">
          Leave blank to use the most recent Candle History bars. A date range crops that fetched history to the
          window you pick — if it needs more bars than fetched, raise Candle History above.
        </p>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan Elliott Wave (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Elliott Wave · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => (!picker.tickers.length ? 'Select at least one ticker' : null))}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Running ZigZag pivots and validating wave structure…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <ElliottWavePanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/elliott-wave" />}
        </>
      )}
    </div>
  )
}

const FIB_STRATEGIES: { id: string; label: string }[] = [
  { id: 'golden_pocket', label: 'Golden Pocket (50–61.8%)' },
  { id: 'ote_smc', label: 'OTE / SMC (61.8–78.6%)' },
  { id: 'deep_786', label: 'Deep 78.6%' },
  { id: 'extension_ride', label: 'Extension Ride' },
  { id: 'fib_cluster', label: 'Fib Cluster' },
  { id: 'rejection_fade', label: 'Rejection Fade' },
]

const FIB_LAYMAN = `In plain English — how to read your results

Fibonacci levels are just measuring tape on a chart. After a big move (a "swing"), price often pulls back
part of the way before continuing. Traders mark those pullback distances as percentages of the original move —
especially 50% and 61.8% (the "golden pocket"). This scanner checks whether price is sitting in one of those
known zones right now, and whether the bigger trend still agrees.

What you see on each ticker card:
• **BULLISH / BEARISH / NEUTRAL** — the suggested direction (or "wait" if nothing is ready).
• **BUY / SELL badge** — only appears when a setup is considered actionable right now.
• **Confidence %** — how many checks lined up (trend, zone quality, reward:risk). Higher is better; it is not a
  win-rate guarantee.
• **SL % and TP %** — how far the suggested stop-loss and take-profit are from entry, as a % of price. Roughly:
  "risk this much to aim for that much."
• **Reward : Risk (1 : X)** — if X is 2, the target is about twice as far as the stop. Thin ratios are filtered out.
• **Best strategy name** (e.g. Golden Pocket) — which Fib tactic fired for this ticker. Read its "When to use" note.
• **Active Fib setups** — sometimes more than one tactic fires; they are listed with their own SL/TP/confidence.
• **Chart (if Charts is on)** — purple Fib ladder on the swing, plus Entry / SL / TP lines for the best setup.

What NEUTRAL / WAIT means:
Price is not currently sitting in an enabled Fib entry zone with trend confirmation and enough reward:risk.
That is normal most of the time — Fib setups are selective. Wait for price to tag a golden pocket, OTE zone,
78.6%, or extension rather than forcing a trade.

Quick decision guide:
1. Prefer tickers with BUY/SELL + higher confidence %.
2. Read "When to use" — if the market mood doesn't match that note, skip even a green badge.
3. Check SL% vs how much you are willing to lose on one trade; size the position from the stop, not from hope.
4. Use the chart to confirm price is actually near the Fib zone the card claims.

Research / education only — not financial advice.`

const FIB_OVERVIEW = `Fibonacci Pro — experienced-trader Fib playbook

Pullbacks into classic Fib ratios (especially the golden pocket and OTE zone) are how many
discretionary desks frame with-trend entries. Extensions (127.2% / 161.8%) define continuation
targets and exhaustion fades. This module evaluates all of those on India / US / crypto / commodity
tickers, attaches a risk plan, and draws the Fib ladder on the chart.`

const FIB_WHEN = `When to use which strategy

1. Golden Pocket — clean impulse, shallow-to-mid pullback, trend still alive (EMA stack). Everyday workhorse.
2. OTE / SMC — want a deeper discount/premium (61.8–78.6) after a liquidity grab; fewer trades, better R:R.
3. Deep 78.6 — volatile names that routinely deep-retrace; size smaller, stop beyond the swing.
4. Extension Ride — already reclaimed the swing origin and thrusting; scale at 127.2, trail toward 161.8.
5. Fib Cluster — secondary swing Fib stacks on the primary golden zone; highest conviction, rarest.
6. Rejection Fade — price tagged an extension and rejected; counter-extension fade with tight risk.`

function FibonacciProPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [error, setError] = useState('')
  const [timeframe, setTimeframe] = useState('1d')
  const [lookback, setLookback] = useState(250)
  const [fibLookback, setFibLookback] = useState(100)
  const [secondaryLookback, setSecondaryLookback] = useState(40)
  const [zoneTolAtr, setZoneTolAtr] = useState(0.55)
  const [minRr, setMinRr] = useState(1.4)
  const [strategies, setStrategies] = useState<string[]>(FIB_STRATEGIES.map((s) => s.id))
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [showCharts, setShowCharts] = useState(true)
  const bg = useAnalysisBackground('pro_trade', 'fibonacci_pro')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const toggleStrategy = (id: string) => {
    setStrategies((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe,
    lookback_bars: lookback,
    fib_lookback: fibLookback,
    secondary_lookback: secondaryLookback,
    zone_tol_atr: zoneTolAtr,
    min_rr: minRr,
    strategies: strategies.length ? strategies : FIB_STRATEGIES.map((s) => s.id),
    start_date: startDate || undefined,
    end_date: endDate || undefined,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!strategies.length) throw new Error('Enable at least one Fib strategy')
      return runProTradeFibonacciPro(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Fibonacci Pro', data) : ''

  return (
    <div>
      <PageHeader
        title="Fibonacci Pro"
        description="Golden pocket · OTE · 78.6 · extensions · cluster · rejection fade — confidence % · SL% · TP% · charts · all asset classes"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="In plain English — how to interpret your results" defaultOpen>
          {FIB_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="Overview">{FIB_OVERVIEW}</CollapsibleSection>
        <CollapsibleSection title="When to use which Fib strategy">{FIB_WHEN}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['1d'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-slate-400">Strategies to evaluate</p>
          <div className="flex flex-wrap gap-2">
            {FIB_STRATEGIES.map((s) => {
              const on = strategies.includes(s.id)
              return (
                <label
                  key={s.id}
                  className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${
                    on
                      ? 'border-violet-500/50 bg-violet-500/10 text-violet-200'
                      : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-800 text-violet-500"
                    checked={on}
                    onChange={() => toggleStrategy(s.id)}
                  />
                  {s.label}
                </label>
              )
            })}
          </div>
        </div>

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-3">
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {EW_TFS.map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </Select>
          </FormField>
          <FormField label="Candle history">
            <Input type="number" min={60} max={650} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 250)} />
          </FormField>
          <FormField label="Primary Fib lookback">
            <Input type="number" min={30} max={300} value={fibLookback} onChange={(e) => setFibLookback(Number(e.target.value) || 100)} />
          </FormField>
          <FormField label="Secondary lookback (cluster)">
            <Input type="number" min={20} max={120} value={secondaryLookback} onChange={(e) => setSecondaryLookback(Number(e.target.value) || 40)} />
          </FormField>
          <FormField label="Zone tolerance (ATR)">
            <Input type="number" step="0.05" min={0.2} max={2} value={zoneTolAtr} onChange={(e) => setZoneTolAtr(Number(e.target.value) || 0.55)} />
          </FormField>
          <FormField label="Min reward:risk">
            <Input type="number" step="0.1" min={0.8} max={5} value={minRr} onChange={(e) => setMinRr(Number(e.target.value) || 1.4)} />
          </FormField>
        </div>

        <div className="mt-4 grid max-w-3xl gap-3 sm:grid-cols-2">
          <FormField label="From date (optional)">
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </FormField>
          <FormField label="To date (optional)">
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan Fibonacci Pro (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Fibonacci Pro · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!strategies.length) return 'Enable at least one Fib strategy'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Mapping Fib swings and evaluating strategies…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          {bg.viewedReportId != null && bg.viewedReportMeta?.name && (
            <p className="mb-2 text-sm text-slate-400">
              Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
            </p>
          )}
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <FibonacciProPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/fibonacci-pro" />}
        </>
      )}
    </div>
  )
}

const BB_OVERVIEW = `BB Mean Reversion — Bollinger Band %B stretch, hardened with the checks a real mean-reversion desk applies

When price closes outside its Bollinger Bands (20-bar mean ± 2 standard deviations), that stretch has historically
tended to snap back toward the mean. But a naive "buy the lower band" bot gets run over the moment the market is
actually trending — the band just walks with price. This strategy only calls a trade after several independent
checks agree: the market is genuinely range-bound (not trending), RSI confirms the extreme, a reversal candlestick
shows up right at the band, a volume climax backs the turn, and an independent Support/Resistance zone lines up
with the same level.

Research / education only — not financial advice.`

const BB_RULES = `How the confidence score is built

1. **Regime filter (hard block)** — Kaufman's Efficiency Ratio measures how directly price is moving vs. chopping.
   If the market is trending too cleanly to fade, the trade is blocked outright rather than shown as a weak signal.
2. **Band squeeze awareness** — Bollinger Bandwidth compared to its own recent percentile history; a tight squeeze
   often resolves with a breakout, not a reversion, so it lowers confidence.
3. **RSI extreme** — the %B stretch should be echoed by RSI overbought/oversold, not just price alone.
4. **Candlestick reversal** — a confirming pattern (Hammer, Engulfing, Shooting Star, etc.) right at the band.
5. **Volume climax** — a reversal on a volume spike carries more weight than one on quiet volume.
6. **Independent Support/Resistance confluence** — a genuine swing-fractal zone near the band touch, from pure
   price geometry rather than the bands themselves.
7. **Risk plan** — stop just beyond the band edge (sanity-checked against ATR so it isn't unrealistically tight or
   wide), target at the mean, reward:risk floor enforced, and a final A/B/C quality grade.
8. **Optional extra confluence (pick any, none required)** — each one adds its own independent vote:
   - **Fibonacci** — is the price also sitting at a classic retracement level (38.2%/50%/61.8% etc.)?
   - **EMA position (20/50 stack)** — is this a pullback *within* the larger trend, not a lone counter-trend bet?
   - **EMA crossover (9/21)** — did short-term momentum just turn the same way (a fresh cross, not a stale one)?
   - **Stochastic RSI** — a more sensitive overbought/oversold read than plain RSI, for a second opinion.
   - **VWAP** — is price still on the "cheap"/"rich" side of the volume-weighted average price?
   - **Volume Profile** — is price at the Value Area High/Low, where the profile itself says value ends?
   - **Smart Money (Order Blocks)** — is there an unmitigated institutional footprint right at this level?
   - **Reversal strategy** — a chart pattern (double top/bottom) or RSI divergence pointing the same way.
   - **MACD** — is the histogram already turning, an early momentum-shift tell?
   - **Support & Resistance zone** — a genuine swing-fractal S/R level, independent of the bands.
   - **Trend direction & strength (ADX)** — on *this* timeframe, does +DI/-DI agree with the trade direction?
   - **MTF Trend & Strength** — zooms out to a genuinely higher timeframe (e.g. 1h→1d, 1d→1w) and checks
     whether the *bigger-picture* trend direction and strength back this trade — the single highest-value
     check for telling a real with-trend pullback apart from a lone counter-trend bet the smaller timeframe
     can't see on its own.
   - **Candlestick & Chart Patterns** — a broader scan (wider lookback than the core check) for classic
     candlestick patterns (Hammer, Engulfing, Shooting Star, Morning/Evening Star) *and* chart patterns
     (Double Top/Bottom) — visible, well-known price-action signatures at this level.`

const BB_LAYMAN = `In plain English — no jargon

Think of a rubber band stretched from a fixed point (the average price). The further it stretches, the more it
tends to snap back — that's the core idea. This tool watches for that stretch (the "Bollinger Band" touch), then
checks several independent things before trusting it: is the market actually calm enough for a snap-back to work
(not in a strong one-way trend), does momentum (RSI) agree the move is overdone, did a classic reversal candle show
up, did trading volume spike on the turn, and is there another independent price level nearby backing it up.

- **SIGNAL: BULLISH** — price stretched too far down, a bounce back up toward the average is expected.
- **SIGNAL: BEARISH** — price stretched too far up, a pullback down toward the average is expected.
- **SIGNAL: WAIT (blocked)** — price is stretched, but the market is trending too cleanly to safely fade it.
- **SIGNAL: NEUTRAL** — price isn't stretched enough yet; nothing to trade.

The more of the confirming checks that line up, the higher the confidence % and the better the A/B/C grade.

If you tick any of the 13 optional extra checks below, each one gets its own line in the result card's
confidence reasons — a line starting with "+N:" means it agreed with the trade and added confidence; a plain
line without "+N:" means it didn't confirm (or wasn't available), which is honestly reported rather than hidden.
"MTF Trend & Strength" deserves special attention: it's the only check that looks at a genuinely *higher*
timeframe than the one you're scanning — think of it as asking "does the bigger picture agree with this trade,
or would I be fighting a larger trend I can't see on my current chart?" A trade that passes this check is
higher-probability than one that only looks convincing on its own timeframe.`

function BbMeanReversionPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(250)
  const [bbPeriod, setBbPeriod] = useState(20)
  const [bbStd, setBbStd] = useState(2.0)
  const [showCharts, setShowCharts] = useState(false)
  const [extraChecks, setExtraChecks] = useState<string[]>([])
  const bg = useAnalysisBackground('pro_trade', 'bb_mean_reversion')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])
  const toggleExtraCheck = (value: string) =>
    setExtraChecks((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframes: picker.durations,
    lookback_bars: lookback,
    bb_period: bbPeriod,
    bb_std: bbStd,
    extra_checks: extraChecks,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!picker.durations.length) throw new Error('Select at least one timeframe')
      return runProTradeBbMeanReversion(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('BB Mean Reversion', data) : ''

  return (
    <div>
      <PageHeader
        title="BB Mean Reversion"
        description="Bollinger %B stretch confirmed by regime filter, RSI, candlestick, volume climax & S/R confluence"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="In plain English — how to interpret your results" defaultOpen>
          {BB_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="Overview">{BB_OVERVIEW}</CollapsibleSection>
        <CollapsibleSection title="How the confidence score is built">{BB_RULES}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['1d'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-3xl gap-3 sm:grid-cols-3">
          <FormField label="Candle history">
            <Input
              type="number"
              min={60}
              max={650}
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value) || 250)}
            />
          </FormField>
          <FormField label="BB period">
            <Input
              type="number"
              min={10}
              max={50}
              value={bbPeriod}
              onChange={(e) => setBbPeriod(Number(e.target.value) || 20)}
            />
          </FormField>
          <FormField label="BB std dev">
            <Input
              type="number"
              step="0.1"
              min={1}
              max={3.5}
              value={bbStd}
              onChange={(e) => setBbStd(Number(e.target.value) || 2.0)}
            />
          </FormField>
        </div>

        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              Extra confluence checks (optional — pick any to add more confidence)
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className="text-[11px] text-slate-500 hover:text-slate-300"
                onClick={() => setExtraChecks(BB_EXTRA_CHECK_OPTIONS.map((o) => o.value))}
              >
                Select all
              </button>
              <button
                type="button"
                className="text-[11px] text-slate-500 hover:text-slate-300"
                onClick={() => setExtraChecks([])}
              >
                Clear
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {BB_EXTRA_CHECK_OPTIONS.map((opt) => (
              <Chip key={opt.value} selected={extraChecks.includes(opt.value)} onClick={() => toggleExtraCheck(opt.value)}>
                {opt.label}
              </Chip>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-slate-500">
            Each selected check reuses an existing, already-proven indicator/engine in this app and adds its own
            independent vote to the confidence score — pick one or more for a more institutional-grade read; leave
            all unchecked to use just the core Bollinger %B / regime / RSI / candlestick / volume read.
          </p>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan BB Mean Reversion (${picker.tickers.length} × ${picker.durations.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`BB Mean Reversion · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!picker.durations.length) return 'Select at least one timeframe'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Computing Bollinger Bands, regime filter and confirmation checks…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <BbMeanReversionPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/bb-mean-reversion" />}
        </>
      )}
    </div>
  )
}

const TL_FURTHER_ANALYSIS_OPTIONS: { value: string; label: string }[] = [
  { value: 'mtf_trend_strength', label: 'Trend & Strength (MTF)' },
]

const TL_OVERVIEW = `Traffic Light Indicator — SMA 20 (Green) / 50 (Yellow) / 200 (Red) on a daily chart.

Source video: https://www.youtube.com/watch?v=xIKoYISD6mY&t=29s

Think of the three moving averages as a traffic light stack. The video's swing rules:

- **BUY:** Red on top, Yellow middle, Green bottom (SMA200 > SMA50 > SMA20) and the daily candle
  closes **below all three**. Buy the **next morning**.
- **SELL:** Stack flips so Green is on top, Yellow middle, Red bottom (SMA20 > SMA50 > SMA200) and
  price closes **above all three**. Sell the **next morning** to book profits.

Prefer large-cap / blue-chip names — weak small-caps can dip under the light and never recover.
Setups may take a month to over a year. Ideal for swing traders; long-term investors can use closes
under the 200 SMA as accumulate zones on quality names.

Optional **Trend & Strength (MTF)** further analysis adds an independent higher-timeframe vote.

Research / education only — not financial advice.`

const TL_RULES = `How signals are scored

1. **Traffic-light stack** — Red/Yellow/Green order must match BUY or SELL geometry.
2. **Close vs stack** — BUY needs close below all three; SELL needs close above all three.
3. **Next-morning action** — the trade plan targets the following session open (video rule).
4. **ATR risk plan** — suggested SL/TP when confidence clears the take threshold.
5. **Optional Trend & Strength (MTF)** — same institutional MTF dispatcher used elsewhere in the app.

Patience is part of the edge: missing the stack or forcing a mid-range close is a WAIT, not a weak signal.`

const TL_LAYMAN = `In plain English

Three average prices (20-day, 50-day, 200-day) are painted like a traffic light. When the slow red line
sits above yellow and green, and the stock closes under all of them, the video treats that as a washed-out
quality name you can buy patiently the next day. When the stack flips green-on-top and price closes above
everything, book the swing the next morning.

Use Charts (candles or line) to see the three SMA overlays. Turn on Trend & Strength if you want a second
opinion from the bigger picture before sizing.`

function TrafficLightIndicatorPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(400)
  const [showCharts, setShowCharts] = useState(true)
  const [furtherAnalysis, setFurtherAnalysis] = useState<string[]>([])
  const bg = useAnalysisBackground('pro_trade', 'traffic_light_indicator')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])
  const toggleFurther = (value: string) =>
    setFurtherAnalysis((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe: '1d',
    lookback_bars: lookback,
    further_analysis: furtherAnalysis,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeTrafficLight(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Traffic Light Indicator', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="Traffic Light Indicator"
        description="SMA 20 / 50 / 200 traffic-light stack — buy under all three, sell above the flip (daily)"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="In plain English — how to interpret your results" defaultOpen>
          {TL_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="Overview — how it works" defaultOpen>
          {TL_OVERVIEW}
        </CollapsibleSection>
        <CollapsibleSection title="How signals are scored">{TL_RULES}</CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: [] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-md gap-3 sm:grid-cols-1">
          <FormField label="Candle history (daily bars)">
            <Input
              type="number"
              min={220}
              max={1200}
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value) || 400)}
            />
          </FormField>
        </div>

        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              Further analysis (optional)
            </p>
            <button
              type="button"
              className="text-[11px] text-slate-500 hover:text-slate-300"
              onClick={() => setFurtherAnalysis([])}
            >
              Clear
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {TL_FURTHER_ANALYSIS_OPTIONS.map((opt) => (
              <Chip
                key={opt.value}
                selected={furtherAnalysis.includes(opt.value)}
                onClick={() => toggleFurther(opt.value)}
              >
                {opt.label}
              </Chip>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-slate-500">
            Trend & Strength reuses the app&apos;s MTF trend/strength engine as an independent confirmation vote.
          </p>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan Traffic Light (${picker.tickers.length})`}
          </Button>
          <a
            href="https://www.youtube.com/watch?v=xIKoYISD6mY&t=29s"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 self-center text-sm text-sky-400 hover:text-sky-300"
          >
            Watch strategy video <ExternalLink size={14} />
          </a>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Traffic Light · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Computing SMA 20/50/200 traffic-light stack…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <TrafficLightIndicatorPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/traffic-light-indicator" />}
        </>
      )}
    </div>
  )
}

const BLSH_OVERVIEW = `Buy Low Sell High — 25-day low (25 DL) GTT ladder for all asset classes.

Originally framed on liquid Nifty 50 / Bank Nifty names; use the same rules on India · US · Crypto · Commodities.

1. Track the 25-day low.
2. Place a buy GTT at 25 DL + 5%. When price trades through it, you are bought.
3. If a new 25 DL prints before fill, update the GTT to 5% above the new low.
4. After a fill, arm the next buy only when price is 10% below your average — again at latest 25 DL + 5%.
5. Sell all units at average + 5%.
6. No stop-loss — you buy weakness via the ladder; the exit is the +5% average target.

This screen simulates GTT state from daily OHLC. Place real GTTs on your broker. Research only.`

const BLSH_RULES = `How the scanner decides status

- WATCH / PLACE GTT — flat; keep buy GTT at current 25 DL + buffer.
- NEAR TRIGGER / BUY FILL ZONE — price is close to or through the buy GTT.
- HOLD FOR SELL — simulated position on; wait for average + sell target.
- ARM ADD GTT — price ≤ average − 10%; place the next buy GTT at latest 25 DL + 5%.
- SELL ALL / SELL ZONE — book all units near average + 5%.

Charts overlay 25 DL + buy GTT (candles or line). No stop-loss line by design.`

const BLSH_LAYMAN = `In plain English

Wait for a stock to make a fresh 25-day low, then set a buy order a little above that low (5%). If it makes an even lower low before you get filled, move the order down with it. Once you own shares, only buy more after the price has fallen about 10% below your average cost — again using a 5%-above-25-day-low order. When price is 5% above your average, sell everything. There is no stop-loss: the plan is to buy dips and exit on a small gain from average.`

const BLSH_HOW_TO = `How to trade this from the app

1. Pick asset class (India tip: start with Nifty 50 / Bank Nifty liquid names).
2. Select tickers → Scan Buy Low Sell High.
3. For each card, copy the Buy GTT level into your broker GTT.
4. If status says UPDATE / new 25 DL, move the GTT.
5. If status says ARM ADD GTT, place the next tranche GTT.
6. If status says SELL ALL, exit the full position near average + 5%.
7. Do not add a stop-loss for this method — size positions you can hold through further dips.`

function BuyLowSellHighPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(320)
  const [lowLookback, setLowLookback] = useState(25)
  const [buyBuffer, setBuyBuffer] = useState(5)
  const [sellTarget, setSellTarget] = useState(5)
  const [addDrop, setAddDrop] = useState(10)
  const [showCharts, setShowCharts] = useState(true)
  const bg = useAnalysisBackground('pro_trade', 'buy_low_sell_high')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe: '1d',
    lookback_bars: lookback,
    low_lookback: lowLookback,
    buy_buffer_pct: buyBuffer,
    sell_target_pct: sellTarget,
    add_on_drop_pct: addDrop,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeBuyLowSellHigh(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Buy Low Sell High', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="Buy Low Sell High"
        description="25-day low GTT ladder — buy at 25DL+5%, sell all at avg+5%, no stop-loss (all asset classes)"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={BLSH_HOW_TO}>
          {BLSH_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {BLSH_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="Overview — method" defaultOpen>
          {BLSH_OVERVIEW}
        </CollapsibleSection>
        <CollapsibleSection title="How statuses are decided">{BLSH_RULES}</CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: [] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <FormField label="History (daily bars)">
            <Input type="number" min={60} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 320)} />
          </FormField>
          <FormField label="Low lookback (days)">
            <Input type="number" min={10} max={60} value={lowLookback} onChange={(e) => setLowLookback(Number(e.target.value) || 25)} />
          </FormField>
          <FormField label="Buy GTT buffer %">
            <Input type="number" step="0.5" min={1} max={15} value={buyBuffer} onChange={(e) => setBuyBuffer(Number(e.target.value) || 5)} />
          </FormField>
          <FormField label="Sell target % (of avg)">
            <Input type="number" step="0.5" min={1} max={20} value={sellTarget} onChange={(e) => setSellTarget(Number(e.target.value) || 5)} />
          </FormField>
          <FormField label="Add-on drop %">
            <Input type="number" step="0.5" min={3} max={30} value={addDrop} onChange={(e) => setAddDrop(Number(e.target.value) || 10)} />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan Buy Low Sell High (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Buy Low Sell High · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Computing 25-day lows and GTT ladder state…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <BuyLowSellHighPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/buy-low-sell-high" />}
        </>
      )}
    </div>
  )
}

const RLB_YOUTUBE = 'https://www.youtube.com/watch?v=pBQ1oVDVe3M'

const RLB_HOW_TO = `How to use RLB - Breakout

Source: ${RLB_YOUTUBE}

1. Pick an asset class and liquid tickers.
2. Scan on the daily chart (default).
3. Focus on RLB pass (all 7 confirmations) — optional near-miss ≥5/7 filter for watchlist.
4. Prefer RSI ≥ 65 and clear volume expansion for higher conviction.
5. Use ATR stop/target as a risk frame; invalidate if price closes back under prior high / EMA20.

Research / education only — not financial advice.`

const RLB_OVERVIEW = `RLB — Rocket Launcher Breakout

Seven confirmations for strong bullish momentum / explosive breakout potential:

1. Close > previous day's high
2. Green candle (close > open)
3. Close > EMA20
4. Close > EMA50
5. RSI > 60 (prefer ≥ 65)
6. Daily gain > 2%
7. Volume > 5-day SMA of volume

Combining trend, momentum, price action, and volume filters false breakouts.
Works on India · US · Crypto · Commodities.`

const RLB_LAYMAN = `In plain English

RLB looks for a stock that is already strong today: it closes above yesterday's high on a green candle,
stays above its 20- and 50-day average prices, shows RSI momentum (ideally 65+), gains more than 2% on the day,
and trades with above-average volume. When all seven line up, the video treats that as a "rocket launcher" breakout candidate.`

function RlbBreakoutPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(250)
  const [rsiMin, setRsiMin] = useState(60)
  const [rsiPrefer, setRsiPrefer] = useState(65)
  const [minDayChg, setMinDayChg] = useState(2)
  const [volSma, setVolSma] = useState(5)
  const [requireAll, setRequireAll] = useState(true)
  const [showCharts, setShowCharts] = useState(true)
  const bg = useAnalysisBackground('pro_trade', 'rlb_breakout')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe: '1d',
    lookback_bars: lookback,
    rsi_min: rsiMin,
    rsi_prefer: rsiPrefer,
    min_day_chg_pct: minDayChg,
    volume_sma_period: volSma,
    require_all_seven: requireAll,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeRlbBreakout(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('RLB - Breakout', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="RLB - Breakout"
        description="Rocket Launcher Breakout — 7 confirmations for explosive bullish momentum"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={RLB_HOW_TO}>
          <ol className="list-decimal space-y-1.5 pl-4 text-sm text-slate-300">
            <li>Pick asset class + liquid tickers, then scan (daily).</li>
            <li>Prioritise <strong className="text-slate-100">RLB pass (7/7)</strong>; use near-miss ≥5/7 as a watchlist.</li>
            <li>Prefer <strong className="text-slate-100">RSI ≥ 65</strong> and clear volume expansion.</li>
            <li>Risk-frame with ATR SL/TP; invalidate on a close back under prior high / EMA20.</li>
          </ol>
          <a href={RLB_YOUTUBE} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-sm text-sky-400 hover:text-sky-300">
            Watch strategy video <ExternalLink size={14} />
          </a>
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>{RLB_LAYMAN}</CollapsibleSection>
        <CollapsibleSection title="Overview — 7 confirmations" defaultOpen>{RLB_OVERVIEW}</CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: [] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <FormField label="History (daily bars)">
            <Input type="number" min={60} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 250)} />
          </FormField>
          <FormField label="RSI minimum">
            <Input type="number" min={50} max={80} value={rsiMin} onChange={(e) => setRsiMin(Number(e.target.value) || 60)} />
          </FormField>
          <FormField label="RSI prefer (≥)">
            <Input type="number" min={55} max={85} value={rsiPrefer} onChange={(e) => setRsiPrefer(Number(e.target.value) || 65)} />
          </FormField>
          <FormField label="Min day gain %">
            <Input type="number" step="0.1" min={0.5} max={10} value={minDayChg} onChange={(e) => setMinDayChg(Number(e.target.value) || 2)} />
          </FormField>
          <FormField label="Volume SMA days">
            <Input type="number" min={3} max={20} value={volSma} onChange={(e) => setVolSma(Number(e.target.value) || 5)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={requireAll} onClick={() => setRequireAll(true)}>Require all 7 for BUY</Chip>
          <Chip selected={!requireAll} onClick={() => setRequireAll(false)}>Allow 6/7 near-pass</Chip>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan RLB Breakout (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`RLB Breakout · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Checking prior-high break, EMAs, RSI, volume…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <RlbBreakoutPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/rlb-breakout" />}
        </>
      )}
    </div>
  )
}

const TIO_HOW_TO = `How to use 3-in-1 Trade System

1. Use a quality / liquid watchlist (prefer strong names — you may average −20% dips).
2. Set CAR days: 10 (safer) or 5–7 (earlier entry).
3. Scan — BUY rows pass DMA stack + CAR; ranked closest to 200 DMA first.
4. Size new buys from the 75% bucket; keep 25% reserve for SIP.
5. Exit all at average + 6.28%.
6. If −20%: wait CAR rising again + 30-day gap; add ~1/3 original from reserve.
7. FIRE compounding: recycle profits; size from remaining slots so capital lasts to max holdings.

Research / education only — not financial advice.`

const TIO_OVERVIEW = `3-in-1 = DMA + CAR + Volume (Mahesh Kaushik / FIRE in India refinements)

Capital: 75% new buying · 25% reserve · max holdings (e.g. 15) · FIRE compounding.

Selection: above SMA50/100/200 · ≤10% above 200 DMA · prefer closest to 200 · turnover over raw volume.

Entry: CAR (expanding average of closes from 52-week high) rising N consecutive days.

Exit: sell all at +6.28% of average purchase price.

SIP defense: after −20%, re-trigger CAR + prefer 30 calendar day gap · deploy ~1/3 original from reserve.`

const TIO_LAYMAN = `In plain English

Only buy when the stock is above its 50-, 100-, and 200-day averages, not stretched more than ~10% above the 200,
and its “CAR” line (a running average measured from the 52-week high) has been climbing for several days in a row.
Among those, pick the ones sitting closest to the 200-day average. Take profit when you’re up 6.28% from your average
cost. If a name drops 20%, don’t panic-average — wait for CAR to climb again and for enough days to pass, then use the
reserve money for a smaller top-up.`

const TIO_OPTIMIZED = `Optimized tweaks built into defaults

• FIRE compounding (slot-based sizing) over aggressive “raise buy every 3 wins”.
• Rank BUY signals by closeness to 200 DMA.
• CAR days tunable 5–7 for impatient entries (default 10).
• SIP gap default 30 days.
• Prefer custom quality watchlists when averaging dips.`

function ThreeInOneTradeSystemPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(400)
  const [carDays, setCarDays] = useState(10)
  const [maxAbove200, setMaxAbove200] = useState(10)
  const [sipGap, setSipGap] = useState(30)
  const [maxHoldings, setMaxHoldings] = useState(15)
  const [requireVol, setRequireVol] = useState(false)
  const [showCharts, setShowCharts] = useState(true)
  const bg = useAnalysisBackground('pro_trade', 'three_in_one_trade_system')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe: '1d',
    lookback_bars: lookback,
    car_rising_days: carDays,
    max_pct_above_200: maxAbove200,
    require_volume_breakout: requireVol,
    sip_gap_days: sipGap,
    max_holdings: maxHoldings,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeThreeInOne(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('3-in-1 Trade System', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="3-in-1 Trade System"
        description="DMA 50/100/200 + CAR rising + volume — exit +6.28% · SIP after −20% (FIRE / Mahesh style)"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={TIO_HOW_TO}>
          {TIO_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {TIO_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — core + optimized" defaultOpen>
          {TIO_OVERVIEW}
          {'\n\n'}
          {TIO_OPTIMIZED}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: [] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <FormField label="History (daily bars)">
            <Input type="number" min={220} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 400)} />
          </FormField>
          <FormField label="CAR rising days (10 / 5–7)">
            <Input type="number" min={5} max={20} value={carDays} onChange={(e) => setCarDays(Number(e.target.value) || 10)} />
          </FormField>
          <FormField label="Max % above 200 DMA">
            <Input type="number" step="0.5" min={2} max={25} value={maxAbove200} onChange={(e) => setMaxAbove200(Number(e.target.value) || 10)} />
          </FormField>
          <FormField label="SIP gap (days)">
            <Input type="number" min={7} max={60} value={sipGap} onChange={(e) => setSipGap(Number(e.target.value) || 30)} />
          </FormField>
          <FormField label="Max holdings (playbook)">
            <Input type="number" min={5} max={40} value={maxHoldings} onChange={(e) => setMaxHoldings(Number(e.target.value) || 15)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={carDays === 10} onClick={() => setCarDays(10)}>CAR 10 (classic)</Chip>
          <Chip selected={carDays === 7} onClick={() => setCarDays(7)}>CAR 7</Chip>
          <Chip selected={carDays === 5} onClick={() => setCarDays(5)}>CAR 5 (early)</Chip>
          <Chip selected={requireVol} onClick={() => setRequireVol((v) => !v)}>
            Require volume breakout
          </Chip>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan 3-in-1 (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`3-in-1 · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Computing DMA stack, CAR from 52w high, volume…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <ThreeInOneTradeSystemPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/3-in-1-trade-system" />}
        </>
      )}
    </div>
  )
}

const SE_HOW_TO = `How to use Simple Effective

1. Pick asset class + timeframe(s) — works on 1m, 15m, and higher TFs.
2. Scan for closes fully outside the MA band with a MACD crossover inside the matching histogram.
3. BUY only after the signal candle High breaks; SELL only after the Low breaks.
4. Place SL on the opposite edge of the MA band.
5. Book at 1:1 or 1:1.5 RRR (trail toward 1:3 only if momentum continues).
6. Skip Sell setups where Open = Low on the signal candle.
7. Never take an MA-band break without MACD-in-histogram confirmation.

Research / education only — not financial advice.`

const SE_OVERVIEW = `Simple Effective — MA band + MACD

• Two MAs form a band/channel + MACD.
• Signal candle must close fully outside the band.
• Enter on break of signal High (Buy) or Low (Sell).
• Stop-loss at the opposite band edge.
• Target 1:1 or 1:1.5 RRR for high accuracy.
• MACD crossover required inside green hist (Buy) or red hist (Sell).
• Avoid Open=Low sell traps (especially gap-downs).

Versatile across Stocks, Indices, Forex, Crypto, Commodities.`

const SE_LAYMAN = `In plain English

Wait for a candle to finish completely above or below a two-moving-average channel, with MACD crossing in the same direction and inside the matching histogram colour (green for buys, red for sells). Only enter once the next price action breaks that candle’s high (buy) or low (sell). Put your stop on the far side of the channel and take a modest 1:1 or 1:1.5 profit — accuracy first.`

function SimpleEffectivePage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(300)
  const [maFast, setMaFast] = useState(9)
  const [maSlow, setMaSlow] = useState(21)
  const [useEma, setUseEma] = useState(true)
  const [rr, setRr] = useState(1.5)
  const [showCharts, setShowCharts] = useState(true)
  const bg = useAnalysisBackground('pro_trade', 'simple_effective')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframes: picker.durations.length ? picker.durations : ['15m'],
    lookback_bars: lookback,
    ma_fast: maFast,
    ma_slow: maSlow,
    use_ema: useEma,
    rr_multiple: rr,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!picker.durations.length) throw new Error('Select at least one timeframe')
      return runProTradeSimpleEffective(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Simple Effective', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="Simple Effective"
        description="MA band close-outside + MACD hist-zone cross — enter on High/Low break · SL opposite band · 1:1–1.5 RRR"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={SE_HOW_TO}>
          {SE_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {SE_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {SE_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <FormField label="History (bars)">
            <Input type="number" min={80} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 300)} />
          </FormField>
          <FormField label="MA fast">
            <Input type="number" min={3} max={50} value={maFast} onChange={(e) => setMaFast(Number(e.target.value) || 9)} />
          </FormField>
          <FormField label="MA slow">
            <Input type="number" min={5} max={100} value={maSlow} onChange={(e) => setMaSlow(Number(e.target.value) || 21)} />
          </FormField>
          <FormField label="RRR (1 = 1:1)">
            <Input type="number" step="0.1" min={1} max={3} value={rr} onChange={(e) => setRr(Number(e.target.value) || 1.5)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={useEma} onClick={() => setUseEma(true)}>EMA band</Chip>
          <Chip selected={!useEma} onClick={() => setUseEma(false)}>SMA band</Chip>
          <Chip selected={rr === 1} onClick={() => setRr(1)}>1:1 RRR</Chip>
          <Chip selected={rr === 1.5} onClick={() => setRr(1.5)}>1:1.5 RRR</Chip>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending
              ? 'Scanning…'
              : `Scan Simple Effective (${picker.tickers.length} × ${picker.durations.length || 1})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Simple Effective · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!picker.durations.length) return 'Select at least one timeframe'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Checking MA-band closes, MACD hist-zone crosses, triggers…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <SimpleEffectivePanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/simple-effective" />}
        </>
      )}
    </div>
  )
}

const BRV_HOW_TO = `How to use BB-RSI-VOL

1. Pick asset class + timeframes + tickers (works on all 4 asset classes).
2. Defaults: BB(20,2) · RSI 35/70 · Vol MA20 · EMA 5/9/50 · require S/R.
3. Scan — only TAKE rows with conf% / SL% / TP% are actionable.
4. Each ticker also shows EMA5/EMA9 position, rise/fall intensity, and whether the next 2 candles tend to continue (from ~100d history) with % confidence.
5. Pro habit: wait for the 9 EMA close; never front-run the band alone.
6. Book partial at mid-band (T1); trail toward T2. Skip steep 50 EMA trends.
7. Also available in Backtester as "BB-RSI-VOL". Research only — not advice.`

const BRV_OVERVIEW = `BB-RSI-VOL — strategy matrix

BUY: Lower BB touch · RSI ≤ 35 · Low volume (below Vol MA) · Support · close above 9 EMA
SELL: Upper BB touch · RSI ≥ 70 · High volume (above Vol MA) · Resistance · close below 9 EMA

Also reports: price above/below EMA5 & EMA9 · short-term rise/fall intensity · next-2-candle continuation odds from similar setups in the last ~100 days (% confidence).

Filters: 50 EMA slope + Kaufman ER (no falling knife / melt-up). Boost: RSI divergence + reversal candle.
T1 = mid BB · T2 = opposite band / next S/R · SL beyond swing / climax wick.
Outputs: % confidence · %SL · %TP · grade A/B/C.`

const BRV_LAYMAN = `In plain English

Buy when price is cheap at the bottom band, RSI is washed out, volume is quiet (sellers tired), and it sits on old support — but only after it closes back above the fast EMA.
Sell when price spikes into the top band with high RSI and climax volume into resistance — after it closes back under the fast EMA.
If the trend is a waterfall or a rocket, stand aside.`

function BbRsiVolPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(300)
  const [rsiBuy, setRsiBuy] = useState(35)
  const [rsiSell, setRsiSell] = useState(70)
  const [requireSr, setRequireSr] = useState(true)
  const [showCharts, setShowCharts] = useState(true)
  const { useAi, setUseAi } = useTradeSetupAi()
  const bg = useAnalysisBackground('pro_trade', 'bb_rsi_vol')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframes: picker.durations.length ? picker.durations : ['15m'],
    lookback_bars: lookback,
    rsi_buy: rsiBuy,
    rsi_sell: rsiSell,
    require_sr: requireSr,
    use_ai: useAi,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!picker.durations.length) throw new Error('Select at least one timeframe')
      return runProTradeBbRsiVol(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('BB-RSI-VOL', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="BB-RSI-VOL"
        description="Lower BB + RSI≤35 + low vol → Buy · Upper BB + RSI≥70 + high vol → Sell · S/R + EMA filters · conf% / SL% / TP%"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={BRV_HOW_TO}>
          {BRV_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {BRV_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {BRV_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-3xl gap-3 sm:grid-cols-3">
          <FormField label="History (bars)">
            <Input type="number" min={80} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 300)} />
          </FormField>
          <FormField label="RSI buy ≤">
            <Input type="number" min={20} max={45} value={rsiBuy} onChange={(e) => setRsiBuy(Number(e.target.value) || 35)} />
          </FormField>
          <FormField label="RSI sell ≥">
            <Input type="number" min={60} max={85} value={rsiSell} onChange={(e) => setRsiSell(Number(e.target.value) || 70)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={requireSr} onClick={() => setRequireSr(true)}>Require S/R</Chip>
          <Chip selected={!requireSr} onClick={() => setRequireSr(false)}>S/R optional</Chip>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending
              ? useAi
                ? 'Scanning + AI refine…'
                : 'Scanning…'
              : `Scan BB-RSI-VOL (${picker.tickers.length} × ${picker.durations.length || 1})`}
          </Button>
        </div>
        <UseAiCheckbox checked={useAi} onChange={setUseAi} className="mt-3" />
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`BB-RSI-VOL · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!picker.durations.length) return 'Select at least one timeframe'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Checking BB · RSI · volume · EMA · S/R…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <BbRsiVolPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/bb-rsi-vol" />}
        </>
      )}
    </div>
  )
}

const EMA9_HOW_TO = `How to use 9 EMA Cross

1. Pick asset class + timeframes + tickers.
2. Defaults: EMA9 · BB(20,2) · RSI(14) · Vol MA20.
3. Scan — TAKE only on a fresh close cross of the 9 EMA with confirming filters.
4. Long: cross above 9 EMA · RSI momentum · volume expand preferred · not hugging Upper BB.
5. Short: cross below 9 EMA · RSI mid-low · volume expand preferred · not hugging Lower BB.
6. T1 = mid BB · T2 = outer band · invalidate on close back through 9 EMA.
7. Optional Use AI to refine Conf % / SL % / TP %. Research only — not advice.`

const EMA9_OVERVIEW = `9 EMA Cross — strategy matrix

LONG: Close crosses above 9 EMA · RSI in momentum zone · volume preferably expanding · room under Upper BB
SHORT: Close crosses below 9 EMA · RSI mid-low · volume preferably expanding · room above Lower BB

Holding above/below without a fresh cross → WATCH only.
Outputs: % confidence · %SL · %TP · grade A/B/C.`

const EMA9_LAYMAN = `In plain English

Buy when price closes back above the 9 EMA with buyers showing up (volume) and RSI not already blown out — aiming toward the middle of the Bollinger Band first.
Sell when price closes back under the 9 EMA with selling volume and RSI not already crushed.
If price is already above/below the 9 EMA but did not just cross, wait — that is only a watch.`

const EMA5_HOW_TO = `How to use 5 EMA Cross

1. Pick asset class + timeframes + tickers.
2. Defaults: EMA5 · BB(20,2) · RSI(14) · Vol MA20.
3. Scan — TAKE only on a fresh close cross of the 5 EMA with confirming filters.
4. Long: cross above 5 EMA · RSI momentum · volume expand preferred · not hugging Upper BB.
5. Short: cross below 5 EMA · RSI mid-low · volume expand preferred · not hugging Lower BB.
6. T1 = mid BB · T2 = outer band · invalidate on close back through 5 EMA.
7. Faster than 9 EMA — more signals, more noise; prefer liquid names / higher TFs if choppy.
8. Optional Use AI to refine Conf % / SL % / TP %. Research only — not advice.`

const EMA5_OVERVIEW = `5 EMA Cross — strategy matrix

LONG: Close crosses above 5 EMA · RSI in momentum zone · volume preferably expanding · room under Upper BB
SHORT: Close crosses below 5 EMA · RSI mid-low · volume preferably expanding · room above Lower BB

Holding above/below without a fresh cross → WATCH only.
Outputs: % confidence · %SL · %TP · grade A/B/C.

vs 9 EMA: quicker reactions for scalps / tight momentum; use volume filter more often.`

const EMA5_LAYMAN = `In plain English

Same idea as 9 EMA Cross, but the average reacts faster. Buy when price closes back above the 5 EMA with volume and RSI not blown out. Sell on a close under the 5 EMA with selling volume. Expect more crosses — skip thin volume.`

const EMA59_HOW_TO = `How to use 5/9 EMA Cross

1. Pick asset class + timeframes + tickers.
2. Defaults: EMA5 · EMA9 · BB(20,2) · RSI(14) · Vol MA20.
3. Scan — TAKE only on a fresh EMA5/EMA9 crossover with confirming filters.
4. Long: EMA5 crosses above EMA9 · prefer close above both · RSI momentum · volume expand · room under Upper BB.
5. Short: EMA5 crosses below EMA9 · prefer close below both · RSI mid-low · volume expand · room above Lower BB.
6. T1 = mid BB · T2 = outer band · invalidate on opposite 5/9 re-cross (or close back through EMA9).
7. Optional Use AI to refine Conf % / SL % / TP %. Research only — not advice.`

const EMA59_OVERVIEW = `5/9 EMA Cross — strategy matrix

LONG: EMA5 crosses above EMA9 · close preferably above both · RSI momentum · volume expand · room under Upper BB
SHORT: EMA5 crosses below EMA9 · close preferably below both · RSI mid-low · volume expand · room above Lower BB

Holding a bull/bear stack without a fresh cross → WATCH only.
Outputs: % confidence · %SL · %TP · grade A/B/C.`

const EMA59_LAYMAN = `In plain English

Watch the fast line (5) and the slow line (9). When the fast line flips above the slow line and price is sitting above both, buyers are taking control — look for a long toward mid Bollinger. When the fast flips under the slow and price is under both, sellers are in charge — look for a short. If the lines already stacked earlier and did not just cross, wait.`

function Ema9CrossPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(300)
  const [requireVol, setRequireVol] = useState(false)
  const [freshCrossOnly, setFreshCrossOnly] = useState(true)
  const [showCharts, setShowCharts] = useState(true)
  const { useAi, setUseAi } = useTradeSetupAi()
  const bg = useAnalysisBackground('pro_trade', 'ema9_bb_rsi_vol')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframes: picker.durations.length ? picker.durations : ['15m'],
    lookback_bars: lookback,
    require_volume_expand: requireVol,
    require_fresh_cross: freshCrossOnly,
    use_ai: useAi,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!picker.durations.length) throw new Error('Select at least one timeframe')
      return runProTradeEma9Cross(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('9 EMA Cross', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="9 EMA Cross"
        description="Close above 9 EMA → long · below → short · filtered by Bollinger Bands, RSI & volume · conf% / SL% / TP%"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={EMA9_HOW_TO}>
          {EMA9_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {EMA9_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {EMA9_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-xl gap-3 sm:grid-cols-2">
          <FormField label="History (bars)">
            <Input type="number" min={80} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 300)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={freshCrossOnly} onClick={() => setFreshCrossOnly(true)}>Fresh cross only</Chip>
          <Chip selected={!freshCrossOnly} onClick={() => setFreshCrossOnly(false)}>Allow hold above/below</Chip>
          <Chip selected={requireVol} onClick={() => setRequireVol(true)}>Require volume expand</Chip>
          <Chip selected={!requireVol} onClick={() => setRequireVol(false)}>Volume optional</Chip>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending
              ? useAi
                ? 'Scanning + AI refine…'
                : 'Scanning…'
              : `Scan 9 EMA Cross (${picker.tickers.length} × ${picker.durations.length || 1})`}
          </Button>
        </div>
        <UseAiCheckbox checked={useAi} onChange={setUseAi} className="mt-3" />
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`9 EMA Cross · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!picker.durations.length) return 'Select at least one timeframe'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Checking 9 EMA cross · BB · RSI · volume…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <Ema9CrossPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/ema9-cross" />}
        </>
      )}
    </div>
  )
}

function Ema5CrossPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(300)
  const [requireVol, setRequireVol] = useState(false)
  const [freshCrossOnly, setFreshCrossOnly] = useState(true)
  const [showCharts, setShowCharts] = useState(true)
  const { useAi, setUseAi } = useTradeSetupAi()
  const bg = useAnalysisBackground('pro_trade', 'ema5_bb_rsi_vol')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframes: picker.durations.length ? picker.durations : ['15m'],
    lookback_bars: lookback,
    ema_period: 5,
    require_volume_expand: requireVol,
    require_fresh_cross: freshCrossOnly,
    use_ai: useAi,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!picker.durations.length) throw new Error('Select at least one timeframe')
      return runProTradeEma5Cross(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('5 EMA Cross', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="5 EMA Cross"
        description="Close above 5 EMA → long · below → short · filtered by Bollinger Bands, RSI & volume · faster than 9 EMA"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={EMA5_HOW_TO}>
          {EMA5_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {EMA5_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {EMA5_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-xl gap-3 sm:grid-cols-2">
          <FormField label="History (bars)">
            <Input type="number" min={80} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 300)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={freshCrossOnly} onClick={() => setFreshCrossOnly(true)}>Fresh cross only</Chip>
          <Chip selected={!freshCrossOnly} onClick={() => setFreshCrossOnly(false)}>Allow hold above/below</Chip>
          <Chip selected={requireVol} onClick={() => setRequireVol(true)}>Require volume expand</Chip>
          <Chip selected={!requireVol} onClick={() => setRequireVol(false)}>Volume optional</Chip>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending
              ? useAi
                ? 'Scanning + AI refine…'
                : 'Scanning…'
              : `Scan 5 EMA Cross (${picker.tickers.length} × ${picker.durations.length || 1})`}
          </Button>
        </div>
        <UseAiCheckbox checked={useAi} onChange={setUseAi} className="mt-3" />
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`5 EMA Cross · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!picker.durations.length) return 'Select at least one timeframe'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Checking 5 EMA cross · BB · RSI · volume…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <Ema5CrossPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/ema5-cross" />}
        </>
      )}
    </div>
  )
}

function Ema59CrossPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(300)
  const [requireVol, setRequireVol] = useState(false)
  const [freshCrossOnly, setFreshCrossOnly] = useState(true)
  const [priceConfirm, setPriceConfirm] = useState(true)
  const [showCharts, setShowCharts] = useState(true)
  const { useAi, setUseAi } = useTradeSetupAi()
  const bg = useAnalysisBackground('pro_trade', 'ema5_9_crossover')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframes: picker.durations.length ? picker.durations : ['15m'],
    lookback_bars: lookback,
    require_volume_expand: requireVol,
    require_fresh_cross: freshCrossOnly,
    require_price_confirm: priceConfirm,
    use_ai: useAi,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!picker.durations.length) throw new Error('Select at least one timeframe')
      return runProTradeEma59Cross(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('5/9 EMA Cross', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="5/9 EMA Cross"
        description="EMA5 crosses above EMA9 → long · below → short · price confirm + BB / RSI / volume · conf% / SL% / TP%"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={EMA59_HOW_TO}>
          {EMA59_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {EMA59_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {EMA59_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-xl gap-3 sm:grid-cols-2">
          <FormField label="History (bars)">
            <Input type="number" min={80} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 300)} />
          </FormField>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={freshCrossOnly} onClick={() => setFreshCrossOnly(true)}>Fresh cross only</Chip>
          <Chip selected={!freshCrossOnly} onClick={() => setFreshCrossOnly(false)}>Allow stack hold</Chip>
          <Chip selected={priceConfirm} onClick={() => setPriceConfirm(true)}>Require price confirm</Chip>
          <Chip selected={!priceConfirm} onClick={() => setPriceConfirm(false)}>EMA cross only</Chip>
          <Chip selected={requireVol} onClick={() => setRequireVol(true)}>Require volume expand</Chip>
          <Chip selected={!requireVol} onClick={() => setRequireVol(false)}>Volume optional</Chip>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending
              ? useAi
                ? 'Scanning + AI refine…'
                : 'Scanning…'
              : `Scan 5/9 EMA Cross (${picker.tickers.length} × ${picker.durations.length || 1})`}
          </Button>
        </div>
        <UseAiCheckbox checked={useAi} onChange={setUseAi} className="mt-3" />
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`5/9 EMA Cross · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!picker.durations.length) return 'Select at least one timeframe'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Checking 5/9 EMA cross · BB · RSI · volume…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <Ema59CrossPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/ema5-9-cross" />}
        </>
      )}
    </div>
  )
}

const FLAT_RETEST_HOW_TO = `How to use Flat Retest

1. Pick asset class + one or more timeframes + tickers.
2. The scanner looks for flat candles (tight consolidation box) first.
3. Do NOT predict the next candle inside the box — wait for post-flat action.
4. LONG sequence: break resistance + volume expand + close above → retest → resistance holds as support.
5. SHORT sequence: reject resistance + bearish + volume → break consolidation low → retest fails.
6. Mid-sequence rows stay WATCH. TAKE only when the full sequence is already on closed bars.
7. Optional Use AI to refine Conf % / SL % / TP %. Research only — not advice.`

const FLAT_RETEST_OVERVIEW = `Flat Retest — strategy matrix

LONG: Flat box → resistance breaks (close above + volume expand) → retest → resistance becomes support
SHORT: Flat box → resistance rejects (bearish + volume expand) → breaks cons low → retest fails

Incomplete sequences → WATCH only.
Outputs: phase · % confidence · %SL · %TP · grade A/B/C.`

const FLAT_RETEST_LAYMAN = `In plain English

First find quiet flat candles that form a box. Then watch what happens after — not inside the box.

For a buy: price punches through the top with volume, comes back to that old top, and it holds as a floor.
For a sell: price gets rejected at the top with a red candle and volume, then breaks the bottom of the box, then fails when it tries to reclaim that bottom.

If any step is missing, wait.`

function FlatRetestPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [lookback, setLookback] = useState(300)
  const [flatMin, setFlatMin] = useState(6)
  const [flatMax, setFlatMax] = useState(12)
  const [showCharts, setShowCharts] = useState(true)
  const { useAi, setUseAi } = useTradeSetupAi()
  const bg = useAnalysisBackground('pro_trade', 'flat_retest')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframes: picker.durations.length ? picker.durations : ['15m'],
    lookback_bars: lookback,
    flat_min_bars: flatMin,
    flat_max_bars: Math.max(flatMin, flatMax),
    use_ai: useAi,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      if (!picker.durations.length) throw new Error('Select at least one timeframe')
      return runProTradeFlatRetest(buildPayload())
    },
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Flat Retest', data) : ''
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="Flat Retest"
        description="After flat candles: break → retest hold = LONG · reject → break low → failed retest = SHORT · multi-TF"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={FLAT_RETEST_HOW_TO}>
          {FLAT_RETEST_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {FLAT_RETEST_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {FLAT_RETEST_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: ['15m'] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-2xl gap-3 sm:grid-cols-3">
          <FormField label="History (bars)">
            <Input type="number" min={80} max={1200} value={lookback} onChange={(e) => setLookback(Number(e.target.value) || 300)} />
          </FormField>
          <FormField label="Flat min bars">
            <Input type="number" min={4} max={20} value={flatMin} onChange={(e) => setFlatMin(Number(e.target.value) || 6)} />
          </FormField>
          <FormField label="Flat max bars">
            <Input type="number" min={6} max={30} value={flatMax} onChange={(e) => setFlatMax(Number(e.target.value) || 12)} />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}>
            {runMut.isPending
              ? useAi
                ? 'Scanning + AI refine…'
                : 'Scanning…'
              : `Scan Flat Retest (${picker.tickers.length} × ${picker.durations.length || 1})`}
          </Button>
        </div>
        <UseAiCheckbox checked={useAi} onChange={setUseAi} className="mt-3" />
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Flat Retest · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), () => {
            if (!picker.tickers.length) return 'Select at least one ticker'
            if (!picker.durations.length) return 'Select at least one timeframe'
            return null
          })}
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Mapping flat boxes · break / reject · retest…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <FlatRetestPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/flat-retest" />}
        </>
      )}
    </div>
  )
}

const BTST_FURTHER_ANALYSIS_OPTIONS: { value: string; label: string }[] = [
  { value: 'pa_vp_smc', label: 'PA-VP-SMC' },
  { value: 'volume_spread_next_candle', label: 'Volume Spread - Next Candle' },
  { value: 'elliott_wave', label: 'Elliott Wave' },
  { value: 'bb_mean_reversion', label: 'BB Mean Reversion' },
  { value: 'support_resistance', label: 'Support & Resistance' },
  { value: 'mtf_trend_strength', label: 'Trend & Strength (MTF)' },
]

const BTST_OVERVIEW = `Buy Today Sell Tomorrow / Sell Today Buy Tomorrow — the classic NSE overnight-momentum play, hardened
with an experienced-trader and institutional-desk checklist before risking capital overnight

BTST: buy strength into today's close, sell tomorrow — before delivery actually settles. STBT is the short-side
mirror: sell weakness into today's close, cover tomorrow (requires stock futures/options — NSE cash-segment
shorts can't be carried overnight).

The core signal is Close Location Value (CLV) — where today's close sits within today's own high-low range. A
close near the day's high (institutional buying absorbing all supply into the close) is the classic BTST tell; a
close near the day's low is the STBT mirror. A close mid-range means no real conviction either way, not a weak
signal — this strategy sits out rather than forcing a mediocre read.

India cash/F&O only — the delivery/overnight-settlement mechanics this strategy is built around are NSE-specific.

Research / education only — not financial advice.`

const BTST_RULES = `How the confidence score is built

1. **Closing-strength signature (core)** — Close Location Value (CLV) determines BTST vs STBT candidacy.
2. **Trend alignment** — buying strength (or selling weakness) only counts for more when it's *with* the
   higher-timeframe trend (EMA20/50 stack), not a lone counter-trend pop likely to fade overnight.
3. **Volume confirmation, with a climax guard** — elevated volume backs genuine conviction, but abnormally
   extreme volume reads as a blow-off spike (chase risk), not rewarded.
4. **Relative strength vs Nifty 50** — the stock must out/under-perform the index today, so this isn't just a
   broad market move dressed up as a single-name signal.
5. **VWAP position** — closing on the "richer" side of today's volume-weighted average price, the same
   institutional benchmark a dealing desk watches.
6. **RSI chase-risk guard** — an already-extended move overnight carries real gap-against-you risk.
7. **Options-market OI buildup** (reusing the same NSE option-chain OI-buildup read Options → Market Prediction
   uses) — a fresh Long/Short Buildup is genuine institutional derivatives conviction building behind the move,
   the single highest-value institutional check here. Gracefully skipped (not penalized) for cash-only names.
8. **No late-session fade** — the final stretch of the session shouldn't be reversing hard against the signal.
9. **A genuine historical self-check** — this exact ticker's own last ~90 sessions are scanned for the same
   closing-strength signature, and the empirical next-day follow-through hit-rate is scored — a real, ticker-
   specific edge check, not just theory applied blindly.
10. **Risk plan** — ATR-sane stop/target (not a raw guess), a reward:risk floor, liquidity floor, and a final
    A/B/C quality grade — the same trading-judgment layer every Pro Trade engine uses.
11. **Optional further analysis (pick any, none required)** — reuses the same 6-check dispatcher built for
    Trading Hub → Intra-Hedging: PA-VP-SMC, Volume Spread - Next Candle, Elliott Wave, BB Mean Reversion,
    Support & Resistance, and a genuine higher-timeframe Trend & Strength read — each adds independent evidence.

Overnight risk note: there is no live stop-loss order protecting an overnight position while the market is
closed — the stop shown is the level to act on the moment the market reopens, not a guaranteed exit price, since
a gap can open beyond it. For a deeper institutional-ownership cross-check before sizing, Command Center →
Smart Money Activity shows this ticker's fund/ETF holdings trend — a complementary, slower-moving read.`

const BTST_LAYMAN = `In plain English — no jargon

Think about how a stock behaves in the last hour before the market closes. If big buyers are stepping in and
absorbing everything sellers throw at them, the stock tends to close right near its high for the day — that's a
sign of genuine conviction, not just a random up day. This tool looks for exactly that closing-strength
signature, then checks several independent things before trusting it: is the stock in a genuine uptrend already
(not catching a falling knife), did real volume back the move, did it beat the overall market today, did buyers
pay up above the volume-weighted average price, and — critically — did the options market itself show fresh
institutional conviction (a "Long Buildup" in derivatives-speak).

- **BTST (Buy Today, Sell Tomorrow)** — the stock closed strong; buy it today, look to sell tomorrow.
- **STBT (Sell Today, Buy Tomorrow)** — the mirror image: the stock closed weak; short it today (via futures/
  options, since NSE doesn't allow carrying a cash-market short overnight), look to cover tomorrow.
- **SIGNAL: NEUTRAL** — the stock closed roughly in the middle of its daily range; no real conviction either way.

The historical follow-through % is the one truly unique check here: this tool actually looks back at how often
THIS SPECIFIC STOCK has followed through the next day after showing this same closing-strength pattern before —
not a generic rule, a real track record on the exact name you're looking at.

Because this is an overnight trade, there's no stop-loss order sitting in the market protecting you while it's
closed — if bad news hits overnight, the stock can gap down (or up, for STBT) past your stop before you can
react. Size positions with that risk in mind.`

interface BtstSavedReportSummary {
  id: number
  name: string
  asset_class: string
  created_at: string
  summary?: {
    entry_count?: number
    btst_count?: number
    stbt_count?: number
    scanned?: number
  }
}

interface BtstBgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: Record<string, unknown>
  meta?: { asset_class?: string }
  created_at?: number
}

function BtstPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [error, setError] = useState('')
  const [minClv, setMinClv] = useState(0.65)
  const [minRr, setMinRr] = useState(1.3)
  const [checkOiBuildup, setCheckOiBuildup] = useState(true)
  const [showCharts, setShowCharts] = useState(false)
  const [furtherAnalysis, setFurtherAnalysis] = useState<string[]>([])

  const [runInBackground, setRunInBackground] = useState(false)
  const [bgReportName, setBgReportName] = useState('')
  const [bgJobIds, setBgJobIds] = useState<string[]>([])
  const [bgError, setBgError] = useState('')
  const [bgMsg, setBgMsg] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const handledDoneRef = useRef<Set<string>>(new Set())
  const queryClient = useQueryClient()

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])
  const toggleFurtherAnalysis = (value: string) =>
    setFurtherAnalysis((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))

  const cfgOverrides = () => ({
    min_clv: minClv,
    min_rr: minRr,
    check_oi_buildup: checkOiBuildup,
    further_analysis: furtherAnalysis,
  })

  const btstReportsQuery = useQuery({ queryKey: ['btst-reports'], queryFn: fetchBtstReports })
  const btstReports = ((btstReportsQuery.data as { reports?: BtstSavedReportSummary[] } | undefined)?.reports) ?? []

  const btstRunningJobsQuery = useQuery({
    queryKey: ['btst-jobs-running'],
    queryFn: () => fetchBtstJobs('running'),
    refetchInterval: 2000,
  })
  const btstRecentJobsQuery = useQuery({ queryKey: ['btst-jobs-recent'], queryFn: () => fetchBtstJobs('all') })
  const btstRecentJobs = ((btstRecentJobsQuery.data as { jobs?: BtstBgJobStatus[] } | undefined)?.jobs) ?? []
  const btstRecentFinished = btstRecentJobs.filter((j) => j.status !== 'running').slice(0, 8)

  useEffect(() => {
    const serverJobs = ((btstRunningJobsQuery.data as { jobs?: BtstBgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [btstRunningJobsQuery.data])

  const btstJobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['btst-job', id],
      queryFn: () => fetchBtstJob(id) as Promise<BtstBgJobStatus>,
      refetchInterval: (q: { state: { data?: BtstBgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })
  const btstJobById = (() => {
    const map = new Map<string, BtstBgJobStatus>()
    btstJobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as BtstBgJobStatus)
    })
    return map
  })()

  useEffect(() => {
    let changed = false
    const stillRunning: string[] = []
    for (const id of bgJobIds) {
      const job = btstJobById.get(id)
      if (!job || job.status === 'running') {
        stillRunning.push(id)
        continue
      }
      if (!handledDoneRef.current.has(id)) {
        handledDoneRef.current.add(id)
        changed = true
        if (job.status === 'done' && job.report_id) {
          setViewedReportId(job.report_id)
          setBgMsg(`Background report saved${job.name ? `: ${job.name}` : ''}.`)
        } else if (job.status === 'done') {
          setBgMsg(job.name ? `Background run "${job.name}" finished.` : 'Background run finished.')
        } else if (job.status === 'error') {
          setBgError(job.error || `Background job failed: ${job.name || id}`)
        }
      }
    }
    if (stillRunning.length !== bgJobIds.length) setBgJobIds(stillRunning)
    if (changed) {
      queryClient.invalidateQueries({ queryKey: ['btst-reports'] })
      queryClient.invalidateQueries({ queryKey: ['btst-jobs-running'] })
      queryClient.invalidateQueries({ queryKey: ['btst-jobs-recent'] })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bgJobIds, btstJobById, queryClient])

  const btstOngoingBg = bgJobIds
    .map((id) => btstJobById.get(id))
    .filter((j): j is BtstBgJobStatus => !!j && j.status === 'running')
  const btstServerRunning = ((btstRunningJobsQuery.data as { jobs?: BtstBgJobStatus[] } | undefined)?.jobs) ?? []
  const btstOngoingMap = new Map<string, BtstBgJobStatus>()
  for (const j of [...btstServerRunning, ...btstOngoingBg]) {
    if (j.status === 'running') btstOngoingMap.set(j.job_id, j)
  }
  const btstOngoingList = Array.from(btstOngoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const btstReportDetailQuery = useQuery({
    queryKey: ['btst-report', viewedReportId],
    queryFn: () => fetchBtstReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const btstStartBgMutation = useMutation({
    mutationFn: startBtstJob,
    onSuccess: (data) => {
      const id = data.job_id as string
      setBgError('')
      setBgMsg(`Background run started${data.name ? `: ${data.name}` : ''}.`)
      setBgReportName('')
      setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
      queryClient.invalidateQueries({ queryKey: ['btst-jobs-running'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const btstSaveReportMutation = useMutation({
    mutationFn: saveBtstReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['btst-reports'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const btstDeleteReportMutation = useMutation({
    mutationFn: deleteBtstReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['btst-reports'] })
    },
  })

  useEffect(() => {
    setViewedReportId(null)
    setBgError('')
    setBgMsg('')
    setRunInBackground(false)
  }, [assetClass])

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runProTradeBtst({
        tickers: picker.tickers,
        asset_class: assetClass,
        ...cfgOverrides(),
      })
    },
    onSuccess: () => { setError(''); setViewedReportId(null) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const startBtstBackgroundRun = () => {
    if (!picker.tickers.length) {
      setBgError('Select at least one ticker')
      return
    }
    if (!bgReportName.trim()) {
      setBgError('Enter a report name for the background run')
      return
    }
    setBgError('')
    setBgMsg('')
    btstStartBgMutation.mutate({
      tickers: picker.tickers,
      asset_class: assetClass,
      config: cfgOverrides(),
      run_in_background: true,
      report_name: bgReportName.trim(),
    })
  }

  const btstViewedReport = btstReportDetailQuery.data as { name?: string; payload?: Record<string, unknown>; created_at?: string; error?: string } | undefined
  const data: Record<string, unknown> | undefined =
    viewedReportId != null ? btstViewedReport?.payload : (runMut.data as Record<string, unknown> | undefined)

  const askContext = data ? buildAskContext('Buy Today Sell Tomorrow', data) : ''

  return (
    <div>
      <PageHeader
        title="Buy Today Sell Tomorrow"
        description="BTST / STBT — closing-strength signature confirmed by trend, volume, relative strength, VWAP, options OI buildup & this ticker's own historical edge"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="In plain English — how to interpret your results" defaultOpen>
          {BTST_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="Overview">{BTST_OVERVIEW}</CollapsibleSection>
        <CollapsibleSection title="How the confidence score is built">{BTST_RULES}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSET_CLASSES.map((ac) => (
            <Chip
              key={ac.id}
              selected={assetClass === ac.id}
              onClick={() => {
                setAssetClass(ac.id)
                setPicker({ tickers: [], durations: [] })
                setError('')
              }}
            >
              {ac.label}
            </Chip>
          ))}
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Options OI-buildup and the "STBT needs F&amp;O" execution note only apply to India — the core closing-
          strength read (CLV, trend, volume, relative strength, VWAP, historical edge) works across all 4 asset
          classes, benchmarked against Nifty 50 / SPY / Bitcoin.
        </p>

        <AssetClassTickerPicker
          key={assetClass}
          assetClass={assetClass}
          showDurations={false}
          defaultSelectCount={15}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-2xl gap-3 sm:grid-cols-3">
          <FormField label="Min CLV (closing-strength threshold)">
            <Input
              type="number"
              step="0.05"
              min={0.5}
              max={0.95}
              value={minClv}
              onChange={(e) => setMinClv(Number(e.target.value) || 0.65)}
            />
          </FormField>
          <FormField label="Min reward:risk">
            <Input
              type="number"
              step="0.1"
              min={0.5}
              max={5}
              value={minRr}
              onChange={(e) => setMinRr(Number(e.target.value) || 1.3)}
            />
          </FormField>
          <FormField label="Options OI-buildup check">
            <Select value={checkOiBuildup ? 'on' : 'off'} onChange={(e) => setCheckOiBuildup(e.target.value === 'on')}>
              <option value="on">On (India F&amp;O names)</option>
              <option value="off">Off</option>
            </Select>
          </FormField>
        </div>

        <div className="mt-4">
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-slate-500">
            Further analysis (optional — pick any to add more confidence)
          </p>
          <div className="flex flex-wrap gap-2">
            {BTST_FURTHER_ANALYSIS_OPTIONS.map((opt) => (
              <Chip key={opt.value} selected={furtherAnalysis.includes(opt.value)} onClick={() => toggleFurtherAnalysis(opt.value)}>
                {opt.label}
              </Chip>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-slate-500">
            Each selected check runs its own live read on the ticker and adds independent confirmation on top of
            the core BTST/STBT read — the same dispatcher built for Trading Hub → Intra-Hedging.
          </p>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || !picker.tickers.length || runInBackground}>
            {runMut.isPending ? 'Scanning…' : `Scan BTST / STBT (${picker.tickers.length})`}
          </Button>
        </div>
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}

        <div className="mt-4 space-y-3 rounded-xl border border-slate-800/60 bg-slate-900/30 p-3">
          <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-300">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-800 text-teal-500"
              checked={runInBackground}
              onChange={(e) => setRunInBackground(e.target.checked)}
            />
            <span>
              <span className="font-medium text-slate-100">Run in background</span>
              <span className="mt-0.5 block text-xs text-slate-500">
                Name the run — it keeps going if you leave this page, then auto-saves into Saved reports below
                when done. You can start several background runs at once.
              </span>
            </span>
          </label>
          {runInBackground && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[16rem] flex-1">
                <FormField label="Report name">
                  <Input
                    value={bgReportName}
                    onChange={(e) => setBgReportName(e.target.value)}
                    placeholder={`BTST · ${new Date().toLocaleDateString()}`}
                    maxLength={200}
                  />
                </FormField>
              </div>
              <Button onClick={startBtstBackgroundRun} disabled={btstStartBgMutation.isPending}>
                {btstStartBgMutation.isPending ? 'Starting…' : 'Start background run'}
              </Button>
            </div>
          )}
          {bgError && <Alert type="error">{bgError}</Alert>}
          {bgMsg && <Alert type="success">{bgMsg}</Alert>}
        </div>
      </Card>

      {btstOngoingList.length > 0 && (
        <Card className="mb-4">
          <p className="mb-2 text-sm font-medium text-slate-200">Background runs in progress ({btstOngoingList.length})</p>
          <div className="space-y-2">
            {btstOngoingList.map((j) => (
              <div key={j.job_id} className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>{j.name || j.job_id}</span>
                  <span>{Math.round((j.progress ?? 0) * 100)}%</span>
                </div>
                {j.progress_note && <p className="mt-1 text-[11px] text-slate-500">{j.progress_note}</p>}
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                  <div className="h-full bg-amber-500 transition-all" style={{ width: `${Math.round((j.progress ?? 0) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {btstRecentFinished.length > 0 && (
        <Card className="mb-4">
          <p className="mb-2 text-sm font-medium text-slate-200">Recent background runs</p>
          <div className="space-y-1.5">
            {btstRecentFinished.map((j) => (
              <button
                key={j.job_id}
                type="button"
                disabled={!(j.status === 'done' && j.report_id)}
                onClick={() => j.report_id && setViewedReportId(j.report_id)}
                className="flex w-full items-center justify-between rounded-lg border border-slate-800/60 bg-slate-900/30 px-2.5 py-2 text-left text-xs text-slate-300 hover:bg-slate-800/40 disabled:cursor-default disabled:hover:bg-slate-900/30"
              >
                <span>{j.name || j.job_id}</span>
                {j.status === 'error' ? (
                  <span className="text-rose-400">Failed{j.error ? `: ${j.error.slice(0, 60)}` : ''}</span>
                ) : j.report_id ? (
                  <span className="text-emerald-400">Saved</span>
                ) : (
                  <span className="text-slate-500">Done (not saved)</span>
                )}
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card className="mb-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-medium text-slate-200">Saved reports ({btstReports.length})</p>
          <button
            type="button"
            className="text-[11px] text-slate-500 hover:text-slate-300"
            onClick={() => btstReportsQuery.refetch()}
          >
            Refresh
          </button>
        </div>
        {btstReports.length === 0 ? (
          <p className="text-xs text-slate-500">No saved reports yet.</p>
        ) : (
          <div className="space-y-1.5">
            {btstReports.map((r) => (
              <div
                key={r.id}
                className={`flex items-center justify-between rounded-lg border px-2.5 py-2 text-xs ${
                  viewedReportId === r.id ? 'border-teal-500/50 bg-teal-500/5' : 'border-slate-800/60 bg-slate-900/30'
                }`}
              >
                <button type="button" className="flex-1 text-left text-slate-300 hover:text-white" onClick={() => setViewedReportId(r.id)}>
                  <span className="font-medium">{r.name}</span>
                  <span className="ml-2 text-slate-500">
                    {r.summary?.entry_count ?? 0} actionable ({r.summary?.btst_count ?? 0} BTST / {r.summary?.stbt_count ?? 0} STBT) of {r.summary?.scanned ?? 0} scanned
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (window.confirm(`Delete saved report "${r.name}"?`)) btstDeleteReportMutation.mutate(r.id)
                  }}
                  className="ml-2 text-slate-500 hover:text-rose-400"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Reading closing strength, trend, volume, options OI, and historical follow-through…" />}

      {data && !runMut.isPending && (
        <>
          <Card className="mb-4">
            {viewedReportId != null && (
              <p className="mb-2 text-xs text-slate-500">
                Viewing saved report: <strong className="text-slate-300">{btstViewedReport?.name}</strong>
                {' · '}
                <button type="button" className="text-teal-400 hover:underline" onClick={() => setViewedReportId(null)}>
                  Back to live scan
                </button>
              </p>
            )}
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <BtstPanel data={data} showCharts={showCharts} />
          </Card>

          {viewedReportId == null && (
            <Card className="mb-4">
              {!showSaveForm ? (
                <Button onClick={() => setShowSaveForm(true)}>Save for future reference</Button>
              ) : (
                <div className="flex flex-wrap items-end gap-2">
                  <div className="min-w-[16rem] flex-1">
                    <FormField label="Report name">
                      <Input value={saveName} onChange={(e) => setSaveName(e.target.value)} maxLength={200} />
                    </FormField>
                  </div>
                  <Button
                    onClick={() => saveName.trim() && btstSaveReportMutation.mutate({ name: saveName.trim(), payload: data })}
                    disabled={btstSaveReportMutation.isPending || !saveName.trim()}
                  >
                    {btstSaveReportMutation.isPending ? 'Saving…' : 'Save'}
                  </Button>
                  <Button onClick={() => setShowSaveForm(false)}>Cancel</Button>
                </div>
              )}
              {saveMsg && <Alert type="success">{saveMsg}</Alert>}
            </Card>
          )}

          {askContext && <AskAIPanel context={askContext} section="pro-trade/btst" />}
        </>
      )}
    </div>
  )
}

export default function ProTrade() {
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()

  const PRO_TRADE_TABS: { id: string; label: string }[] = [
    { id: 'volume-profile-ce', label: 'Volume Profile CE' },
    { id: 'volume-profile-poc', label: 'Volume Profile POC' },
    { id: 'pa-volume-profile', label: 'PA - Volume Profile' },
    { id: 'pa-vp-smc', label: 'PA-VP-SMC' },
    { id: 'volume-spread-next-candle', label: 'Volume Spread - Next Candle' },
    { id: 'elliott-wave', label: 'Elliott Wave' },
    { id: 'fibonacci-pro', label: 'Fibonacci Pro' },
    { id: 'bb-mean-reversion', label: 'BB Mean Reversion' },
    { id: 'traffic-light-indicator', label: 'Traffic Light Indicator' },
    { id: 'buy-low-sell-high', label: 'Buy Low Sell High' },
    { id: 'rlb-breakout', label: 'RLB - Breakout' },
    { id: '3-in-1-trade-system', label: '3-in-1 Trade System' },
    { id: 'simple-effective', label: 'Simple Effective' },
    { id: 'bb-rsi-vol', label: 'BB-RSI-VOL' },
    { id: 'ema9-cross', label: '9 EMA Cross' },
    { id: 'ema5-cross', label: '5 EMA Cross' },
    { id: 'ema5-9-cross', label: '5/9 EMA Cross' },
    { id: 'flat-retest', label: 'Flat Retest' },
    { id: 'btst', label: 'Buy Today Sell Tomorrow' },
    { id: 'ticker-chart', label: 'Ticker Chart' },
  ]

  if (!tab) return <Navigate to="/pro-trade/volume-profile-ce" replace />

  let page: ReactNode = null
  if (tab === 'volume-profile-ce') page = <VolumeProfileCePage />
  else if (tab === 'volume-profile-poc') page = <VolumeProfilePocPage />
  else if (tab === 'pa-volume-profile') page = <PaVolumeProfilePage />
  else if (tab === 'pa-vp-smc') page = <PaVpSmcPage />
  else if (tab === 'volume-spread-next-candle') page = <VolumeSpreadNextCandlePage />
  else if (tab === 'elliott-wave') page = <ElliottWavePage />
  else if (tab === 'fibonacci-pro') page = <FibonacciProPage />
  else if (tab === 'bb-mean-reversion') page = <BbMeanReversionPage />
  else if (tab === 'traffic-light-indicator') page = <TrafficLightIndicatorPage />
  else if (tab === 'buy-low-sell-high') page = <BuyLowSellHighPage />
  else if (tab === 'rlb-breakout') page = <RlbBreakoutPage />
  else if (tab === '3-in-1-trade-system') page = <ThreeInOneTradeSystemPage />
  else if (tab === 'simple-effective') page = <SimpleEffectivePage />
  else if (tab === 'bb-rsi-vol') page = <BbRsiVolPage />
  else if (tab === 'ema9-cross') page = <Ema9CrossPage />
  else if (tab === 'ema5-cross') page = <Ema5CrossPage />
  else if (tab === 'ema5-9-cross') page = <Ema59CrossPage />
  else if (tab === 'flat-retest') page = <FlatRetestPage />
  else if (tab === 'btst') page = <BtstPage />
  else if (tab === 'ticker-chart') page = <TickerChartPage />
  else return <Navigate to="/pro-trade/volume-profile-ce" replace />

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {PRO_TRADE_TABS.map((t) => (
          <Chip
            key={t.id}
            selected={tab === t.id}
            onClick={() => navigate(`/pro-trade/${t.id}`)}
          >
            {t.label}
          </Chip>
        ))}
      </div>
      {page}
    </div>
  )
}
