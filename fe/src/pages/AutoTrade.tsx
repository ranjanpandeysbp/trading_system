import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Play, Square, RefreshCw, Zap } from 'lucide-react'
import {
  apiErrorMessage,
  fetchAutoTradeSchedule,
  fetchAutoTradeSuggestions,
  runAutoTradeNow,
  startAutoTradeSchedule,
  stopAutoTradeSchedule,
  updateAutoTradeSchedule,
  type AutoTradeSuggestion,
} from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { AddToWatchlistButton } from '../components/watchlist/AddToWatchlistButton'
import { PlaceTradeModal } from '../components/backtester/PlaceTradeModal'

const ASSET_CLASSES: Array<{ value: AutoTradeSuggestion['asset_class']; label: string }> = [
  { value: 'india', label: 'India' },
  { value: 'us', label: 'US' },
  { value: 'crypto', label: 'Crypto' },
  { value: 'commodity', label: 'Commodity' },
]

const STYLES: Array<{ value: AutoTradeSuggestion['style']; label: string }> = [
  { value: 'scalping', label: 'Scalping' },
  { value: 'intraday', label: 'Intraday' },
  { value: 'swing', label: 'Swing' },
  { value: 'investing', label: 'Investing' },
]

const INTERVAL_PRESETS = [
  { label: '1h', minutes: 60 },
  { label: '3h', minutes: 180 },
  { label: '6h', minutes: 360 },
  { label: '12h', minutes: 720 },
  { label: '24h', minutes: 1440 },
]

function fmtDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function actionBadgeClass(action: string): string {
  if (action === 'BUY') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (action === 'SELL') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
}

function gradeBadgeClass(grade: string): string {
  if (grade === 'A') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (grade === 'B') return 'border-blue-500/30 bg-blue-500/10 text-blue-400'
  return 'border-slate-600/50 bg-slate-700/20 text-slate-400'
}

