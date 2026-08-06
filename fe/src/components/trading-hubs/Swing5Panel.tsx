import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { apiErrorMessage, runSwing5Scan } from '../../api/client'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../analysis/AnalysisBackground'
import type { AssetClass } from '../command-center/AssetClassTickerPicker'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Alert, Loading } from '../ui/Feedback'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'

const DEFAULT_STRATEGIES = ['breakout', 'uptrend_bounce']

const CURRENCY_BY_ASSET: Record<AssetClass, string> = {
  india: '₹',
  us: '$',
  crypto: '',
  commodity: '$',
}

const _YOUTUBE_URL = 'https://www.youtube.com/shorts/SFCzyK908zI'

interface Swing5Hit {
  ticker: string
  timeframe: string
  price?: number
  confidence_pct?: number
  reasons?: string[]
  risk_note?: string
  live?: {
    direction?: string
    entry_price?: number
    stop_price?: number
    target_price?: number
    sl_pct?: number
    tp_pct?: number
    hold_duration?: string
  }
}

interface Swing5Bucket {
  hits: Swing5Hit[]
  misses: Array<{ ticker: string; timeframe: string; reasons?: string[] }>
  errors: Array<{ ticker: string; timeframe: string; error: string }>
}

interface Swing5Result {
  market?: string
  asset_class?: string
  results?: Record<string, Swing5Bucket>
  error?: string
}

function Explanation() {
  return (
    <details className="mb-4 rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium text-slate-200">
        📖 The 5 strategies — how each one works
      </summary>
      <div className="mt-2 space-y-2 text-xs leading-relaxed text-slate-400">
        <p>
          <a href={_YOUTUBE_URL} target="_blank" rel="noreferrer" className="text-teal-400 hover:underline">
            Video reference
          </a>{' '}
          — five of the best risk-to-reward swing setups, made mechanical here and scanned across India,
          US, Crypto, and Commodities. All five are <strong>long-only</strong> setups, exactly as framed in the source.
        </p>
        <p><strong>1. Breakouts</strong> — a stock pauses its uptrend, consolidates for weeks/months (price contractions), then breaks out because demand exceeds supply. Key tell: the more consecutive contraction legs into the break, the more explosive it tends to be.</p>
        <p><strong>2. Episodic Pivots (Gap and Go)</strong> — price gaps up hugely on volume from a catalyst (earnings, news). Key tell: stronger when the gap clears a major resistance level. These move fast — treat as a shorter, more actively-monitored hold.</p>
        <p><strong>3. Pullbacks</strong> — missed the breakout? Wait for price to retrace to the original breakout level. Key tell: the pullback should happen on <strong>low</strong> volume (little real selling) — that's the safer version of this entry.</p>
        <p><strong>4. Uptrending Bounces</strong> — a multi-week/month uptrend sells off to a moving average or prior support, then a <strong>bullish, high-volume</strong> candle confirms buyers stepped back in.</p>
        <p><strong>5. Bottom Bounces (falling knife)</strong> — a sequence of gap-downs on rising volume, culminating in one final, biggest gap-down that closes <strong>bullish</strong> on huge volume — an institutional capitulation-buying signature. <strong>This is the highest-risk of the five</strong> — a countertrend trade; many falling knives keep falling. Size it smaller than the others.</p>
        <p>Each detected setup gets a confidence %, entry, stop-loss, take-profit (fixed risk:reward), and an expected holding duration. Confidence is a heuristic confluence score, <strong>not</strong> a statistical win probability, and no setup — including the other four — guarantees a profitable outcome. <strong>Research / education only — NOT FINANCIAL ADVICE.</strong></p>
      </div>
    </details>
  )
}

