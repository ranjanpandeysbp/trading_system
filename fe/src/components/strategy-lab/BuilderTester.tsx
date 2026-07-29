import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Bot, Plus, Save, Sparkles, Trash2, Zap } from 'lucide-react'
import {
  aiGenerateStrategy,
  apiErrorMessage,
  createCustomStrategy,
  deleteCustomStrategy,
  fetchCustomStrategies,
  fetchStrategyLabPresets,
  runStrategyLabBacktest,
  type AIGeneratedStrategy,
  type CustomStrategy,
} from '../../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../command-center/AssetClassTickerPicker'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Badge } from '../ui/Badge'
import { FormField, Input, Select, Textarea } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'
import { DataTable, Th, Td } from '../ui/Table'

// ── Indicator library — mirrors be/app/market_pulse/indicators.py exactly:
// same types, same param names, same output-column naming convention. ──────

type IndicatorParam = { name: string; label: string; default: number; step?: number }
type IndicatorDef = {
  type: string
  label: string
  params: IndicatorParam[]
  columns: (p: Record<string, number | string>) => string[]
}

const INDICATOR_DEFS: IndicatorDef[] = [
  { type: 'ema', label: 'EMA', params: [{ name: 'period', label: 'Period', default: 20 }], columns: (p) => [`ema_${p.period}`] },
  { type: 'sma', label: 'SMA', params: [{ name: 'period', label: 'Period', default: 20 }], columns: (p) => [`sma_${p.period}`] },
  { type: 'vwap', label: 'VWAP', params: [], columns: () => ['vwap'] },
  { type: 'rsi', label: 'RSI', params: [{ name: 'period', label: 'Period', default: 14 }], columns: (p) => [`rsi_${p.period}`] },
  {
    type: 'bb', label: 'Bollinger Bands',
    params: [{ name: 'period', label: 'Period', default: 20 }, { name: 'std_dev', label: 'Std Dev', default: 2, step: 0.1 }],
    columns: (p) => [`bb_upper_${p.period}_${p.std_dev}`, `bb_middle_${p.period}_${p.std_dev}`, `bb_lower_${p.period}_${p.std_dev}`],
  },
  { type: 'atr', label: 'ATR', params: [{ name: 'period', label: 'Period', default: 14 }], columns: (p) => [`atr_${p.period}`] },
  {
    type: 'supertrend', label: 'SuperTrend',
    params: [{ name: 'period', label: 'Period', default: 10 }, { name: 'multiplier', label: 'Multiplier', default: 3, step: 0.1 }],
    columns: (p) => [`supertrend_${p.period}_${p.multiplier}`, `supertrend_dir_${p.period}_${p.multiplier}`],
  },
  {
    type: 'macd', label: 'MACD',
    params: [{ name: 'fast', label: 'Fast', default: 12 }, { name: 'slow', label: 'Slow', default: 26 }, { name: 'signal', label: 'Signal', default: 9 }],
    columns: (p) => [`macd_${p.fast}_${p.slow}`, `macd_signal_${p.fast}_${p.slow}_${p.signal}`, `macd_hist_${p.fast}_${p.slow}_${p.signal}`],
  },
  {
    type: 'stochastic', label: 'Stochastic',
    params: [{ name: 'k_period', label: '%K Period', default: 14 }, { name: 'd_period', label: '%D Period', default: 3 }],
    columns: (p) => [`stoch_k_${p.k_period}`, `stoch_d_${p.k_period}_${p.d_period}`],
  },
  { type: 'adx', label: 'ADX', params: [{ name: 'period', label: 'Period', default: 14 }], columns: (p) => [`adx_${p.period}`, `plus_di_${p.period}`, `minus_di_${p.period}`] },
  { type: 'obv', label: 'OBV', params: [], columns: () => ['obv'] },
  { type: 'vol_sma', label: 'Volume SMA', params: [{ name: 'period', label: 'Period', default: 20 }], columns: (p) => [`vol_sma_${p.period}`, `vol_ratio_${p.period}`] },
  { type: 'pivots', label: 'Pivot Points', params: [], columns: () => ['pivot', 'pivot_r1', 'pivot_s1', 'pivot_r2', 'pivot_s2'] },
  {
    type: 'fibonacci', label: 'Fibonacci Levels',
    params: [{ name: 'lookback', label: 'Lookback', default: 50 }],
    columns: (p) => [`fib_high_${p.lookback}`, `fib_low_${p.lookback}`, `fib_0.236_${p.lookback}`, `fib_0.382_${p.lookback}`, `fib_0.5_${p.lookback}`, `fib_0.618_${p.lookback}`, `fib_0.786_${p.lookback}`],
  },
  { type: 'cci', label: 'CCI', params: [{ name: 'period', label: 'Period', default: 20 }], columns: (p) => [`cci_${p.period}`] },
  { type: 'roc', label: 'Rate of Change', params: [{ name: 'period', label: 'Period', default: 9 }], columns: (p) => [`roc_${p.period}`] },
  { type: 'williams_r', label: 'Williams %R', params: [{ name: 'period', label: 'Period', default: 14 }], columns: (p) => [`williams_r_${p.period}`] },
  { type: 'mfi', label: 'Money Flow Index', params: [{ name: 'period', label: 'Period', default: 14 }], columns: (p) => [`mfi_${p.period}`] },
  {
    type: 'donchian', label: 'Donchian Channels',
    params: [{ name: 'period', label: 'Period', default: 20 }],
    columns: (p) => [`donchian_upper_${p.period}`, `donchian_lower_${p.period}`, `donchian_middle_${p.period}`],
  },
]

