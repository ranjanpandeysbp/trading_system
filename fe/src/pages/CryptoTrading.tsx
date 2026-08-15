import { useCallback, useState, type ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { apiErrorMessage, runCryptoMultibaggerReversal, runCryptoAdvanceBbReversal, runCryptoEmaCrossover, runCryptoSupertrend } from '../api/client'
import {
  AssetClassTickerPicker,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { MultibaggerReversalPanel } from '../components/crypto-trading/MultibaggerReversalPanel'
import { AdvanceBbReversalPanel } from '../components/crypto-trading/AdvanceBbReversalPanel'
import { EmaCrossoverPanel } from '../components/crypto-trading/EmaCrossoverPanel'
import { SupertrendPanel } from '../components/crypto-trading/SupertrendPanel'
import { ChartsToggle } from '../components/pro-trade/ChartsToggle'
import { StrategyDataSourceBar } from '../components/ui/StrategyDataSourceBar'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

const HOW_TO = `How to use Multibagger Reversal

1. Click Scan movers — the desk pulls CoinDCX USDT pairs with |24h| ≥ 40% (default).
2. Optionally pick specific crypto tickers instead (still checked against the 24h filter).
3. On 5m: EMA 280 (or 300) + SuperTrend (10, 3).
4. SHORT only when price is below the EMA AND SuperTrend turns RED.
5. Exit when SuperTrend turns GREEN. Target = −10% of entry price.
6. Research only — not financial advice.`

const OVERVIEW = `Multibagger Reversal — SHORT fade

Universe: coins that moved ≥40% (abs) in the last 24 hours (CoinDCX).
Indicators: EMA 280 + SuperTrend (10, 3) on the 5-minute chart.
Entry: close below EMA AND SuperTrend flips RED → SHORT.
Stop / exit: SuperTrend turns GREEN (reference SL = ST line).
Target: 10% of the coin price (entry × 0.90).`

const LAYMAN = `In plain English

Find coins that went vertical in the last day. Wait until price slips under the long EMA and the SuperTrend paints red — then look for a short toward a 10% drop. If SuperTrend flips back to green, get out.`

function MultibaggerReversalPage() {
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['5m'] })
  const [error, setError] = useState('')
  const [threshold, setThreshold] = useState(40)
  const [emaPeriod, setEmaPeriod] = useState<280 | 300>(280)
  const [maxCandidates, setMaxCandidates] = useState(40)
  const [showCharts, setShowCharts] = useState(true)
  const [useCustomTickers, setUseCustomTickers] = useState(false)

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: useCustomTickers ? picker.tickers : [],
    move_threshold_pct: threshold,
    ema_period: emaPeriod,
    max_candidates: maxCandidates,
    target_pct: 10,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (useCustomTickers && !picker.tickers.length) {
        throw new Error('Select at least one crypto ticker, or scan all movers')
      }
      return runCryptoMultibaggerReversal(buildPayload())
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Record<string, unknown> | undefined
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="Multibagger Reversal"
        description="≥40% 24h movers · 5m EMA + SuperTrend (10,3) · SHORT below EMA on RED flip · exit on GREEN · −10% target"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={HOW_TO}>
          {HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          <Chip selected={!useCustomTickers} onClick={() => setUseCustomTickers(false)}>
            Auto-scan 24h movers
          </Chip>
          <Chip selected={useCustomTickers} onClick={() => setUseCustomTickers(true)}>
            Pick tickers
          </Chip>
        </div>

        {useCustomTickers && (
          <AssetClassTickerPicker
            key="crypto"
            assetClass="crypto"
            showDurations={false}
            defaultSelectCount={15}
            onChange={handlePickerChange}
          />
        )}

        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-slate-400">EMA period (5m)</p>
          <div className="flex flex-wrap gap-2">
            <Chip selected={emaPeriod === 280} onClick={() => setEmaPeriod(280)}>
              EMA 280
            </Chip>
            <Chip selected={emaPeriod === 300} onClick={() => setEmaPeriod(300)}>
              EMA 300
            </Chip>
          </div>
        </div>

        <div className="mt-4 grid max-w-xl gap-3 sm:grid-cols-2">
          <FormField label="Min |24h| move %">
            <Input
              type="number"
              min={20}
              max={100}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value) || 40)}
            />
          </FormField>
          <FormField label="Max movers to scan">
            <Input
              type="number"
              min={5}
              max={80}
              value={maxCandidates}
              onChange={(e) => setMaxCandidates(Number(e.target.value) || 40)}
            />
          </FormField>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            {runMut.isPending
              ? 'Scanning CoinDCX movers + 5m setups…'
              : useCustomTickers
                ? `Scan Multibagger (${picker.tickers.length} tickers)`
                : `Scan Multibagger movers (≥${threshold}%)`}
          </Button>
        </div>

        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Finding ≥40% 24h coins · checking EMA + SuperTrend on 5m…" />}

      {data && !runMut.isPending && (
        <Card className="mb-4">
          <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass="crypto" />
          {data.error != null && (
            <Alert type="error">{String(data.error)}</Alert>
          )}
          <MultibaggerReversalPanel data={data} showCharts={showCharts} />
        </Card>
      )}
    </div>
  )
}

