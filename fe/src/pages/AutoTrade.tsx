import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Pencil, Play, Plus, RefreshCw, Square, Trash2, X, Zap } from 'lucide-react'
import {
  apiErrorMessage,
  createAutoTradeSetup,
  deleteAutoTradeSetup,
  fetchAutoTradeSetups,
  fetchAutoTradeSuggestions,
  runAutoTradeSetupNow,
  startAutoTradeSetup,
  stopAutoTradeSetup,
  updateAutoTradeSetup,
  type AutoTradeAssetClass,
  type AutoTradeDirection,
  type AutoTradeSetup,
  type AutoTradeStyle,
  type AutoTradeSuggestion,
} from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { AddToWatchlistButton } from '../components/watchlist/AddToWatchlistButton'
import { PlaceTradeModal } from '../components/backtester/PlaceTradeModal'

const ASSET_CLASSES: Array<{ value: AutoTradeAssetClass; label: string }> = [
  { value: 'india', label: 'India' },
  { value: 'us', label: 'US' },
  { value: 'crypto', label: 'Crypto' },
  { value: 'commodity', label: 'Commodity' },
]

const STYLES: Array<{ value: AutoTradeStyle; label: string }> = [
  { value: 'scalping', label: 'Scalping' },
  { value: 'intraday', label: 'Intraday' },
  { value: 'swing', label: 'Swing' },
  { value: 'investing', label: 'Investing' },
]

const ASSET_CLASS_LABEL: Record<AutoTradeAssetClass, string> = Object.fromEntries(
  ASSET_CLASSES.map((a) => [a.value, a.label]),
) as Record<AutoTradeAssetClass, string>

const STYLE_LABEL: Record<AutoTradeStyle, string> = Object.fromEntries(
  STYLES.map((s) => [s.value, s.label]),
) as Record<AutoTradeStyle, string>

const DIRECTIONS: Array<{ value: AutoTradeDirection; label: string }> = [
  { value: 'both', label: 'Both — long & short' },
  { value: 'long_only', label: 'Long only' },
  { value: 'short_only', label: 'Short only' },
]

const DIRECTION_LABEL: Record<AutoTradeDirection, string> = Object.fromEntries(
  DIRECTIONS.map((d) => [d.value, d.label]),
) as Record<AutoTradeDirection, string>