const OPERATORS = ['>', '<', '>=', '<=', '==', 'crosses above', 'crosses below']
const BASE_COLUMNS = ['open', 'high', 'low', 'close', 'volume']
const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk']

type IndicatorConfig = { type: string; [param: string]: string | number }
type RuleConfig = { left: string; op: string; right_type: 'value' | 'indicator'; right_val: string }

function indicatorLabel(cfg: IndicatorConfig): string {
  const def = INDICATOR_DEFS.find((d) => d.type === cfg.type)
  if (!def) return cfg.type
  const params = def.params.map((p) => `${p.name}=${cfg[p.name]}`).join(', ')
  return params ? `${def.label} (${params})` : def.label
}

function availableColumns(indicators: IndicatorConfig[]): string[] {
  const cols = new Set<string>(BASE_COLUMNS)
  for (const cfg of indicators) {
    const def = INDICATOR_DEFS.find((d) => d.type === cfg.type)
    if (def) def.columns(cfg).forEach((c) => cols.add(c))
  }
  return Array.from(cols)
}

function defaultParams(def: IndicatorDef): Record<string, number> {
  const out: Record<string, number> = {}
  for (const p of def.params) out[p.name] = p.default
  return out
}

// ── Builder state ────────────────────────────────────────────────────────

type Direction = 'long_only' | 'short_only' | 'long_short'
type Sizing = 'pct_of_capital' | 'risk_pct'

interface BuilderState {
  name: string
  timeframe: string
  indicators: IndicatorConfig[]
  entryRules: RuleConfig[]
  exitRules: RuleConfig[]
  entryMode: 'AND' | 'OR'
  exitMode: 'AND' | 'OR'
  direction: Direction
  sizing: Sizing
  capitalAllocationPct: number
  riskPct: number
  slPct: number
  tpPct: number
  capital: number
  commission: number
  slippage: number
}

const DEFAULT_STATE: BuilderState = {
  name: '',
  timeframe: '1d',
  indicators: [{ type: 'rsi', period: 14 }],
  entryRules: [{ left: 'rsi_14', op: '<', right_type: 'value', right_val: '35' }],
  exitRules: [{ left: 'rsi_14', op: '>', right_type: 'value', right_val: '65' }],
  entryMode: 'AND',
  exitMode: 'AND',
  direction: 'long_only',
  sizing: 'pct_of_capital',
  capitalAllocationPct: 95,
  riskPct: 1,
  slPct: 0,
  tpPct: 0,
  capital: 100_000,
  commission: 0.1,
  slippage: 0.05,
}

const HOW_IT_WORKS = `1. Build indicators — pick technical indicators (RSI, EMA, MACD, Bollinger Bands, …) and their parameters. Each one adds columns you can reference in your rules.
2. Build entry/exit rules — compare an indicator (or price) against a fixed value or another indicator, using >, <, ==, or a crossover. Combine multiple rules with AND (all must be true) or OR (any one).
3. Configure — pick a ticker, timeframe, starting capital, costs, stop-loss/take-profit, direction (long/short/both), and position sizing.
4. Backtest — runs your exact rules bar-by-bar over history and reports the full professional metric set (CAGR, Sharpe, Sortino, max drawdown, profit factor, expectancy, long vs short win rate, …), an equity curve, and every trade taken.
5. Save or ask AI — save a working strategy to reuse from Quick Start next time, or describe a strategy in plain English (or paste a video transcript) and let AI turn it into indicators + rules you can review and run.`

