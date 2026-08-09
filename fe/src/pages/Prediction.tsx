import { useCallback, useState, type ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { apiErrorMessage, runPredictionPatternAnalogue } from '../api/client'
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

export default function Prediction() {
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()

  const TABS: { id: string; label: string }[] = [
    { id: 'pattern-analogue', label: 'Pattern Analogue' },
  ]

  if (!tab) return <Navigate to="/prediction/pattern-analogue" replace />

  let page: ReactNode = null
  if (tab === 'pattern-analogue') page = <PatternAnaloguePage />
  else return <Navigate to="/prediction/pattern-analogue" replace />

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <Chip key={t.id} selected={tab === t.id} onClick={() => navigate(`/prediction/${t.id}`)}>
            {t.label}
          </Chip>
        ))}
      </div>
      {page}
    </div>
  )
}
