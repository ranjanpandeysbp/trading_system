import { useCallback, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { apiErrorMessage, runOptionsDeltaNeutral, runOptionsDoubleCalendar } from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import { AssetClassTickerPicker, type TickerPickerValue } from '../components/command-center/AssetClassTickerPicker'
import { DeltaNeutralPanel, DoubleCalendarPanel } from '../components/options/OptionsPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const SECTIONS = [
  { id: 'double_calendar', label: '📅 Double Calendar' },
  { id: 'delta_neutral', label: '🎰 Delta Neutral' },
] as const

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

function CollapsibleSection({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-medium text-slate-200 hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        {title}
      </button>
      {open && <div className="border-t border-slate-800/60 px-3 py-3">{children}</div>}
    </div>
  )
}

export default function Options() {
  const [section, setSection] = useState<SectionId>('double_calendar')
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

  const data = runMutation.data as Record<string, unknown> | undefined
  const askContext = data ? buildAskContext('Double Calendar', data) : ''

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

  const dnData = runDnMutation.data as Record<string, unknown> | undefined
  const dnAskContext = dnData ? buildAskContext('Delta Neutral', dnData) : ''

  return (
    <div>
      <PageHeader title="Options" description="Options income & structuring strategies." />

      <div className="mb-4 flex flex-wrap gap-2">
        {SECTIONS.map(({ id, label }) => (
          <Chip key={id} selected={section === id} onClick={() => setSection(id)}>{label}</Chip>
        ))}
      </div>

      {section === 'double_calendar' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">
            Sell near-term calls/puts, buy longer-dated calls/puts at the same (or wider) strikes — a
            theta-positive, range-bound income spread. Low-IV entry gate, 20-40% take-profit, 30% mental stop.
          </p>

          <CollapsibleSection title="📖 How the Double Calendar works">
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

            <AssetClassTickerPicker key={assetClass} assetClass={assetClass} showDurations onChange={handlePickerChange} />

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

            <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
              {runMutation.isPending ? 'Building…' : '📅 Build Double Calendar'}
            </Button>
            {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
          </Card>

          {runMutation.isPending && <Loading message="Building Double Calendar…" />}

          {data && !runMutation.isPending && (
            <Card>
              <DoubleCalendarPanel
                data={data} stopLoss={-stopLossPct / 100} takeProfitStart={tpStart / 100} takeProfitMax={tpMax / 100}
              />
            </Card>
          )}

          {askContext && !runMutation.isPending && (
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

          <CollapsibleSection title="📖 How Delta-Neutral (Iron Condor / Iron Fly) works">
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

            <AssetClassTickerPicker key={dnAssetClass} assetClass={dnAssetClass} showDurations onChange={handleDnPickerChange} />

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

            <Button className="mt-4" onClick={() => runDnMutation.mutate()} disabled={runDnMutation.isPending}>
              {runDnMutation.isPending ? 'Building…' : '🎯 Build Delta-Neutral Spread'}
            </Button>
            {dnError && <div className="mt-3"><Alert type="error">{dnError}</Alert></div>}
          </Card>

          {runDnMutation.isPending && <Loading message="Building Delta-Neutral spread…" />}

          {dnData && !runDnMutation.isPending && (
            <Card>
              <DeltaNeutralPanel data={dnData} profitTargetPct={dnTpPct / 100} stopLossMultiple={slMultiple} />
            </Card>
          )}

          {dnAskContext && !runDnMutation.isPending && (
            <AskAIPanel context={dnAskContext} section="options/delta_neutral" />
          )}
        </div>
      )}
    </div>
  )
}