const BB_HOW_TO = `How to use Advance BB Reversal

1. Scan top CoinDCX pairs (or pick tickers) on the 30-minute chart.
2. SHORT: price outside UPPER BB → next candle closes inside → target LOWER BB.
3. LONG: price outside LOWER BB → next candle closes inside → target UPPER BB.
4. Money plan: size so stop risk ≈ ₹200 and reward ≈ ₹600 (1:3).
5. Avoid bad trades: go with trend · short near resistance · long near support.
6. Claimed accuracy ~80% with filters — research only, not advice.`

const BB_OVERVIEW = `Advance BB Reversal — 30m · ~80%

SHORT: outside UPPER BB → close inside → SHORT → Lower BB
LONG: outside LOWER BB → close inside → LONG → Upper BB
SL/TGT money: ₹200 / ₹600
Filters: with-trend (EMA20) · short near resistance · long near support`

const BB_LAYMAN = `In plain English

Wait for price to poke outside a Bollinger Band, then close back inside on the next candle. Trade toward the opposite band. Size the position so you only risk about ₹200 to make about ₹600. Prefer shorts near resistance and longs near support, and don't fade a strong trend.`

function AdvanceBbReversalPage() {
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['30m'] })
  const [error, setError] = useState('')
  const [side, setSide] = useState<'long' | 'short' | 'both'>('both')
  const [requireTrend, setRequireTrend] = useState(true)
  const [requireSr, setRequireSr] = useState(true)
  const [maxTickers, setMaxTickers] = useState(30)
  const [showCharts, setShowCharts] = useState(true)
  const [useCustomTickers, setUseCustomTickers] = useState(false)

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: useCustomTickers ? picker.tickers : [],
    timeframe: '30m',
    side,
    require_trend: requireTrend,
    require_sr: requireSr,
    max_tickers: maxTickers,
    risk_inr: 200,
    reward_inr: 600,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (useCustomTickers && !picker.tickers.length) {
        throw new Error('Select at least one crypto ticker, or scan top pairs')
      }
      return runCryptoAdvanceBbReversal(buildPayload())
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Record<string, unknown> | undefined
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="Advance BB Reversal"
        description="30m BB pierce→inside · opposite-band target · ₹200 SL / ₹600 TGT · with-trend + S/R · ~80%"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={BB_HOW_TO}>
          {BB_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {BB_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {BB_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
          <Chip selected={!useCustomTickers} onClick={() => setUseCustomTickers(false)}>
            Auto-scan top CoinDCX
          </Chip>
          <Chip selected={useCustomTickers} onClick={() => setUseCustomTickers(true)}>
            Pick tickers
          </Chip>
        </div>

        {useCustomTickers && (
          <AssetClassTickerPicker
            key="crypto-bb"
            assetClass="crypto"
            showDurations={false}
            defaultSelectCount={15}
            onChange={handlePickerChange}
          />
        )}

        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-slate-400">Side</p>
          <div className="flex flex-wrap gap-2">
            <Chip selected={side === 'both'} onClick={() => setSide('both')}>Long & short</Chip>
            <Chip selected={side === 'long'} onClick={() => setSide('long')}>Long only</Chip>
            <Chip selected={side === 'short'} onClick={() => setSide('short')}>Short only</Chip>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Chip selected={requireTrend} onClick={() => setRequireTrend(true)}>Require with-trend</Chip>
          <Chip selected={!requireTrend} onClick={() => setRequireTrend(false)}>Trend optional</Chip>
          <Chip selected={requireSr} onClick={() => setRequireSr(true)}>Require S/R</Chip>
          <Chip selected={!requireSr} onClick={() => setRequireSr(false)}>S/R optional</Chip>
        </div>

        {!useCustomTickers && (
          <div className="mt-4 max-w-xs">
            <FormField label="Max pairs to scan">
              <Input
                type="number"
                min={5}
                max={80}
                value={maxTickers}
                onChange={(e) => setMaxTickers(Number(e.target.value) || 30)}
              />
            </FormField>
          </div>
        )}

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            {runMut.isPending
              ? 'Scanning 30m BB re-entries…'
              : useCustomTickers
                ? `Scan BB Reversal (${picker.tickers.length})`
                : `Scan BB Reversal (top ${maxTickers})`}
          </Button>
        </div>

        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Checking 30m Bollinger pierce → close inside · trend · S/R…" />}

      {data && !runMut.isPending && (
        <Card className="mb-4">
          <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass="crypto" />
          {data.error != null && <Alert type="error">{String(data.error)}</Alert>}
          <AdvanceBbReversalPanel data={data} showCharts={showCharts} />
        </Card>
      )}
    </div>
  )
}

const EMA_COINS = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'BNB-USDT'] as const