export function Swing5Panel({
  tickers,
  assetClass,
  strategyKeys,
  strategyLabels,
  timeframeOptions,
}: {
  tickers: string[]
  assetClass: AssetClass
  strategyKeys: string[]
  strategyLabels: Record<string, string>
  timeframeOptions: string[]
}) {
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(
    strategyKeys.filter((k) => DEFAULT_STRATEGIES.includes(k)),
  )
  const [selectedTfs, setSelectedTfs] = useState<string[]>(['1d'])
  const [error, setError] = useState('')
  const bg = useAnalysisBackground('trading_hub', 'swing_5_strategies')

  const toggleStrategy = (key: string) =>
    setSelectedStrategies((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
  const toggleTf = (tf: string) =>
    setSelectedTfs((prev) => (prev.includes(tf) ? prev.filter((t) => t !== tf) : [...prev, tf]))

  const mutation = useMutation({
    mutationFn: () => {
      if (!tickers.length) throw new Error('Enter at least one ticker')
      if (!selectedTfs.length) throw new Error('Select at least one timeframe')
      if (!selectedStrategies.length) throw new Error('Check at least one strategy')
      return runSwing5Scan({
        tickers, timeframes: selectedTfs, strategies: selectedStrategies, asset_class: assetClass,
      })
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
  })

  const buildPayload = () => ({
    tickers,
    asset_class: assetClass,
    timeframes: selectedTfs,
    strategies: selectedStrategies,
  })

  const result = (bg.viewedPayload ?? mutation.data) as Swing5Result | undefined
  const currency = CURRENCY_BY_ASSET[assetClass] ?? ''

  return (
    <div>
      <Explanation />

      <div className="mb-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
          Pick one or more strategies to scan ({selectedStrategies.length} selected)
        </p>
        <div className="flex flex-wrap gap-2">
          {strategyKeys.map((key) => (
            <Chip key={key} selected={selectedStrategies.includes(key)} onClick={() => toggleStrategy(key)}>
              {strategyLabels[key] ?? key}
            </Chip>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
          Timeframes to scan — daily is the natural default (weeks/months of history matter for contraction, breakout, and moving-average context)
        </p>
        <div className="flex flex-wrap gap-2">
          {timeframeOptions.map((tf) => (
            <Chip key={tf} selected={selectedTfs.includes(tf)} onClick={() => toggleTf(tf)}>{tf}</Chip>
          ))}
        </div>
      </div>

      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !tickers.length || bg.runInBackground}>
        {mutation.isPending
          ? `Scanning ${selectedStrategies.length} strateg${selectedStrategies.length === 1 ? 'y' : 'ies'}…`
          : `🔍 Scan Swing Setups${tickers.length ? ` (${tickers.length} ticker${tickers.length === 1 ? '' : 's'})` : ''}`}
      </Button>
      <AnalysisBackgroundControls
        bg={bg}
        placeholder={`Swing 5 · ${new Date().toLocaleDateString()}`}
        onStart={() => bg.startBackground(buildPayload(), () => {
          if (!tickers.length) return 'Enter at least one ticker'
          if (!selectedTfs.length) return 'Select at least one timeframe'
          if (!selectedStrategies.length) return 'Check at least one strategy'
          return null
        })}
      />
      <AnalysisBackgroundJobsAndReports bg={bg} />
      {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}

      {mutation.isPending && <div className="mt-4"><Loading message="Scanning strategies across ticker(s)/timeframe(s)…" /></div>}

      {!mutation.isPending && result && (
        <div className="mt-4 space-y-4">
          {result.error && <Alert type="error">{result.error}</Alert>}
          {!result.error && strategyKeys
            .filter((key) => key in (result.results ?? {}))
            .map((key) => (
              <StrategyResults
                key={key}
                label={strategyLabels[key] ?? key}
                bucket={result.results?.[key]}
                currency={currency}
              />
            ))}
        </div>
      )}
    </div>
  )
}

function StrategyResults({ label, bucket, currency }: { label: string; bucket?: Swing5Bucket; currency: string }) {
  const hits = bucket?.hits ?? []
  const misses = bucket?.misses ?? []
  const errors = bucket?.errors ?? []

  return (
    <Card>
      <h4 className="font-medium text-white">
        {label} — <span className="text-emerald-400">{hits.length} setup{hits.length === 1 ? '' : 's'} found</span>
      </h4>
      {!hits.length && (
        <p className="mt-1 text-sm text-slate-500">No qualifying setup right now across the scanned ticker(s)/timeframe(s).</p>
      )}
      <div className="mt-2 space-y-2">
        {hits.map((row, i) => (
          <HitRow key={`${row.ticker}-${row.timeframe}-${i}`} row={row} currency={currency} />
        ))}
      </div>

      {misses.length > 0 && (
        <details className="mt-3 rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium text-slate-400">⚪ No setup — {misses.length}</summary>
          <div className="mt-2 space-y-1">
            {misses.map((m, i) => (
              <p key={i} className="flex items-center gap-2 text-xs text-slate-500">
                <span>· <strong>{m.ticker}</strong> ({m.timeframe}): {(m.reasons ?? ['no setup'])[0]}</span>
                <AddToWatchlistButton ticker={m.ticker} compact />
              </p>
            ))}
          </div>
        </details>
      )}

      {errors.map((e, i) => (
        <p key={i} className="mt-2 text-xs text-amber-500">⚠️ {e.ticker} · {e.timeframe}: {e.error}</p>
      ))}
    </Card>
  )
}

function HitRow({ row, currency }: { row: Swing5Hit; currency: string }) {
  const [open, setOpen] = useState(false)
  const live = row.live ?? {}
  return (
    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="min-w-0 flex-1 text-left text-sm text-slate-200"
        >
          <strong>{row.ticker}</strong> · {row.timeframe} · <span className="text-emerald-400">🟢 LONG</span>
          {' · conf '}{row.confidence_pct}%
          {row.price != null ? ` · price ${currency}${row.price.toLocaleString(undefined, { maximumFractionDigits: 4 })}` : ''}
        </button>
        <AddToWatchlistButton ticker={row.ticker} compact />
        <button type="button" onClick={() => setOpen((o) => !o)} className="shrink-0 text-slate-500">
          {open ? '▲' : '▼'}
        </button>
      </div>
      {open && (
        <div className="space-y-2 border-t border-emerald-500/20 px-3 py-2">
          {row.risk_note && <Alert type="error">{row.risk_note}</Alert>}
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div><p className="text-xs text-slate-500">Entry</p><p className="font-medium text-white">{currency}{live.entry_price}</p></div>
            <div><p className="text-xs text-slate-500">Stop</p><p className="font-medium text-white">{currency}{live.stop_price}</p></div>
            <div><p className="text-xs text-slate-500">Target</p><p className="font-medium text-white">{currency}{live.target_price}</p></div>
            <div><p className="text-xs text-slate-500">SL % / TP %</p><p className="font-medium text-white">-{live.sl_pct}% / +{live.tp_pct}%</p></div>
          </div>
          {live.hold_duration && <p className="text-xs text-slate-400">Expected hold: {live.hold_duration}</p>}
          {(row.reasons ?? []).map((r, i) => (
            <p key={i} className="text-xs text-slate-400">· {r}</p>
          ))}
        </div>
      )}
    </div>
  )
}