export function BuilderTester({ assetClass }: { assetClass: AssetClass }) {
  const qc = useQueryClient()
  const [state, setState] = useState<BuilderState>(DEFAULT_STATE)
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [quickStart, setQuickStart] = useState('')
  const [aiText, setAiText] = useState('')
  const [aiName, setAiName] = useState('')
  const [aiPreview, setAiPreview] = useState<AIGeneratedStrategy | null>(null)
  const [aiError, setAiError] = useState('')
  const [runError, setRunError] = useState('')
  const [saveMsg, setSaveMsg] = useState('')

  const ticker = picker.tickers[0] ?? ''
  const cols = useMemo(() => availableColumns(state.indicators), [state.indicators])

  const presetsQ = useQuery({
    queryKey: ['sl-presets-builder', assetClass],
    queryFn: () => fetchStrategyLabPresets(undefined, assetClass),
  })
  const customQ = useQuery({
    queryKey: ['custom-strategies', assetClass],
    queryFn: () => fetchCustomStrategies(),
  })

  const presets = (presetsQ.data?.presets ?? {}) as Record<string, { description?: string; recommended_timeframe?: string; recommended_sl?: number; recommended_tp?: number }>
  const customStrategies = customQ.data?.strategies ?? []

  const backtestMut = useMutation({
    mutationFn: () =>
      runStrategyLabBacktest({
        ticker,
        timeframe: state.timeframe,
        asset_class: assetClass,
        indicators: state.indicators,
        entry_rules: state.entryRules,
        exit_rules: state.exitRules,
        entry_mode: state.entryMode,
        exit_mode: state.exitMode,
        direction_mode: state.direction,
        position_sizing: state.sizing,
        capital_allocation_pct: state.capitalAllocationPct,
        risk_pct: state.riskPct,
        capital: state.capital,
        commission: state.commission / 100,
        slippage: state.slippage / 100,
        sl_pct: state.slPct,
        tp_pct: state.tpPct,
      }),
    onSuccess: () => setRunError(''),
    onError: (e) => setRunError(apiErrorMessage(e)),
  })

  const aiMut = useMutation({
    mutationFn: () => aiGenerateStrategy({ text: aiText, market: presetsQ.data?.market ?? 'india', asset_class: assetClass, strategy_name: aiName || undefined }),
    onSuccess: (data) => { setAiPreview(data); setAiError('') },
    onError: (e) => setAiError(apiErrorMessage(e)),
  })

  const saveMut = useMutation({
    mutationFn: () =>
      createCustomStrategy({
        name: state.name.trim() || `${ticker} · ${state.timeframe} custom strategy`,
        market: presetsQ.data?.market ?? 'india',
        asset_class: assetClass,
        timeframe: state.timeframe,
        indicators: state.indicators,
        entry_rules: state.entryRules,
        exit_rules: state.exitRules,
        entry_mode: state.entryMode,
        exit_mode: state.exitMode,
        direction_mode: state.direction,
        position_sizing: state.sizing,
        capital_allocation_pct: state.capitalAllocationPct,
        risk_pct: state.riskPct,
        sl_pct: state.slPct,
        tp_pct: state.tpPct,
      }),
    onSuccess: (row) => {
      qc.invalidateQueries({ queryKey: ['custom-strategies', assetClass] })
      setSaveMsg(`Saved "${row.name}" — it now appears in Quick Start.`)
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteCustomStrategy(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['custom-strategies', assetClass] }),
  })

  const addIndicator = (type: string) => {
    const def = INDICATOR_DEFS.find((d) => d.type === type)
    if (!def) return
    setState((s) => ({ ...s, indicators: [...s.indicators, { type, ...defaultParams(def) }] }))
  }
  const removeIndicator = (idx: number) => setState((s) => ({ ...s, indicators: s.indicators.filter((_, i) => i !== idx) }))
  const updateIndicatorParam = (idx: number, param: string, value: number) =>
    setState((s) => ({ ...s, indicators: s.indicators.map((c, i) => (i === idx ? { ...c, [param]: value } : c)) }))

  const addRule = (kind: 'entryRules' | 'exitRules') =>
    setState((s) => ({ ...s, [kind]: [...s[kind], { left: cols[0] ?? 'close', op: '>', right_type: 'value', right_val: '0' }] }))
  const removeRule = (kind: 'entryRules' | 'exitRules', idx: number) =>
    setState((s) => ({ ...s, [kind]: s[kind].filter((_, i) => i !== idx) }))
  const updateRule = (kind: 'entryRules' | 'exitRules', idx: number, patch: Partial<RuleConfig>) =>
    setState((s) => ({ ...s, [kind]: s[kind].map((r, i) => (i === idx ? { ...r, ...patch } : r)) }))

  const loadPreset = (name: string) => {
    const p = presets[name]
    if (!p) return
    // Preset backtests go through preset_name server-side, but for the
    // builder we just seed sensible defaults — SL/TP/timeframe.
    setState((s) => ({
      ...s,
      name,
      timeframe: p.recommended_timeframe || s.timeframe,
      slPct: p.recommended_sl ?? s.slPct,
      tpPct: p.recommended_tp ?? s.tpPct,
    }))
  }

  const loadCustom = (cs: CustomStrategy) => {
    setState({
      name: cs.name,
      timeframe: cs.timeframe,
      indicators: cs.indicators as IndicatorConfig[],
      entryRules: cs.entry_rules as RuleConfig[],
      exitRules: cs.exit_rules as RuleConfig[],
      entryMode: cs.entry_mode,
      exitMode: cs.exit_mode,
      direction: cs.direction_mode,
      sizing: cs.position_sizing,
      capitalAllocationPct: cs.capital_allocation_pct,
      riskPct: cs.risk_pct,
      slPct: cs.sl_pct,
      tpPct: cs.tp_pct,
      capital: DEFAULT_STATE.capital,
      commission: DEFAULT_STATE.commission,
      slippage: DEFAULT_STATE.slippage,
    })
  }

  const loadAiPreview = () => {
    if (!aiPreview) return
    setState((s) => ({
      ...s,
      name: aiPreview.name,
      timeframe: aiPreview.recommended_timeframe || s.timeframe,
      indicators: aiPreview.indicators as IndicatorConfig[],
      entryRules: aiPreview.entry_rules as RuleConfig[],
      exitRules: aiPreview.exit_rules as RuleConfig[],
      entryMode: aiPreview.entry_mode,
      exitMode: aiPreview.exit_mode,
      direction: aiPreview.direction_mode,
      slPct: aiPreview.recommended_sl ?? s.slPct,
      tpPct: aiPreview.recommended_tp ?? s.tpPct,
    }))
  }

  useEffect(() => { setSaveMsg('') }, [state])

  const result = backtestMut.data as {
    metrics?: Record<string, number | null>
    trades?: Array<Record<string, unknown>>
    trade_count?: number
    equity_curve?: Array<{ date: string; equity: number }>
  } | undefined
  const metrics = result?.metrics ?? {}

  return (
    <div className="space-y-4">
      <Card>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-slate-200">How this works</summary>
          <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{HOW_IT_WORKS}</pre>
        </details>
      </Card>

      <Card>
        <h3 className="mb-3 font-medium text-white">Quick Start</h3>
        <div className="flex flex-wrap items-end gap-3">
          <FormField label="Load a built-in preset or your saved strategy">
            <Select
              value={quickStart}
              onChange={(e) => {
                const v = e.target.value
                setQuickStart(v)
                if (!v) return
                if (v.startsWith('custom:')) {
                  const cs = customStrategies.find((c) => String(c.id) === v.slice(7))
                  if (cs) loadCustom(cs)
                } else if (v.startsWith('preset:')) {
                  loadPreset(v.slice(7))
                }
              }}
            >
              <option value="">— select —</option>
              {Object.keys(presets).length > 0 && (
                <optgroup label="Built-in presets">
                  {Object.keys(presets).map((name) => (
                    <option key={name} value={`preset:${name}`}>{name}</option>
                  ))}
                </optgroup>
              )}
              {customStrategies.length > 0 && (
                <optgroup label="Your saved strategies">
                  {customStrategies.map((cs) => (
                    <option key={cs.id} value={`custom:${cs.id}`}>
                      {cs.name}{cs.source === 'ai' ? ' (AI)' : ''}
                    </option>
                  ))}
                </optgroup>
              )}
            </Select>
          </FormField>
          {quickStart.startsWith('custom:') && (
            <Button
              variant="danger" size="sm"
              onClick={() => {
                const id = Number(quickStart.slice(7))
                deleteMut.mutate(id)
                setQuickStart('')
              }}
            >
              <Trash2 size={14} /> Delete saved
            </Button>
          )}
        </div>
      </Card>

      <Card>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-slate-200 inline-flex items-center gap-1.5">
            <Bot size={15} /> AI Strategy Creator — describe it, let AI build the rules
          </summary>
          <div className="mt-3 space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField label="Strategy name (optional)">
                <Input value={aiName} onChange={(e) => setAiName(e.target.value)} placeholder="e.g. RSI Pullback Swing" />
              </FormField>
            </div>
            <FormField label="Describe the strategy in plain English, or paste a video transcript">
              <Textarea
                rows={5}
                value={aiText}
                onChange={(e) => setAiText(e.target.value)}
                placeholder="e.g. Buy when RSI(14) drops below 30 and price is above the 50 EMA. Sell when RSI crosses back above 60. Use a 2% stop loss and 4% target on the daily timeframe."
              />
            </FormField>
            <Button onClick={() => aiMut.mutate()} disabled={aiMut.isPending || aiText.trim().length < 10}>
              <Sparkles size={16} /> {aiMut.isPending ? 'Generating…' : 'Generate AI Strategy Preview'}
            </Button>
            {aiError && <Alert type="error">{aiError}</Alert>}
            {aiPreview && (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3 text-sm">
                <p className="font-medium text-slate-200">{aiPreview.name}</p>
                <p className="mt-1 text-xs text-slate-400">{aiPreview.description}</p>
                <p className="mt-1 text-xs text-slate-500">
                  TF {aiPreview.recommended_timeframe} · SL {aiPreview.recommended_sl ?? '—'}% · TP {aiPreview.recommended_tp ?? '—'}% · {aiPreview.direction_mode}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {aiPreview.indicators.length} indicators · {aiPreview.entry_rules.length} entry rules · {aiPreview.exit_rules.length} exit rules
                </p>
                <Button size="sm" variant="secondary" className="mt-2" onClick={loadAiPreview}>
                  Load into builder
                </Button>
              </div>
            )}
          </div>
        </details>
      </Card>

      <Card>
        <h3 className="mb-3 font-medium text-white">1 &amp; 2 — Indicators and Rules</h3>

        <FormField label={`Indicators (${state.indicators.length} configured)`}>
          <div className="flex flex-wrap gap-2">
            {INDICATOR_DEFS.map((def) => (
              <Chip key={def.type} selected={false} onClick={() => addIndicator(def.type)}>
                <Plus size={12} className="mr-1 inline" />{def.label}
              </Chip>
            ))}
          </div>
        </FormField>

        {state.indicators.length > 0 && (
          <div className="mb-4 space-y-2">
            {state.indicators.map((cfg, idx) => {
              const def = INDICATOR_DEFS.find((d) => d.type === cfg.type)
              return (
                <div key={idx} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-800/60 bg-slate-900/40 p-2">
                  <span className="text-sm text-slate-200">{indicatorLabel(cfg)}</span>
                  {def?.params.map((p) => (
                    <label key={p.name} className="flex items-center gap-1 text-xs text-slate-500">
                      {p.label}
                      <input
                        type="number"
                        step={p.step ?? 1}
                        value={cfg[p.name]}
                        onChange={(e) => updateIndicatorParam(idx, p.name, Number(e.target.value))}
                        className="w-16 rounded border border-slate-700/80 bg-slate-800/60 px-1.5 py-0.5 text-slate-200"
                      />
                    </label>
                  ))}
                  <button type="button" onClick={() => removeIndicator(idx)} className="ml-auto text-slate-500 hover:text-rose-400">
                    <Trash2 size={14} />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        <RuleList
          label="Entry rules"
          rules={state.entryRules}
          mode={state.entryMode}
          onModeChange={(m) => setState((s) => ({ ...s, entryMode: m }))}
          cols={cols}
          onAdd={() => addRule('entryRules')}
          onRemove={(i) => removeRule('entryRules', i)}
          onUpdate={(i, patch) => updateRule('entryRules', i, patch)}
        />
        <div className="mt-4">
          <RuleList
            label="Exit rules"
            rules={state.exitRules}
            mode={state.exitMode}
            onModeChange={(m) => setState((s) => ({ ...s, exitMode: m }))}
            cols={cols}
            onAdd={() => addRule('exitRules')}
            onRemove={(i) => removeRule('exitRules', i)}
            onUpdate={(i, patch) => updateRule('exitRules', i, patch)}
          />
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 font-medium text-white">3 — Configure</h3>
        <AssetClassTickerPicker key={assetClass} assetClass={assetClass} single showDurations={false} onChange={setPicker} />
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Timeframe">
            <Select value={state.timeframe} onChange={(e) => setState((s) => ({ ...s, timeframe: e.target.value }))}>
              {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
            </Select>
          </FormField>
          <FormField label="Direction">
            <Select value={state.direction} onChange={(e) => setState((s) => ({ ...s, direction: e.target.value as Direction }))}>
              <option value="long_only">Long only</option>
              <option value="short_only">Short only</option>
              <option value="long_short">Long &amp; short</option>
            </Select>
          </FormField>
          <FormField label="Position sizing">
            <Select value={state.sizing} onChange={(e) => setState((s) => ({ ...s, sizing: e.target.value as Sizing }))}>
              <option value="pct_of_capital">% of capital</option>
              <option value="risk_pct">Risk % (needs SL)</option>
            </Select>
          </FormField>
          {state.sizing === 'pct_of_capital' ? (
            <FormField label="Capital allocation %">
              <Input type="number" value={state.capitalAllocationPct} onChange={(e) => setState((s) => ({ ...s, capitalAllocationPct: Number(e.target.value) }))} />
            </FormField>
          ) : (
            <FormField label="Risk % per trade">
              <Input type="number" step={0.1} value={state.riskPct} onChange={(e) => setState((s) => ({ ...s, riskPct: Number(e.target.value) }))} />
            </FormField>
          )}
          <FormField label="Starting capital">
            <Input type="number" value={state.capital} onChange={(e) => setState((s) => ({ ...s, capital: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Commission %">
            <Input type="number" step={0.01} value={state.commission} onChange={(e) => setState((s) => ({ ...s, commission: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Slippage %">
            <Input type="number" step={0.01} value={state.slippage} onChange={(e) => setState((s) => ({ ...s, slippage: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Stop-loss %">
            <Input type="number" step={0.1} value={state.slPct} onChange={(e) => setState((s) => ({ ...s, slPct: Number(e.target.value) }))} />
          </FormField>
          <FormField label="Take-profit %">
            <Input type="number" step={0.1} value={state.tpPct} onChange={(e) => setState((s) => ({ ...s, tpPct: Number(e.target.value) }))} />
          </FormField>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={() => backtestMut.mutate()} disabled={backtestMut.isPending || !ticker}>
            <Zap size={16} /> {backtestMut.isPending ? 'Running backtest…' : '4 — Run Backtest'}
          </Button>
          <FormField label="Strategy name (for saving)">
            <Input value={state.name} onChange={(e) => setState((s) => ({ ...s, name: e.target.value }))} placeholder="Name this strategy…" className="w-56" />
          </FormField>
          <Button variant="secondary" onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !state.indicators.length}>
            <Save size={16} /> Save strategy
          </Button>
        </div>
        {!ticker && <p className="mt-2 text-xs text-amber-400">Select a ticker above to run a backtest.</p>}
        {runError && <div className="mt-3"><Alert type="error">{runError}</Alert></div>}
        {saveMsg && <div className="mt-3"><Alert type="success">{saveMsg}</Alert></div>}
      </Card>

      {backtestMut.isPending && <Loading message="Running backtest…" />}

      {result && (
        <ResultsPanel metrics={metrics} trades={result.trades ?? []} tradeCount={result.trade_count ?? 0} equityCurve={result.equity_curve ?? []} />
      )}
    </div>
  )
}

function RuleList({
  label, rules, mode, onModeChange, cols, onAdd, onRemove, onUpdate,
}: {
  label: string
  rules: RuleConfig[]
  mode: 'AND' | 'OR'
  onModeChange: (m: 'AND' | 'OR') => void
  cols: string[]
  onAdd: () => void
  onRemove: (i: number) => void
  onUpdate: (i: number, patch: Partial<RuleConfig>) => void
}) {
  return (
    <FormField label={`${label} (${rules.length})`}>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs text-slate-500">Match</span>
        <Chip selected={mode === 'AND'} onClick={() => onModeChange('AND')}>AND (all)</Chip>
        <Chip selected={mode === 'OR'} onClick={() => onModeChange('OR')}>OR (any)</Chip>
      </div>
      <div className="space-y-2">
        {rules.map((r, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-800/60 bg-slate-900/40 p-2 text-sm">
            <Select value={r.left} onChange={(e) => onUpdate(i, { left: e.target.value })} className="!w-auto">
              {cols.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
            <Select value={r.op} onChange={(e) => onUpdate(i, { op: e.target.value })} className="!w-auto">
              {OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
            </Select>
            <Select value={r.right_type} onChange={(e) => onUpdate(i, { right_type: e.target.value as 'value' | 'indicator' })} className="!w-auto">
              <option value="value">value</option>
              <option value="indicator">indicator</option>
            </Select>
            {r.right_type === 'indicator' ? (
              <Select value={r.right_val} onChange={(e) => onUpdate(i, { right_val: e.target.value })} className="!w-auto">
                {cols.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            ) : (
              <input
                type="text"
                value={r.right_val}
                onChange={(e) => onUpdate(i, { right_val: e.target.value })}
                className="w-24 rounded border border-slate-700/80 bg-slate-800/60 px-2 py-1 text-slate-200"
              />
            )}
            <button type="button" onClick={() => onRemove(i)} className="ml-auto text-slate-500 hover:text-rose-400">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
      <Button variant="ghost" size="sm" className="mt-2" onClick={onAdd}>
        <Plus size={14} /> Add rule
      </Button>
    </FormField>
  )
}

type MetricDef = { key: string; label: string; pct?: boolean }

const METRIC_CARDS: MetricDef[] = [
  { key: 'total_return_pct', label: 'Total Return', pct: true },
  { key: 'cagr_pct', label: 'CAGR', pct: true },
  { key: 'sharpe_ratio', label: 'Sharpe' },
  { key: 'max_drawdown_pct', label: 'Max Drawdown', pct: true },
  { key: 'profit_factor', label: 'Profit Factor' },
  { key: 'win_rate_pct', label: 'Win Rate', pct: true },
  { key: 'n_trades', label: 'Trades' },
  { key: 'final_capital', label: 'Final Capital' },
]

const PRO_METRICS: MetricDef[] = [
  { key: 'sortino_ratio', label: 'Sortino Ratio' },
  { key: 'annual_volatility_pct', label: 'Annual Volatility', pct: true },
  { key: 'max_drawdown_duration_days', label: 'Max DD Duration (days)' },
  { key: 'exposure_pct', label: 'Exposure', pct: true },
  { key: 'expectancy_pct', label: 'Expectancy', pct: true },
  { key: 'max_consecutive_wins', label: 'Max Consecutive Wins' },
  { key: 'max_consecutive_losses', label: 'Max Consecutive Losses' },
  { key: 'buy_hold_return_pct', label: 'Buy & Hold Return', pct: true },
  { key: 'alpha_pct', label: 'Alpha vs Buy & Hold', pct: true },
  { key: 'long_win_rate_pct', label: 'Long Win Rate', pct: true },
  { key: 'short_win_rate_pct', label: 'Short Win Rate', pct: true },
]

// Meaning + how to read it toward a take/skip decision — shown as hover
// tooltips on each card and expanded in the "What these numbers mean" panel.
const METRIC_GUIDE: Record<string, { meaning: string; good: string; watch: string }> = {
  total_return_pct: {
    meaning: 'Overall % gain or loss on your starting capital across the whole backtest period.',
    good: 'Comfortably positive, and ahead of Buy & Hold (see Alpha below).',
    watch: 'Negative, or barely positive once you account for costs — the strategy isn\'t adding value.',
  },
  cagr_pct: {
    meaning: 'Annualized compounding growth rate — lets you compare strategies or tickers fairly regardless of how long each backtest period is.',
    good: 'Double digits, clearly ahead of a savings/index benchmark.',
    watch: 'Near zero or negative once annualized.',
  },
  sharpe_ratio: {
    meaning: 'Return earned per unit of volatility (risk-adjusted return) — the single most-used "is this worth the ride" number.',
    good: 'Above 1 is respectable, above 2 is strong.',
    watch: 'Below 0.5 — the return doesn\'t justify the bumpiness.',
  },
  max_drawdown_pct: {
    meaning: 'The worst peak-to-trough decline in equity during the test — the deepest hole you\'d have had to sit through.',
    good: 'Shallow relative to the total return, and small enough you could hold through it without panic-closing.',
    watch: 'Deep enough that you honestly wouldn\'t stay in the trade if it happened live.',
  },
  profit_factor: {
    meaning: 'Gross profit ÷ gross loss. Tells you whether winners actually outweigh losers in dollar terms.',
    good: 'Above 1.5 — a real edge.',
    watch: 'Below 1.2 (thin edge) or below 1 (the strategy loses money even if the win rate looks fine).',
  },
  win_rate_pct: {
    meaning: '% of trades that were profitable. Misleading on its own — a low win rate can still be very profitable if winners are much bigger than losers, and vice versa.',
    good: 'High win rate WITH a healthy Profit Factor — consistent, easy to trust.',
    watch: 'High win rate but low/negative Profit Factor — many small wins, a few large losses wipe them out.',
  },
  n_trades: {
    meaning: 'Sample size — how many completed trades these stats are based on.',
    good: '30+ trades — enough to trust the other numbers aren\'t just luck.',
    watch: 'Under ~15-20 trades — treat every other metric here as a rough guess, not a verdict.',
  },
  final_capital: {
    meaning: 'Ending account value, starting from your configured Starting Capital, trading only this one strategy.',
    good: '—',
    watch: '—',
  },
  sortino_ratio: {
    meaning: 'Like Sharpe, but only penalizes downside volatility — upside swings don\'t count against it. Often fairer for strategies with big winning runs.',
    good: 'Above 1.5-2, and noticeably higher than the Sharpe ratio (means most of the volatility is upside).',
    watch: 'Close to or below the Sharpe ratio — the volatility is mostly to the downside.',
  },
  annual_volatility_pct: {
    meaning: 'How much the equity curve swings on an annualized basis — a bumpier ride even if the end result is good.',
    good: 'Low relative to CAGR (good return per unit of bumpiness).',
    watch: 'Very high — expect a stressful equity curve even if the average outcome is fine.',
  },
  max_drawdown_duration_days: {
    meaning: 'How long it took to recover back to the prior equity peak after the worst drawdown — how long you\'d be "underwater", not just how deep.',
    good: 'Short relative to your holding-period patience.',
    watch: 'Long stretches underwater — can you actually wait that out without giving up?',
  },
  exposure_pct: {
    meaning: '% of the backtest period you were actually holding a position.',
    good: 'Low exposure with good returns = capital-efficient — your money is free the rest of the time.',
    watch: 'Very high exposure — you\'re "always in", so any market-wide shock hits you fully.',
  },
  expectancy_pct: {
    meaning: 'Average expected % return per trade, blending win rate and win/loss size — the single number closest to "what do I expect to make per trade, on average".',
    good: 'Clearly positive.',
    watch: 'Zero or negative — even with a decent win rate, the average trade loses money.',
  },
  max_consecutive_wins: {
    meaning: 'Longest winning streak in the backtest.',
    good: '—',
    watch: '—',
  },
  max_consecutive_losses: {
    meaning: 'Longest losing streak — tells you how much drawdown and psychological pain to expect in the worst stretch.',
    good: 'Short streak relative to your position size — you can survive it and keep trading the plan.',
    watch: 'A long streak — make sure your position size lets you survive this many losses IN A ROW without blowing up the account or panicking.',
  },
  buy_hold_return_pct: {
    meaning: 'What you\'d have made just buying and holding the ticker for the same period, doing nothing.',
    good: '—',
    watch: '—',
  },
  alpha_pct: {
    meaning: 'Strategy return minus Buy & Hold return — the actual value added by all this rule-building versus doing nothing.',
    good: 'Clearly positive — the strategy earns its complexity and costs.',
    watch: 'Negative — you\'d have done better just holding the ticker; the strategy isn\'t worth the extra risk/effort.',
  },
  long_win_rate_pct: {
    meaning: 'Win rate on long trades only — useful with Long & Short mode to see if the edge holds on the buy side.',
    good: '—',
    watch: 'Much weaker than the short win rate — the edge may really only exist on one side.',
  },
  short_win_rate_pct: {
    meaning: 'Win rate on short trades only.',
    good: '—',
    watch: 'Much weaker than the long win rate — the edge may really only exist on one side.',
  },
}

function fmt(v: number | null | undefined, pct?: boolean): string {
  if (v === null || v === undefined) return '—'
  return pct ? `${v}%` : String(v)
}

function ResultsPanel({
  metrics, trades, tradeCount, equityCurve,
}: {
  metrics: Record<string, number | null>
  trades: Array<Record<string, unknown>>
  tradeCount: number
  equityCurve: Array<{ date: string; equity: number }>
}) {
  const askContext = buildAskContext('Strategy Lab backtest result', { metrics, trade_count: tradeCount, recent_trades: trades.slice(-10) })

  return (
    <Card>
      <h3 className="mb-4 font-medium text-white">Results</h3>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {METRIC_CARDS.map((m) => (
          <div
            key={m.key}
            className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3"
            title={METRIC_GUIDE[m.key]?.meaning}
          >
            <p className="text-[11px] uppercase tracking-wide text-slate-500">{m.label}</p>
            <p className="mt-1 text-lg font-semibold text-slate-100">{fmt(metrics[m.key], m.pct)}</p>
          </div>
        ))}
      </div>

      <details className="mt-4 rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium text-slate-200">What these numbers mean, and how to read them</summary>
        <div className="mt-3 space-y-4">
          <p className="text-xs leading-relaxed text-slate-400">
            No single number tells you whether to take this trade — read them together. A high win rate with a bad
            Profit Factor means small wins and a few big losses. A great Sharpe with only 8 trades could just be luck.
            The checklist below is the order that matters most.
          </p>

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Before you take this trade</p>
            <ol className="list-decimal space-y-1.5 pl-5 text-xs leading-relaxed text-slate-300">
              <li><strong className="text-slate-200">Sample size first</strong> — with fewer than ~20-30 trades, don't trust any of the numbers below yet; run a longer period.</li>
              <li><strong className="text-slate-200">Is there an edge?</strong> — Profit Factor above 1.3-1.5 and positive Expectancy. If either is weak, the win rate doesn't matter.</li>
              <li><strong className="text-slate-200">Is the ride worth it?</strong> — Sharpe above 1, Sortino not far below it. Low Sharpe means big returns came with even bigger swings.</li>
              <li><strong className="text-slate-200">Can you survive the worst stretch?</strong> — check Max Drawdown, its Duration, and Max Consecutive Losses. Size your position so that worst case doesn't wipe you out or force you to quit.</li>
              <li><strong className="text-slate-200">Does it actually beat doing nothing?</strong> — Alpha vs Buy & Hold should be clearly positive, or the strategy's complexity and costs aren't earning their keep.</li>
              <li><strong className="text-slate-200">Treat it as a hypothesis</strong> — a good backtest is a reason to test further, not a green light to risk real capital. Paper-trade it first (Paper Trading / Trade Candidate) before going live.</li>
            </ol>
          </div>

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Every metric, in plain terms</p>
            <div className="space-y-2">
              {[...METRIC_CARDS, ...PRO_METRICS].map((m) => {
                const g = METRIC_GUIDE[m.key]
                if (!g) return null
                return (
                  <div key={m.key} className="rounded-md border border-slate-800/60 bg-slate-950/40 p-2.5">
                    <p className="text-xs font-semibold text-slate-200">{m.label}</p>
                    <p className="mt-0.5 text-xs text-slate-400">{g.meaning}</p>
                    {(g.good !== '—' || g.watch !== '—') && (
                      <div className="mt-1.5 grid gap-1 sm:grid-cols-2">
                        {g.good !== '—' && (
                          <p className="text-[11px] text-emerald-400"><span className="font-medium">Good sign:</span> {g.good}</p>
                        )}
                        {g.watch !== '—' && (
                          <p className="text-[11px] text-amber-400"><span className="font-medium">Watch out:</span> {g.watch}</p>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </details>

      {equityCurve.length > 1 && (
        <div className="mt-6 h-64">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Equity curve</p>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={equityCurve} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
              <defs>
                <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={40} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} width={56} domain={['auto', 'auto']} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#e2e8f0' }}
              />
              <Area type="monotone" dataKey="equity" stroke="#3b82f6" strokeWidth={2} fill="url(#equityFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <details className="mt-6 rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium text-slate-200">Professional metrics</summary>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {PRO_METRICS.map((m) => (
            <div key={m.key} title={METRIC_GUIDE[m.key]?.meaning}>
              <p className="text-[11px] uppercase tracking-wide text-slate-500">{m.label}</p>
              <p className="text-sm text-slate-200">{fmt(metrics[m.key], m.pct)}</p>
            </div>
          ))}
        </div>
      </details>

      {trades.length > 0 && (
        <details className="mt-4 rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2" open>
          <summary className="cursor-pointer text-sm font-medium text-slate-200">Trade log (last {trades.length})</summary>
          <div className="mt-3">
            <DataTable minWidth={700}>
              <thead>
                <tr>
                  <Th>Entry</Th>
                  <Th>Exit</Th>
                  <Th>Direction</Th>
                  <Th>Entry Price</Th>
                  <Th>Exit Price</Th>
                  <Th>P&amp;L %</Th>
                  <Th>Exit Reason</Th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => {
                  const pnl = Number(t.pnl_pct ?? 0)
                  return (
                    <tr key={i}>
                      <Td className="text-xs">{String(t.entry_date ?? '').slice(0, 19)}</Td>
                      <Td className="text-xs">{String(t.exit_date ?? '').slice(0, 19)}</Td>
                      <Td><Badge action={String(t.direction ?? '')} /></Td>
                      <Td>{Number(t.entry_price ?? 0).toFixed(2)}</Td>
                      <Td>{Number(t.exit_price ?? 0).toFixed(2)}</Td>
                      <Td className={pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{pnl.toFixed(2)}%</Td>
                      <Td className="text-xs text-slate-400">{String(t.exit_reason ?? '')}</Td>
                    </tr>
                  )
                })}
              </tbody>
            </DataTable>
          </div>
        </details>
      )}

      <div className="mt-4">
        <AskAIPanel context={askContext} section="strategy_lab_builder" />
      </div>
    </Card>
  )
}