function SuggestionCard({ s }: { s: AutoTradeSuggestion }) {
  const [showReasons, setShowReasons] = useState(false)
  const [trading, setTrading] = useState(false)

  return (
    <Card>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-white">{s.ticker}</p>
          <span className={`mt-1 inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 text-xs font-semibold ${actionBadgeClass(s.action)}`}>
            {s.action}
          </span>
        </div>
        <AddToWatchlistButton ticker={s.ticker} compact />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span className={`inline-flex items-center rounded-lg border px-1.5 py-0.5 font-semibold ${gradeBadgeClass(s.grade)}`}>
          Grade {s.grade}
        </span>
        <span>{s.confidence_pct.toFixed(0)}% confidence</span>
        {s.sl_pct != null && s.tp_pct != null && <span>SL {s.sl_pct.toFixed(1)}% · TP {s.tp_pct.toFixed(1)}%</span>}
      </div>

      <p className="mt-2 text-[12px] leading-relaxed text-slate-300">{s.plain_english}</p>

      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-slate-500">
        <div>
          <p className="uppercase tracking-wide">Entry</p>
          <p className="text-slate-300">{s.entry_price != null ? s.entry_price.toFixed(2) : '—'}</p>
        </div>
        <div>
          <p className="uppercase tracking-wide">Stop</p>
          <p className="text-slate-300">{s.stop_price != null ? s.stop_price.toFixed(2) : '—'}</p>
        </div>
        <div>
          <p className="uppercase tracking-wide">Target</p>
          <p className="text-slate-300">{s.target_price != null ? s.target_price.toFixed(2) : '—'}</p>
        </div>
      </div>

      {s.reasons.length > 0 && (
        <div className="mt-2 border-t border-slate-800/60 pt-2">
          <button
            type="button"
            onClick={() => setShowReasons((v) => !v)}
            className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-300"
          >
            {showReasons ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Raw signal breakdown ({s.reasons.length})
          </button>
          {showReasons && (
            <ul className="mt-1.5 space-y-0.5 text-[11px] text-slate-500">
              {s.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
        </div>
      )}

      {s.action !== 'WAIT' && (
        <Button size="sm" variant="secondary" className="mt-3 w-full" onClick={() => setTrading(true)}>
          Place paper trade
        </Button>
      )}

      {trading && (
        <PlaceTradeModal
          ticker={s.ticker}
          assetClass={s.asset_class}
          strategyLabel={`Auto Trade · ${s.style}`}
          defaultSide={s.action === 'SELL' ? 'sell' : 'buy'}
          defaultPrice={s.entry_price}
          defaultSlPct={s.sl_pct}
          defaultTpPct={s.tp_pct}
          onClose={() => setTrading(false)}
        />
      )}
    </Card>
  )
}

function MethodologyPanel() {
  const [open, setOpen] = useState(true)
  return (
    <Card className="mb-4">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between text-left">
        <h3 className="font-semibold text-white">How Auto Trade works</h3>
        {open ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
      </button>
      {open && (
        <div className="mt-3 space-y-3 text-sm text-slate-400">
          <p>
            Every scheduled run scans a curated, liquid watchlist for each of 4 markets (India, US, Crypto, Commodity) across
            4 trading styles (Scalping, Intraday, Swing, Investing) — 16 buckets in total. It doesn't try to cover every listed
            ticker; an institutional desk works a watchlist, not the whole market.
          </p>
          <div>
            <p className="font-medium text-slate-300">1. Multiple independent engines vote, not just one indicator</p>
            <p>
              For each ticker, several unrelated signal engines (rule-based strategies, Trading Hub confluence engines, and the
              Pro Trade Price-Action + Volume-Profile + Smart-Money engine) each cast a vote on direction. A suggestion only
              forms when enough of them genuinely agree — this is real N-of-M confluence, not a single black-box score.
            </p>
          </div>
          <div>
            <p className="font-medium text-slate-300">2. Fundamentals & ownership flow (India)</p>
            <p>
              For India, Swing and Investing suggestions also fold in screener.in fundamentals and FII/DII/promoter ownership
              trend — agreement between the technical read and the fundamental picture boosts confidence; disagreement pulls it
              down. This data isn't available for US/Crypto/Commodity yet, so those buckets are technical-only.
            </p>
          </div>
          <div>
            <p className="font-medium text-slate-300">3. A trading-judgment layer sits on top of the raw math</p>
            <ul className="ml-4 list-disc space-y-1">
              <li><strong className="text-slate-300">Reward-for-risk floor</strong> — a technically-agreeing setup with poor risk/reward for its style is downgraded to WAIT rather than acted on.</li>
              <li><strong className="text-slate-300">Volatility-sane stops</strong> — a proposed stop that's too tight or too wide for the instrument's real ATR is re-derived from actual volatility instead of trusted blindly.</li>
              <li><strong className="text-slate-300">Momentum-exhaustion guard</strong> — an already-extended move (RSI-overbought long / RSI-oversold short) gets flagged as chase risk rather than presented as clean.</li>
              <li><strong className="text-slate-300">Liquidity floor</strong> — abnormally thin volume skips a ticker for the fast-timeframe buckets, where slippage matters most.</li>
              <li><strong className="text-slate-300">A/B/C quality grade</strong> — confidence, risk/reward, liquidity, and volatility-fit are combined into one simple grade alongside the confidence %.</li>
            </ul>
          </div>
          <p>
            Each card also gets a short plain-English explanation, not just a list of jargon reasons — the raw signal breakdown
            is still there if you want it, collapsed underneath.
          </p>
        </div>
      )}
    </Card>
  )
}

export default function AutoTrade() {
  const qc = useQueryClient()
  const [assetClass, setAssetClass] = useState<AutoTradeSuggestion['asset_class']>('india')
  const [style, setStyle] = useState<AutoTradeSuggestion['style']>('swing')
  const [intervalDraft, setIntervalDraft] = useState<number | null>(null)
  const [error, setError] = useState('')

  const scheduleQuery = useQuery({ queryKey: ['auto-trade-schedule'], queryFn: fetchAutoTradeSchedule, refetchInterval: 30_000 })
  const suggestionsQuery = useQuery({ queryKey: ['auto-trade-suggestions'], queryFn: () => fetchAutoTradeSuggestions(), refetchInterval: 60_000 })

  const schedule = scheduleQuery.data
  const interval = intervalDraft ?? schedule?.interval_minutes ?? 360

  const updateMutation = useMutation({
    mutationFn: updateAutoTradeSchedule,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['auto-trade-schedule'] }); setError('') },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  const startMutation = useMutation({
    mutationFn: startAutoTradeSchedule,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['auto-trade-schedule'] }); setError('') },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  const stopMutation = useMutation({
    mutationFn: stopAutoTradeSchedule,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['auto-trade-schedule'] }); setError('') },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  const runNowMutation = useMutation({
    mutationFn: runAutoTradeNow,
    onSuccess: () => { setError(''); qc.invalidateQueries({ queryKey: ['auto-trade-schedule'] }) },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const suggestions = suggestionsQuery.data?.suggestions ?? []
  const filtered = useMemo(
    () => suggestions.filter((s) => s.asset_class === assetClass && s.style === style),
    [suggestions, assetClass, style],
  )
  const bucketCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const s of suggestions) counts.set(`${s.asset_class}:${s.style}`, (counts.get(`${s.asset_class}:${s.style}`) ?? 0) + 1)
    return counts
  }, [suggestions])

  return (
    <div>
      <PageHeader
        title="Auto Trade"
        description="Automated, institutional-style suggestion engine — scans India, US, Crypto and Commodities across Scalping, Intraday, Swing and Investing every few hours, and shows a ranked BUY/SELL/WAIT shortlist with confidence, SL/TP and a plain-English explanation for each idea."
      />

      <MethodologyPanel />

      <Card className="mb-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="inline-flex items-center gap-2 font-semibold text-white"><Zap size={16} className="text-amber-400" /> Automation</h3>
          {schedule?.enabled ? (
            <Button variant="danger" size="sm" onClick={() => stopMutation.mutate()} disabled={stopMutation.isPending}>
              <Square size={14} /> Stop
            </Button>
          ) : (
            <Button size="sm" onClick={() => startMutation.mutate()} disabled={startMutation.isPending}>
              <Play size={14} /> Start
            </Button>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Run every (minutes)">
            <div className="flex gap-2">
              <Input
                type="number"
                min={15}
                max={1440}
                value={interval}
                onChange={(e) => setIntervalDraft(Number(e.target.value))}
                onBlur={() => intervalDraft != null && updateMutation.mutate({ interval_minutes: intervalDraft })}
              />
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {INTERVAL_PRESETS.map((p) => (
                <button
                  key={p.minutes}
                  type="button"
                  onClick={() => { setIntervalDraft(p.minutes); updateMutation.mutate({ interval_minutes: p.minutes }) }}
                  className={`rounded-full border px-2 py-0.5 text-[11px] ${
                    interval === p.minutes ? 'border-blue-500/50 bg-blue-500/15 text-blue-300' : 'border-slate-700 text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </FormField>
          <FormField label="Next run">
            <p className="pt-2 text-sm text-slate-300">{schedule?.enabled ? fmtDateTime(schedule.next_run_at) : 'Automation stopped'}</p>
          </FormField>
          <FormField label="Last run">
            <p className="pt-2 text-sm text-slate-300">{fmtDateTime(schedule?.last_run_at ?? null)}</p>
          </FormField>
          <FormField label="Last status">
            <p className="pt-2 text-sm text-slate-300">{schedule?.last_status ?? '—'}</p>
          </FormField>
        </div>

        <div className="mt-2 flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => runNowMutation.mutate()} disabled={runNowMutation.isPending}>
            <RefreshCw size={14} className={runNowMutation.isPending ? 'animate-spin' : ''} />
            Run now
          </Button>
        </div>
        {error && <div className="mt-2"><Alert type="error">{error}</Alert></div>}
      </Card>

      <Card className="mb-4">
        <div className="flex flex-wrap gap-1.5">
          {ASSET_CLASSES.map((a) => (
            <button
              key={a.value}
              type="button"
              onClick={() => setAssetClass(a.value)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                assetClass === a.value ? 'border-teal-400 bg-teal-500/10 text-teal-300' : 'border-slate-700 text-slate-400 hover:text-slate-200'
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {STYLES.map((st) => {
            const count = bucketCounts.get(`${assetClass}:${st.value}`) ?? 0
            return (
              <button
                key={st.value}
                type="button"
                onClick={() => setStyle(st.value)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                  style === st.value ? 'border-blue-500/50 bg-blue-500/15 text-blue-300' : 'border-slate-700/80 bg-slate-800/40 text-slate-400 hover:text-slate-200'
                }`}
              >
                {st.label}{count > 0 ? ` (${count})` : ''}
              </button>
            )
          })}
        </div>
      </Card>

      {suggestionsQuery.isLoading && <Loading message="Loading latest Auto Trade suggestions…" />}

      {!suggestionsQuery.isLoading && !suggestions.length && (
        <Card>
          <p className="text-sm text-slate-500">
            No suggestions yet — start automation above, or click "Run now" for an immediate sweep. A full sweep across all
            16 buckets can take several minutes.
          </p>
        </Card>
      )}

      {filtered.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((s) => <SuggestionCard key={s.id} s={s} />)}
        </div>
      )}

      {suggestions.length > 0 && !filtered.length && !suggestionsQuery.isLoading && (
        <Card>
          <p className="text-sm text-slate-500">No suggestions for this asset class / style combination in the latest sweep.</p>
        </Card>
      )}
    </div>
  )
}
