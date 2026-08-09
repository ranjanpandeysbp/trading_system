import { useCallback, useState, type ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { apiErrorMessage, runPredictionAstroFinance, runPredictionPatternAnalogue } from '../api/client'
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
import { PatternAnaloguePanel } from '../components/prediction/PatternAnaloguePanel'
import { AstroFinancePanel } from '../components/prediction/AstroFinancePanel'
import { StrategyDataSourceBar } from '../components/ui/StrategyDataSourceBar'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

const PA_TFS = ['5m', '15m', '30m', '1h', '4h', '1d', '1wk'] as const
const ASSET_CLASSES: { id: AssetClass; label: string }[] = [
  { id: 'india', label: 'India' },
  { id: 'us', label: 'US' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'commodity', label: 'Commodity' },
]

const OVERVIEW = `Pattern Analogue takes the latest N candles on your chosen timeframe as a “template” shape,
searches earlier history (lookback bars or an explicit date range) for the most similar windows,
then measures what happened in the next F bars after each match.

Use it when you want a data-backed answer to: “When price last looked like this, what usually came next?”`

const RULES = `How it works

• Shape = z-scored relative close path over pattern_bars (scale-invariant).
• Similarity = cosine similarity; only matches ≥ min similarity are kept.
• Overlapping historical hits are de-duplicated; live template is excluded from the search.
• Forward outcome = next-bar return, F-bar return, MFE / MAE after each analogue.
• Bias (BUY/SELL/WAIT) comes from the historical forward-return distribution — not a fill guarantee.`

function PatternAnaloguePage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['15m'] })
  const [error, setError] = useState('')
  const [timeframe, setTimeframe] = useState('15m')
  const [patternBars, setPatternBars] = useState(20)
  const [forwardBars, setForwardBars] = useState(5)
  const [searchLookback, setSearchLookback] = useState(500)
  const [searchFrom, setSearchFrom] = useState('')
  const [searchTo, setSearchTo] = useState('')
  const [topN, setTopN] = useState(10)
  const [minSim, setMinSim] = useState(0.82)
  const bg = useAnalysisBackground('prediction', 'pattern_analogue')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: picker.tickers,
    asset_class: assetClass,
    timeframe,
    pattern_bars: patternBars,
    forward_bars: forwardBars,
    search_lookback_bars: searchLookback,
    search_from_date: searchFrom || undefined,
    search_to_date: searchTo || undefined,
    top_n: topN,
    min_similarity: minSim,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!picker.tickers.length) throw new Error('Select at least one ticker')
      return runPredictionPatternAnalogue(buildPayload())
    },
    onSuccess: () => {
      setError('')
      bg.setViewedReportId(null)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Pattern Analogue', data) : ''

  return (
    <div>
      <PageHeader
        title="Pattern Analogue"
        description="Match the latest chart shape to history — see what usually happened next"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="Overview" defaultOpen>
          {OVERVIEW}
        </CollapsibleSection>
        <CollapsibleSection title="Method & rules">{RULES}</CollapsibleSection>
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
          defaultSelectCount={8}
          onChange={handlePickerChange}
        />

        <div className="mt-4 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {PA_TFS.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Pattern bars (current shape)">
            <Input
              type="number"
              min={5}
              max={120}
              value={patternBars}
              onChange={(e) => setPatternBars(Number(e.target.value) || 20)}
            />
          </FormField>
          <FormField label="Forward bars (what next?)">
            <Input
              type="number"
              min={1}
              max={60}
              value={forwardBars}
              onChange={(e) => setForwardBars(Number(e.target.value) || 5)}
            />
          </FormField>
          <FormField label="Search lookback bars">
            <Input
              type="number"
              min={80}
              max={2500}
              value={searchLookback}
              onChange={(e) => setSearchLookback(Number(e.target.value) || 500)}
            />
          </FormField>
          <FormField label="Search from date (optional)">
            <Input type="date" value={searchFrom} onChange={(e) => setSearchFrom(e.target.value)} />
          </FormField>
          <FormField label="Search to date (optional)">
            <Input type="date" value={searchTo} onChange={(e) => setSearchTo(e.target.value)} />
          </FormField>
          <FormField label="Top matches">
            <Input
              type="number"
              min={1}
              max={50}
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value) || 10)}
            />
          </FormField>
          <FormField label="Min similarity (0.5–0.99)">
            <Input
              type="number"
              step="0.01"
              min={0.5}
              max={0.99}
              value={minSim}
              onChange={(e) => setMinSim(Number(e.target.value) || 0.82)}
            />
          </FormField>
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !picker.tickers.length || bg.runInBackground}
          >
            {runMut.isPending
              ? 'Scanning analogues…'
              : `Find pattern analogues (${picker.tickers.length})`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Pattern Analogue · ${new Date().toLocaleDateString()}`}
          onStart={() =>
            bg.startBackground(buildPayload(), () => (!picker.tickers.length ? 'Select at least one ticker' : null))
          }
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && (
        <Loading message="Matching current chart shape against historical windows…" />
      )}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <PatternAnaloguePanel data={data} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="prediction/pattern-analogue" />}
        </>
      )}
    </div>
  )
}

const ASTRO_STRATEGIES: { id: string; label: string }[] = [
  { id: 'lunar_cycle', label: 'Lunar Cycle' },
  { id: 'amavasya_sr', label: 'Amavasya S/R' },
  { id: 'bhadra_timing', label: 'Bhadra Timing' },
  { id: 'transit_gaps', label: 'Transit Gaps' },
  { id: 'trading_calendar', label: 'Trading Calendar' },
]

const ZODIAC_SIGNS = [
  'Aries',
  'Taurus',
  'Gemini',
  'Cancer',
  'Leo',
  'Virgo',
  'Libra',
  'Scorpio',
  'Sagittarius',
  'Capricorn',
  'Aquarius',
  'Pisces',
]

const ASTRO_OVERVIEW = `Astro Finance overlays lunar cycles, Amavasya S/R, Bhadra timing, Mars/Venus gap bias,
and a Muhurat / Ashtakvarga-lite trading calendar on India · US · Crypto · Commodities.

Sources: Harshubh Shah (Vijay Thakkar + Vikas Gupta) and Astrologer Rahul Bhatnagar.
Use as timing confirmation with technical analysis — never as a standalone signal.
Harshubh: Samay Balwan Che (Time is Powerful); master TA first.`

const ASTRO_HOWTO = `How-to (from the videos)

1. Lunar Cycle — Momentum / reversals cluster near Amavasya (New Moon) & Poornima (Full Moon).
2. Amavasya S/R — Mark New-Moon session high/low as permanent S/R; update when broken.
3. Bhadra Timing — Vishti Karana windows during market hours for intraday tops/bottoms.
4. Transit Gaps — Mars/Venus sign ingress ±1 day vs overnight gaps (Gochar).
5. Trading Calendar — Moon-sign favorable days (set your 4+ Ashtakvarga signs), Char/Shubh/Amrit/Labh Muhurat,
   commodity↔planet map (Gold=Sun/Jupiter, Copper=Sun, Crude=Saturn, Silver=Moon).

Pillars: Moon · Rahu · Jupiter · Mercury. 5th house < 28 bindus → trade cautiously.`

function AstroFinancePage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [error, setError] = useState('')
  const [strategy, setStrategy] = useState('lunar_cycle')
  const [lookbackDays, setLookbackDays] = useState(730)
  const [forwardDays, setForwardDays] = useState(3)
  const [strongSigns, setStrongSigns] = useState<string[]>([])
  const bg = useAnalysisBackground('prediction', 'astro_finance')

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])
  const needsTickers = strategy !== 'trading_calendar'

  const buildPayload = () => ({
    strategy,
    tickers: picker.tickers,
    asset_class: assetClass,
    lookback_days: lookbackDays,
    forward_days: forwardDays,
    strong_moon_signs: strongSigns,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (needsTickers && !picker.tickers.length) throw new Error('Select at least one ticker')
      return runPredictionAstroFinance(buildPayload())
    },
    onSuccess: () => {
      setError('')
      bg.setViewedReportId(null)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Astro Finance', data) : ''
  const guideHtml = typeof data?.guide === 'string' ? String(data.guide) : ''

  const toggleSign = (sign: string) => {
    setStrongSigns((prev) => (prev.includes(sign) ? prev.filter((s) => s !== sign) : [...prev, sign]))
  }

  return (
    <div>
      <PageHeader
        title="Astro Finance"
        description="Lunar cycles · Amavasya S/R · Bhadra · Transit gaps · Muhurat calendar — India / US / Crypto / Commodities"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="Overview & sources" defaultOpen>
          {ASTRO_OVERVIEW}
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-400">
            <li>
              <a className="text-blue-400 hover:underline" href="https://www.youtube.com/watch?v=xP-rt9tU79U" target="_blank" rel="noreferrer">
                Harshubh Shah × Vijay Thakkar
              </a>
            </li>
            <li>
              <a className="text-blue-400 hover:underline" href="https://www.youtube.com/watch?v=xZ84XDFInEI" target="_blank" rel="noreferrer">
                Harshubh Shah × Vikas Gupta Show
              </a>
            </li>
            <li>
              <a className="text-blue-400 hover:underline" href="https://www.youtube.com/watch?v=G1WYa0VgA7A" target="_blank" rel="noreferrer">
                Astrologer Rahul Bhatnagar — Ashtakvarga / Muhurat
              </a>
            </li>
          </ul>
        </CollapsibleSection>
        <CollapsibleSection title="How to use each desk">{ASTRO_HOWTO}</CollapsibleSection>
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {ASTRO_STRATEGIES.map((s) => (
            <Chip key={s.id} selected={strategy === s.id} onClick={() => setStrategy(s.id)}>
              {s.label}
            </Chip>
          ))}
        </div>

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

        {needsTickers && (
          <AssetClassTickerPicker
            key={`${assetClass}-${strategy}`}
            assetClass={assetClass}
            showDurations={false}
            defaultSelectCount={assetClass === 'commodity' ? 4 : 6}
            onChange={handlePickerChange}
          />
        )}

        <div className="mt-4 grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {strategy !== 'trading_calendar' && strategy !== 'bhadra_timing' && (
            <>
              <FormField label="Lookback days">
                <Input
                  type="number"
                  min={120}
                  max={2500}
                  value={lookbackDays}
                  onChange={(e) => setLookbackDays(Number(e.target.value) || 730)}
                />
              </FormField>
              {strategy === 'lunar_cycle' && (
                <FormField label="Forward days (post-event)">
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={forwardDays}
                    onChange={(e) => setForwardDays(Number(e.target.value) || 3)}
                  />
                </FormField>
              )}
            </>
          )}
        </div>

        {strategy === 'trading_calendar' && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-slate-400">
              Strong Moon signs (Ashtakvarga 4+ bindus) — leave empty to show all days
            </p>
            <div className="flex flex-wrap gap-2">
              {ZODIAC_SIGNS.map((z) => (
                <Chip key={z} selected={strongSigns.includes(z)} onClick={() => toggleSign(z)}>
                  {z}
                </Chip>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || (needsTickers && !picker.tickers.length) || bg.runInBackground}
          >
            {runMut.isPending ? 'Running Astro desk…' : `Run ${ASTRO_STRATEGIES.find((s) => s.id === strategy)?.label}`}
          </Button>
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`Astro Finance · ${strategy} · ${new Date().toLocaleDateString()}`}
          onStart={() =>
            bg.startBackground(buildPayload(), () =>
              needsTickers && !picker.tickers.length ? 'Select at least one ticker' : null,
            )
          }
        />
        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && <Loading message="Computing lunar / transit overlays…" />}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          {guideHtml && (
            <Card className="mb-4">
              <CollapsibleSection title="Engine guide" defaultOpen={false}>
                {guideHtml}
              </CollapsibleSection>
            </Card>
          )}
          <Card className="mb-4">
            <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass={assetClass} />
            <AstroFinancePanel data={data} />
          </Card>
          {askContext && <AskAIPanel context={askContext} section="prediction/astro-finance" />}
        </>
      )}
    </div>
  )
}

export default function Prediction() {
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()

  const TABS: { id: string; label: string; to?: string }[] = [
    { id: 'pattern-analogue', label: 'Pattern Analogue' },
    { id: 'astro-finance', label: 'Astro Finance' },
    { id: 'market-prediction', label: 'Market Prediction', to: '/options?section=market_prediction' },
  ]

  if (!tab) return <Navigate to="/prediction/pattern-analogue" replace />

  let page: ReactNode = null
  if (tab === 'pattern-analogue') page = <PatternAnaloguePage />
  else if (tab === 'astro-finance') page = <AstroFinancePage />
  else if (tab === 'market-prediction') {
    return <Navigate to="/options?section=market_prediction" replace />
  }
  else return <Navigate to="/prediction/pattern-analogue" replace />

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <Chip
            key={t.id}
            selected={tab === t.id}
            onClick={() => navigate(t.to || `/prediction/${t.id}`)}
          >
            {t.label}
          </Chip>
        ))}
      </div>
      {page}
    </div>
  )
}