const INTERVAL_PRESETS = [
  { label: '15m', minutes: 15 },
  { label: '30m', minutes: 30 },
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
    <>
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
    </Card>

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
    </>
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
            Create one or more named setups, each scanning a curated, liquid watchlist for one market (India, US, Crypto, or
            Commodity) and one trading style (Scalping, Intraday, Swing, or Investing) on its own schedule — e.g. "Crypto
            Scalping" every 30 minutes and "India Swing" every 6 hours, run and managed independently. It doesn't try to cover
            every listed ticker; an institutional desk works a watchlist, not the whole market.
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
              For India, Swing and Investing setups also fold in screener.in fundamentals and FII/DII/promoter ownership
              trend — agreement between the technical read and the fundamental picture boosts confidence; disagreement pulls it
              down. This data isn't available for US/Crypto/Commodity yet, so those setups are technical-only.
            </p>
          </div>
          <div>
            <p className="font-medium text-slate-300">3. A trading-judgment layer sits on top of the raw math</p>
            <ul className="ml-4 list-disc space-y-1">
              <li><strong className="text-slate-300">Reward-for-risk floor</strong> — a technically-agreeing setup with poor risk/reward for its style is downgraded to WAIT rather than acted on.</li>
              <li><strong className="text-slate-300">Volatility-sane stops</strong> — a proposed stop that's too tight or too wide for the instrument's real ATR is re-derived from actual volatility instead of trusted blindly.</li>
              <li><strong className="text-slate-300">Momentum-exhaustion guard</strong> — an already-extended move (RSI-overbought long / RSI-oversold short) gets flagged as chase risk rather than presented as clean.</li>
              <li><strong className="text-slate-300">Liquidity floor</strong> — abnormally thin volume skips a ticker for the fast-timeframe setups, where slippage matters most.</li>
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

function CreateSetupModal({ onClose, onCreated }: { onClose: () => void; onCreated: (setup: AutoTradeSetup) => void }) {
  const [name, setName] = useState('')
  const [assetClass, setAssetClass] = useState<AutoTradeAssetClass>('india')
  const [style, setStyle] = useState<AutoTradeStyle>('swing')
  const [direction, setDirection] = useState<AutoTradeDirection>('both')
  const [interval, setIntervalMinutes] = useState(360)
  const [error, setError] = useState('')

  const createMutation = useMutation({
    mutationFn: () =>
      createAutoTradeSetup({
        name: name.trim() || `${ASSET_CLASS_LABEL[assetClass]} ${STYLE_LABEL[style]}`,
        asset_class: assetClass,
        style,
        direction,
        interval_minutes: interval,
      }),
    onSuccess: (setup) => onCreated(setup),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-md overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-white">New Auto Trade setup</h3>
            <button type="button" onClick={onClose} className="text-slate-400 hover:text-white">
              <X size={18} />
            </button>
          </div>

          <FormField label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={`${ASSET_CLASS_LABEL[assetClass]} ${STYLE_LABEL[style]}`} autoFocus />
          </FormField>

          <div className="grid grid-cols-2 gap-3">
            <FormField label="Asset class">
              <Select value={assetClass} onChange={(e) => setAssetClass(e.target.value as AutoTradeAssetClass)}>
                {ASSET_CLASSES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </Select>
            </FormField>
            <FormField label="Style">
              <Select value={style} onChange={(e) => setStyle(e.target.value as AutoTradeStyle)}>
                {STYLES.map((st) => <option key={st.value} value={st.value}>{st.label}</option>)}
              </Select>
            </FormField>
          </div>

          <FormField label="Trade direction">
            <Select value={direction} onChange={(e) => setDirection(e.target.value as AutoTradeDirection)}>
              {DIRECTIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
            </Select>
          </FormField>

          <FormField label="Run every (minutes)">
            <Input type="number" min={15} max={1440} value={interval} onChange={(e) => setIntervalMinutes(Number(e.target.value))} />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {INTERVAL_PRESETS.map((p) => (
                <button
                  key={p.minutes}
                  type="button"
                  onClick={() => setIntervalMinutes(p.minutes)}
                  className={`rounded-full border px-2 py-0.5 text-[11px] ${
                    interval === p.minutes ? 'border-blue-500/50 bg-blue-500/15 text-blue-300' : 'border-slate-700 text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </FormField>

          {error && <Alert type="error">{error}</Alert>}

          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Creating…' : 'Create setup'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}

function EditSetupModal({ setup, onClose, onSaved }: { setup: AutoTradeSetup; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(setup.name)
  const [direction, setDirection] = useState<AutoTradeDirection>(setup.direction)
  const [interval, setIntervalMinutes] = useState(setup.interval_minutes)
  const [error, setError] = useState('')

  const saveMutation = useMutation({
    mutationFn: () =>
      updateAutoTradeSetup(setup.id, {
        name: name.trim() || setup.name,
        direction,
        interval_minutes: interval,
      }),
    onSuccess: () => onSaved(),
    onError: (e) => setError(apiErrorMessage(e)),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-md overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-white">Edit setup</h3>
            <button type="button" onClick={onClose} className="text-slate-400 hover:text-white">
              <X size={18} />
            </button>
          </div>

          <FormField label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </FormField>

          <div className="mb-4 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
            <span className="rounded-full border border-slate-700 px-2 py-0.5">{ASSET_CLASS_LABEL[setup.asset_class]}</span>
            <span className="rounded-full border border-slate-700 px-2 py-0.5">{STYLE_LABEL[setup.style]}</span>
            <span className="italic">market and style can't be changed — create a new setup for a different combination</span>
          </div>

          <FormField label="Trade direction">
            <Select value={direction} onChange={(e) => setDirection(e.target.value as AutoTradeDirection)}>
              {DIRECTIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
            </Select>
          </FormField>

          <FormField label="Run every (minutes)">
            <Input type="number" min={15} max={1440} value={interval} onChange={(e) => setIntervalMinutes(Number(e.target.value))} />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {INTERVAL_PRESETS.map((p) => (
                <button
                  key={p.minutes}
                  type="button"
                  onClick={() => setIntervalMinutes(p.minutes)}
                  className={`rounded-full border px-2 py-0.5 text-[11px] ${
                    interval === p.minutes ? 'border-blue-500/50 bg-blue-500/15 text-blue-300' : 'border-slate-700 text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </FormField>

          {error && <Alert type="error">{error}</Alert>}

          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={() => saveMutation.mutate()} disabled={!name.trim() || saveMutation.isPending}>
              {saveMutation.isPending ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}

function SetupCard({ setup, active, onSelect }: { setup: AutoTradeSetup; active: boolean; onSelect: () => void }) {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)

  const invalidate = () => qc.invalidateQueries({ queryKey: ['auto-trade-setups'] })
  const startMutation = useMutation({ mutationFn: () => startAutoTradeSetup(setup.id), onSuccess: invalidate, onError: (e) => setError(apiErrorMessage(e)) })
  const stopMutation = useMutation({ mutationFn: () => stopAutoTradeSetup(setup.id), onSuccess: invalidate, onError: (e) => setError(apiErrorMessage(e)) })
  const runNowMutation = useMutation({ mutationFn: () => runAutoTradeSetupNow(setup.id), onSuccess: invalidate, onError: (e) => setError(apiErrorMessage(e)) })
  const deleteMutation = useMutation({
    mutationFn: () => deleteAutoTradeSetup(setup.id),
    onSuccess: () => {
      invalidate()
      qc.invalidateQueries({ queryKey: ['auto-trade-suggestions'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  return (
    <>
    <div className={`rounded-xl border p-3 transition ${active ? 'border-teal-400 bg-teal-500/10' : 'border-slate-800/60 bg-slate-900/40 hover:border-slate-700'}`}>
      <button type="button" onClick={onSelect} className="w-full text-left">
        <div className="flex items-center justify-between gap-2">
          <p className="font-medium text-white">{setup.name}</p>
          <span className={`text-xs font-medium ${setup.enabled ? 'text-emerald-400' : 'text-slate-500'}`}>
            {setup.enabled ? 'Running' : 'Stopped'}
          </span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] text-slate-400">
          <span className="rounded-full border border-slate-700 px-2 py-0.5">{ASSET_CLASS_LABEL[setup.asset_class]}</span>
          <span className="rounded-full border border-slate-700 px-2 py-0.5">{STYLE_LABEL[setup.style]}</span>
          {setup.direction !== 'both' && (
            <span className="rounded-full border border-blue-500/40 bg-blue-500/10 px-2 py-0.5 text-blue-300">
              {DIRECTION_LABEL[setup.direction]}
            </span>
          )}
          <span className="rounded-full border border-slate-700 px-2 py-0.5">every {setup.interval_minutes}m</span>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">
          Next: {setup.enabled ? fmtDateTime(setup.next_run_at) : '—'} · Last: {fmtDateTime(setup.last_run_at)}
        </p>
        {setup.last_status && <p className="mt-0.5 text-[11px] text-slate-500">{setup.last_status}</p>}
      </button>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {setup.enabled ? (
          <Button size="sm" variant="danger" onClick={() => stopMutation.mutate()} disabled={stopMutation.isPending}>
            <Square size={12} /> Stop
          </Button>
        ) : (
          <Button size="sm" onClick={() => startMutation.mutate()} disabled={startMutation.isPending}>
            <Play size={12} /> Start
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => runNowMutation.mutate()} disabled={runNowMutation.isPending}>
          <RefreshCw size={12} className={runNowMutation.isPending ? 'animate-spin' : ''} /> Run now
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
          <Pencil size={12} /> Edit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            if (window.confirm(`Delete setup "${setup.name}"? This also deletes its saved suggestions.`)) {
              deleteMutation.mutate()
            }
          }}
          disabled={deleteMutation.isPending}
        >
          <Trash2 size={12} />
        </Button>
      </div>
      {error && <p className="mt-1.5 text-[11px] text-rose-400">{error}</p>}
    </div>

    {editing && (
      <EditSetupModal
        setup={setup}
        onClose={() => setEditing(false)}
        onSaved={() => {
          setEditing(false)
          invalidate()
        }}
      />
    )}
    </>
  )
}

export default function AutoTrade() {
  const [selectedSetupId, setSelectedSetupId] = useState<number | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  const setupsQuery = useQuery({ queryKey: ['auto-trade-setups'], queryFn: fetchAutoTradeSetups, refetchInterval: 30_000 })
  const setups = setupsQuery.data?.setups ?? []

  useEffect(() => {
    if (selectedSetupId == null && setups.length) setSelectedSetupId(setups[0].id)
    if (selectedSetupId != null && setups.length && !setups.some((s) => s.id === selectedSetupId)) {
      setSelectedSetupId(setups[0]?.id ?? null)
    }
  }, [setups, selectedSetupId])

  const suggestionsQuery = useQuery({
    queryKey: ['auto-trade-suggestions', selectedSetupId],
    queryFn: () => fetchAutoTradeSuggestions({ setup_id: selectedSetupId ?? undefined }),
    enabled: selectedSetupId != null,
    refetchInterval: 60_000,
  })
  const suggestions = suggestionsQuery.data?.suggestions ?? []
  const selectedSetup = setups.find((s) => s.id === selectedSetupId)

  return (
    <div>
      <PageHeader
        title="Auto Trade"
        description="Automated, institutional-style suggestion engine — create a setup for any market + trading style combination, each on its own schedule, and get a ranked BUY/SELL/WAIT shortlist with confidence, SL/TP and a plain-English explanation for each idea."
      />

      <MethodologyPanel />

      <Card className="mb-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="inline-flex items-center gap-2 font-semibold text-white">
            <Zap size={16} className="text-amber-400" /> Your setups ({setups.length})
          </h3>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus size={14} /> New setup
          </Button>
        </div>

        {setupsQuery.isLoading ? (
          <Loading message="Loading your Auto Trade setups…" />
        ) : setups.length === 0 ? (
          <p className="text-sm text-slate-500">
            No setups yet — create one to start automated scanning for a specific market and trading style (e.g. "Crypto
            Scalping" or "India Swing").
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {setups.map((s) => (
              <SetupCard key={s.id} setup={s} active={s.id === selectedSetupId} onSelect={() => setSelectedSetupId(s.id)} />
            ))}
          </div>
        )}
      </Card>

      {showCreate && (
        <CreateSetupModal
          onClose={() => setShowCreate(false)}
          onCreated={(setup) => {
            setShowCreate(false)
            setSelectedSetupId(setup.id)
          }}
        />
      )}

      {selectedSetup && (
        <>
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
            {selectedSetup.name} — {ASSET_CLASS_LABEL[selectedSetup.asset_class]} · {STYLE_LABEL[selectedSetup.style]}
          </p>
          {suggestionsQuery.isLoading && <Loading message="Loading suggestions…" />}
          {!suggestionsQuery.isLoading && !suggestions.length && (
            <Card>
              <p className="text-sm text-slate-500">
                No suggestions yet for this setup — start it above, or click "Run now" for an immediate scan.
              </p>
            </Card>
          )}
          {suggestions.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {suggestions.map((s) => <SuggestionCard key={s.id} s={s} />)}
            </div>
          )}
        </>
      )}
    </div>
  )
}
