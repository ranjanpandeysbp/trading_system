import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, ExternalLink, Trash2 } from 'lucide-react'
import { Navigate, useParams } from 'react-router-dom'
import {
  apiErrorMessage,
  deleteBtstReport,
  fetchBtstJob,
  fetchBtstJobs,
  fetchBtstReport,
  fetchBtstReports,
  runProTradeBbMeanReversion,
  runProTradeBtst,
  runProTradeElliottWave,
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
import { BtstPanel } from '../components/pro-trade/BtstPanel'
import { ChartsToggle } from '../components/pro-trade/ChartsToggle'
import { ElliottWavePanel } from '../components/pro-trade/ElliottWavePanel'
import { PaVolumeProfilePanel } from '../components/pro-trade/PaVolumeProfilePanel'
import { PaVpSmcPanel } from '../components/pro-trade/PaVpSmcPanel'
import { VolumeProfileCePanel } from '../components/pro-trade/VolumeProfileCePanel'
import { VolumeProfilePocPanel } from '../components/pro-trade/VolumeProfilePocPanel'
import { VolumeSpreadNextCandlePanel } from '../components/pro-trade/VolumeSpreadNextCandlePanel'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const YOUTUBE = 'https://youtu.be/67u8mdQ8f08'
const CE_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1wk'] as const
const POC_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1wk'] as const
const PA_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1wk'] as const
const SMC_HTF_TFS = ['30m', '1h', '4h', '1d'] as const
const SMC_LTF_TFS = ['5m', '15m', '30m', '1h'] as const
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

function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-medium text-slate-200 hover:bg-slate-800/30"
      >
        {open ? (
          <ChevronDown size={14} className="shrink-0 text-slate-500" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-slate-500" />
        )}
        {title}
      </button>
      {open && (
        <div className="border-t border-slate-800/60 px-3 py-3 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">
          {children}
        </div>
      )}
    </div>
  )
}

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
            <ElliottWavePanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/elliott-wave" />}
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
            <BbMeanReversionPanel data={data} showCharts={showCharts} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="pro-trade/bb-mean-reversion" />}
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
  if (!tab) return <Navigate to="/pro-trade/volume-profile-ce" replace />
  if (tab === 'volume-profile-ce') return <VolumeProfileCePage />
  if (tab === 'volume-profile-poc') return <VolumeProfilePocPage />
  if (tab === 'pa-volume-profile') return <PaVolumeProfilePage />
  if (tab === 'pa-vp-smc') return <PaVpSmcPage />
  if (tab === 'volume-spread-next-candle') return <VolumeSpreadNextCandlePage />
  if (tab === 'elliott-wave') return <ElliottWavePage />
  if (tab === 'bb-mean-reversion') return <BbMeanReversionPage />
  if (tab === 'btst') return <BtstPage />
  return <Navigate to="/pro-trade/volume-profile-ce" replace />
}