const EMA_PRESETS = [
  { coin: 'BTCUSDT', tf: '30m', fast: 9, med: 30, sl: 1.5, tp: 6 },
  { coin: 'ETHUSDT', tf: '4h', fast: 10, med: 21, sl: 1.5, tp: 7 },
  { coin: 'SOLUSDT', tf: '4h', fast: 10, med: 21, sl: 3.5, tp: 7 },
  { coin: 'XRPUSDT', tf: '1h', fast: 10, med: 26, sl: 1.5, tp: 7 },
  { coin: 'BNBUSDT', tf: '4h', fast: 9, med: 30, sl: 2.5, tp: 7 },
] as const

const EMA_HOW_TO = `How to use EMA Crossover

1. Default scan covers BTC, ETH, SOL, XRP, BNB — each on its own preset TF / EMAs / SL% / TP%.
2. LONG when fast EMA crosses above medium; SHORT when fast crosses below medium.
3. Stop and target are fixed % from entry (per coin table).
4. Optionally pick your own tickers (non-presets fall back to BTC-style defaults).
5. Research only — not financial advice.`

const EMA_OVERVIEW = `EMA Crossover — per-coin presets

| Coin | TF | Fast | Med | SL% | TP% |
|------|-----|------|-----|-----|-----|
| BTCUSDT | 30m | 9 | 30 | 1.5 | 6 |
| ETHUSDT | 4h | 10 | 21 | 1.5 | 7 |
| SOLUSDT | 4h | 10 | 21 | 3.5 | 7 |
| XRPUSDT | 1h | 10 | 26 | 1.5 | 7 |
| BNBUSDT | 4h | 9 | 30 | 2.5 | 7 |

Fast × above Medium → LONG · Fast × below Medium → SHORT`

const EMA_LAYMAN = `In plain English

Each major has its own chart speed and EMA pair. When the faster average flips above the slower one, look for a buy; when it flips under, look for a sell. Stops and targets are fixed percentages from entry — e.g. BTC uses 1.5% stop and 6% target on the 30m chart.`

function EmaCrossoverPage() {
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [...EMA_COINS], durations: ['30m'] })
  const [error, setError] = useState('')
  const [side, setSide] = useState<'long' | 'short' | 'both'>('both')
  const [showCharts, setShowCharts] = useState(true)
  const [useDefaults, setUseDefaults] = useState(true)

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: useDefaults ? [] : picker.tickers,
    side,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!useDefaults && !picker.tickers.length) {
        throw new Error('Select at least one ticker, or use default majors')
      }
      return runCryptoEmaCrossover(buildPayload())
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Record<string, unknown> | undefined
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="EMA Crossover"
        description="Per-coin TF · EMA fast/medium · SL% / TP% — BTC 30m 9/30 · ETH/SOL 4h 10/21 · XRP 1h 10/26 · BNB 4h 9/30"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={EMA_HOW_TO}>
          {EMA_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {EMA_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {EMA_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-4 overflow-x-auto">
          <p className="mb-2 text-xs font-medium text-slate-400">Show cryptos (desk presets)</p>
          <table className="w-full min-w-[520px] border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-slate-700/80 text-slate-400">
                <th className="py-2 pr-3 font-medium">Coin</th>
                <th className="py-2 pr-3 font-medium">TF</th>
                <th className="py-2 pr-3 font-medium">EMA Fast</th>
                <th className="py-2 pr-3 font-medium">EMA Med</th>
                <th className="py-2 pr-3 font-medium">SL %</th>
                <th className="py-2 font-medium">TP %</th>
              </tr>
            </thead>
            <tbody>
              {EMA_PRESETS.map((row) => (
                <tr key={row.coin} className="border-b border-slate-800/60 text-slate-200">
                  <td className="py-1.5 pr-3 font-medium text-white">{row.coin}</td>
                  <td className="py-1.5 pr-3">{row.tf}</td>
                  <td className="py-1.5 pr-3">{row.fast}</td>
                  <td className="py-1.5 pr-3">{row.med}</td>
                  <td className="py-1.5 pr-3 text-rose-300">{row.sl}</td>
                  <td className="py-1.5 text-emerald-300">{row.tp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mb-3 flex flex-wrap gap-2">
          <Chip selected={useDefaults} onClick={() => setUseDefaults(true)}>
            Majors (BTC ETH SOL XRP BNB)
          </Chip>
          <Chip selected={!useDefaults} onClick={() => setUseDefaults(false)}>
            Pick tickers
          </Chip>
        </div>

        {!useDefaults && (
          <AssetClassTickerPicker
            key="crypto-ema"
            assetClass="crypto"
            showDurations={false}
            defaultSelectCount={5}
            onChange={handlePickerChange}
          />
        )}

        <div className="mt-3">
          <p className="mb-2 text-xs font-medium text-slate-400">Side</p>
          <div className="flex flex-wrap gap-2">
            <Chip selected={side === 'both'} onClick={() => setSide('both')}>Long & short</Chip>
            <Chip selected={side === 'long'} onClick={() => setSide('long')}>Long only</Chip>
            <Chip selected={side === 'short'} onClick={() => setSide('short')}>Short only</Chip>
          </div>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            {runMut.isPending
              ? 'Scanning per-coin EMA presets…'
              : useDefaults
                ? 'Scan EMA Crossover (5 majors · presets)'
                : `Scan EMA Crossover (${picker.tickers.length})`}
          </Button>
        </div>

        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Checking per-coin EMA crosses (BTC 30m · ETH/SOL/BNB 4h · XRP 1h)…" />}

      {data && !runMut.isPending && (
        <Card className="mb-4">
          <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass="crypto" />
          {data.error != null && <Alert type="error">{String(data.error)}</Alert>}
          <EmaCrossoverPanel data={data} showCharts={showCharts} />
        </Card>
      )}
    </div>
  )
}

const ST_COINS = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT'] as const

const ST_PRESETS = [
  { coin: 'BTCUSDT', tf: '1h', atr: 25, factor: 6.325, sl: 2.5, tp: 4 },
  { coin: 'ETHUSDT', tf: '1h', atr: 15, factor: 6.325, sl: 2.5, tp: 5 },
  { coin: 'SOLUSDT', tf: '1h', atr: 25, factor: 3.5, sl: 3.5, tp: 7 },
  { coin: 'XRPUSDT', tf: '1h', atr: 10, factor: 2.5, sl: 2.5, tp: 4 },
] as const

const ST_HOW_TO = `How to use SuperTrend (S2 · Archit Trend Flow)

1. Default scan covers BTC, ETH, SOL, XRP — each with its own ATR length, factor, SL%, and TP%.
2. GREEN SuperTrend below price = uptrend → LONG on fresh green flip.
3. RED SuperTrend above price = downtrend → SHORT on fresh red flip.
4. Money stop/target from the preset table; also exit when color flips against you.
5. Research only — not financial advice.`

const ST_OVERVIEW = `SuperTrend — S2 Archit Trend Flow

GREEN below price = UPTREND (LONG). RED above price = DOWNTREND (SHORT).
Uses ATR to auto-adjust for volatility. Color change = trading signal.

| Coin | TF | ATR | Factor | SL% | TP% |
|------|-----|-----|--------|-----|-----|
| BTCUSDT | 1h | 25 | 6.325 | 2.5 | 4 |
| ETHUSDT | 1h | 15 | 6.325 | 2.5 | 5 |
| SOLUSDT | 1h | 25 | 3.5 | 3.5 | 7 |
| XRPUSDT | 1h | 10 | 2.5 | 2.5 | 4 |

TF: 30m or 1h (desk presets use 1h). SL also on opposite color flip.`

const ST_LAYMAN = `In plain English

SuperTrend paints a green line under price when the trend is up, and a red line above price when the trend is down. When it flips green, look for a buy; when it flips red, look for a sell. Each coin uses its own ATR settings and fixed % stop/target.`

function SupertrendPage() {
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [...ST_COINS], durations: ['1h'] })
  const [error, setError] = useState('')
  const [side, setSide] = useState<'long' | 'short' | 'both'>('both')
  const [showCharts, setShowCharts] = useState(true)
  const [useDefaults, setUseDefaults] = useState(true)

  const handlePickerChange = useCallback((v: TickerPickerValue) => setPicker(v), [])

  const buildPayload = () => ({
    tickers: useDefaults ? [] : picker.tickers,
    side,
  })

  const runMut = useMutation({
    mutationFn: () => {
      if (!useDefaults && !picker.tickers.length) {
        throw new Error('Select at least one ticker, or use default majors')
      }
      return runCryptoSupertrend(buildPayload())
    },
    onSuccess: () => setError(''),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = runMut.data as Record<string, unknown> | undefined
  const howItWorks = data?.how_it_works != null ? String(data.how_it_works) : null

  return (
    <div>
      <PageHeader
        title="SuperTrend"
        description="S2 Archit Trend Flow · GREEN flip LONG · RED flip SHORT · per-coin ATR/factor · 1h · % SL/TP"
      />

      <div className="mb-4 space-y-2">
        <CollapsibleSection title="How to use this screen" defaultOpen copyText={ST_HOW_TO}>
          {ST_HOW_TO}
        </CollapsibleSection>
        <CollapsibleSection title="In plain English" defaultOpen>
          {ST_LAYMAN}
        </CollapsibleSection>
        <CollapsibleSection title="How it works — rules" defaultOpen>
          {ST_OVERVIEW}
        </CollapsibleSection>
        {howItWorks && (
          <CollapsibleSection title="Engine how-it-works (from scan)">
            <pre className="whitespace-pre-wrap text-xs text-slate-400">{howItWorks}</pre>
          </CollapsibleSection>
        )}
      </div>

      <Card className="mb-4">
        <div className="mb-4 overflow-x-auto">
          <p className="mb-2 text-xs font-medium text-slate-400">Show cryptos (desk presets)</p>
          <table className="w-full min-w-[560px] border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-slate-700/80 text-slate-400">
                <th className="py-2 pr-3 font-medium">Coin</th>
                <th className="py-2 pr-3 font-medium">TF</th>
                <th className="py-2 pr-3 font-medium">ATR Length</th>
                <th className="py-2 pr-3 font-medium">Factor</th>
                <th className="py-2 pr-3 font-medium">SL %</th>
                <th className="py-2 font-medium">TP %</th>
              </tr>
            </thead>
            <tbody>
              {ST_PRESETS.map((row) => (
                <tr key={row.coin} className="border-b border-slate-800/60 text-slate-200">
                  <td className="py-1.5 pr-3 font-medium text-white">{row.coin}</td>
                  <td className="py-1.5 pr-3">{row.tf}</td>
                  <td className="py-1.5 pr-3">{row.atr}</td>
                  <td className="py-1.5 pr-3">{row.factor}</td>
                  <td className="py-1.5 pr-3 text-rose-300">{row.sl}</td>
                  <td className="py-1.5 text-emerald-300">{row.tp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mb-3 flex flex-wrap gap-2">
          <Chip selected={useDefaults} onClick={() => setUseDefaults(true)}>
            Majors (BTC ETH SOL XRP)
          </Chip>
          <Chip selected={!useDefaults} onClick={() => setUseDefaults(false)}>
            Pick tickers
          </Chip>
        </div>

        {!useDefaults && (
          <AssetClassTickerPicker
            key="crypto-st"
            assetClass="crypto"
            showDurations={false}
            defaultSelectCount={4}
            onChange={handlePickerChange}
          />
        )}

        <div className="mt-3">
          <p className="mb-2 text-xs font-medium text-slate-400">Side</p>
          <div className="flex flex-wrap gap-2">
            <Chip selected={side === 'both'} onClick={() => setSide('both')}>Long & short</Chip>
            <Chip selected={side === 'long'} onClick={() => setSide('long')}>Long only</Chip>
            <Chip selected={side === 'short'} onClick={() => setSide('short')}>Short only</Chip>
          </div>
        </div>

        <div className="mt-3">
          <ChartsToggle checked={showCharts} onChange={setShowCharts} />
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending}>
            {runMut.isPending
              ? 'Scanning SuperTrend flips…'
              : useDefaults
                ? 'Scan SuperTrend (4 majors · presets)'
                : `Scan SuperTrend (${picker.tickers.length})`}
          </Button>
        </div>

        {error && (
          <div className="mt-3">
            <Alert type="error">{error}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Checking SuperTrend color flips on 1h (per-coin ATR/factor)…" />}

      {data && !runMut.isPending && (
        <Card className="mb-4">
          <StrategyDataSourceBar data={data as Record<string, unknown>} assetClass="crypto" />
          {data.error != null && <Alert type="error">{String(data.error)}</Alert>}
          <SupertrendPanel data={data} showCharts={showCharts} />
        </Card>
      )}
    </div>
  )
}

export default function CryptoTrading() {
  const { tab } = useParams()
  const navigate = useNavigate()

  const TABS = [
    { id: 'multibagger-reversal', label: 'Multibagger Reversal' },
    { id: 'advance-bb-reversal', label: 'Advance BB Reversal' },
    { id: 'ema-crossover', label: 'EMA Crossover' },
    { id: 'supertrend', label: 'SuperTrend' },
  ]

  if (!tab) return <Navigate to="/crypto-trading/multibagger-reversal" replace />

  let page: ReactNode = null
  if (tab === 'multibagger-reversal') page = <MultibaggerReversalPage />
  else if (tab === 'advance-bb-reversal') page = <AdvanceBbReversalPage />
  else if (tab === 'ema-crossover') page = <EmaCrossoverPage />
  else if (tab === 'supertrend') page = <SupertrendPage />
  else return <Navigate to="/crypto-trading/multibagger-reversal" replace />

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <Chip
            key={t.id}
            selected={tab === t.id}
            onClick={() => navigate(`/crypto-trading/${t.id}`)}
          >
            {t.label}
          </Chip>
        ))}
      </div>
      {page}
    </div>
  )
}
