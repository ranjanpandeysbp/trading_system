import { useMemo, useState } from 'react'
import { Badge } from '../ui/Badge'
import { DataTable, useSort } from '../ui/Table'
import { AskAIPanel } from '../ai/AskAIPanel'
import { TradeSignalBlock, resolveTradeSuggestion } from '../trading/TradeSignalBlock'
import { PatternCandleChart, PatternShapeOverlay } from './PatternAnalogueCharts'

type Row = Record<string, unknown>
type Candle = {
  time?: string
  open?: number
  high?: number
  low?: number
  close?: number
  i?: number
  zone?: string
}

function pct(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

function biasTone(bias: string): 'BUY' | 'SELL' | 'HOLD' {
  const b = bias.toUpperCase()
  if (b === 'BUY' || b === 'LONG') return 'BUY'
  if (b === 'SELL' || b === 'SHORT') return 'SELL'
  return 'HOLD'
}

function asCandles(v: unknown): Candle[] {
  return Array.isArray(v) ? (v as Candle[]) : []
}

function MatchTable({ matches }: { matches: Row[] }) {
  const { sorted, sortKey, sortDir, handleSort } = useSort(
    matches,
    {
      rank: (r) => Number(r.rank ?? 0),
      similarity: (r) => Number(r.similarity ?? 0),
      before: (r) => Number(r.before_return_pct ?? 0),
      next: (r) => Number(r.next_bar_return_pct ?? 0),
      forward: (r) => Number(r.forward_return_pct ?? 0),
      match_end: (r) => String(r.match_end ?? ''),
    },
    'rank',
    'asc',
  )

  if (!matches.length) {
    return <p className="text-sm text-slate-500">No similar historical windows above the similarity threshold.</p>
  }

  return (
    <DataTable title="Historical analogues — before & after">
      <thead>
        <tr>
          <th className="cursor-pointer" onClick={() => handleSort('rank')}>
            #{sortKey === 'rank' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </th>
          <th className="cursor-pointer" onClick={() => handleSort('similarity')}>
            Sim%{sortKey === 'similarity' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </th>
          <th className="cursor-pointer" onClick={() => handleSort('match_end')}>
            Match end{sortKey === 'match_end' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </th>
          <th>Shape</th>
          <th className="cursor-pointer" onClick={() => handleSort('before')}>
            Before{sortKey === 'before' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </th>
          <th className="cursor-pointer" onClick={() => handleSort('next')}>
            Next bar{sortKey === 'next' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </th>
          <th className="cursor-pointer" onClick={() => handleSort('forward')}>
            After{sortKey === 'forward' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </th>
          <th>MFE / MAE</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((m) => (
          <tr key={`${m.match_end}-${m.rank}`}>
            <td className="text-slate-400">{String(m.rank ?? '')}</td>
            <td className="font-medium text-slate-200">{String(m.similarity ?? '—')}%</td>
            <td className="whitespace-nowrap text-xs text-slate-300">
              <div>{String(m.match_start ?? '').slice(0, 16)}</div>
              <div className="text-slate-500">→ {String(m.match_end ?? '').slice(0, 16)}</div>
            </td>
            <td className="text-xs text-slate-400">
              {String(m.shape_label ?? '—')}
              <div className="text-slate-500">{pct(m.match_net_return_pct)}</div>
            </td>
            <td>
              <span className={Number(m.before_return_pct) >= 0 ? 'text-sky-300' : 'text-sky-400/80'}>
                {pct(m.before_return_pct)}
              </span>
              <div className="text-[11px] text-slate-500">{String(m.before_direction ?? '')}</div>
            </td>
            <td>
              <span className={Number(m.next_bar_return_pct) >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                {pct(m.next_bar_return_pct)}
              </span>
              <div className="text-[11px] text-slate-500">{String(m.next_direction ?? '')}</div>
            </td>
            <td>
              <span className={Number(m.forward_return_pct) >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                {pct(m.forward_return_pct)}
              </span>
              <div className="text-[11px] text-slate-500">{String(m.forward_direction ?? '')}</div>
            </td>
            <td className="text-xs text-slate-400">
              <span className="text-emerald-400/90">{pct(m.max_favorable_pct)}</span>
              {' / '}
              <span className="text-rose-400/90">{pct(m.max_adverse_pct)}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  )
}

function PatternChartsBlock({ template, matches }: { template: Row; matches: Row[] }) {
  const baseCandles = asCandles(template.candles)
  const overlayMatches = matches.slice(0, 6).map((m, i) => ({
    id: `m${m.rank ?? i}`,
    label: `#${m.rank ?? i + 1} · ${String(m.similarity ?? '—')}%`,
    shape_pct: Array.isArray(m.shape_pct) ? (m.shape_pct as number[]) : [],
  }))
  const fromImage = String(template.source || '') === 'chart_image'

  if (!baseCandles.length && !matches.some((m) => asCandles(m.candles).length)) {
    return null
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-sky-300/90">
          {fromImage ? 'Digitized chart template' : 'Base pattern (live template)'}
        </p>
        <PatternCandleChart
          candles={baseCandles}
          height={200}
          title={String(template.shape_label || 'Current window')}
          subtitle={
            fromImage
              ? `From screenshot · net ${pct(template.net_return_pct)}${template.digitizer ? ` · ${String(template.digitizer)}` : ''}`
              : `${String(template.start_time || '').slice(0, 16)} → ${String(template.end_time || '').slice(0, 16)} · net ${pct(template.net_return_pct)}`
          }
        />
      </div>

      {overlayMatches.some((m) => m.shape_pct.length) ? (
        <PatternShapeOverlay
          base={{ shape_pct: Array.isArray(template.shape_pct) ? (template.shape_pct as number[]) : [], label: 'Base' }}
          matches={overlayMatches}
          height={170}
        />
      ) : null}

      {matches.length > 0 ? (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-violet-300/90">
            Historical matches — before · pattern · after
          </p>
          <div className="grid gap-3 lg:grid-cols-2">
            {matches.map((m) => {
              const candles = asCandles(m.candles)
              const fwd = asCandles(m.forward_candles)
              const before = asCandles(m.before_candles)
              if (!candles.length) return null
              return (
                <PatternCandleChart
                  key={`${m.rank}-${m.match_end}`}
                  candles={candles}
                  beforeCandles={before}
                  forwardCandles={fwd}
                  height={150}
                  compact
                  title={`#${m.rank} · ${String(m.similarity ?? '—')}% similar · ${String(m.shape_label ?? '')}`}
                  subtitle={`${String(m.match_start || '').slice(0, 16)} → ${String(m.match_end || '').slice(0, 16)} · before ${pct(m.before_return_pct)} · next ${pct(m.next_bar_return_pct)} · after ${pct(m.forward_return_pct)}`}
                />
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function TickerCard({ result, index }: { result: Row; index: number }) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade))
  const pred = (result.prediction as Row) || {}
  const summary = (result.outcome_summary as Row) || {}
  const template = (result.template as Row) || {}
  const matches = (result.matches as Row[]) || []
  const bias = String(pred.bias || result.signal || 'WAIT')
  const trade = resolveTradeSuggestion(result)
  const currency = String(result.currency ?? '')

  return (
    <div className="rounded-xl border border-slate-800/70 bg-slate-950/40">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">{String(result.ticker)}</span>
            <Badge action={biasTone(bias)} />
            {result.confidence_pct != null && (
              <span className="text-xs text-slate-400">{String(result.confidence_pct)}% conf</span>
            )}
            {trade.sl_pct != null && (
              <span className="text-xs text-rose-300/90">SL {String(trade.sl_pct)}%</span>
            )}
            {trade.tp_pct != null && (
              <span className="text-xs text-emerald-300/90">TP {String(trade.tp_pct)}%</span>
            )}
            {String(result.template_source) === 'chart_image' ? (
              <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-300">FROM CHART IMAGE</span>
            ) : null}
            {result.take_trade ? (
              <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-300">ACTIONABLE</span>
            ) : null}
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-slate-400">
            {String(pred.plain_english || result.error || '—')}
          </p>
        </div>
        <span className="shrink-0 text-slate-500">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-slate-800/60 px-4 py-3">
          {result.error && !matches.length ? (
            <p className="text-sm text-rose-300">{String(result.error)}</p>
          ) : (
            <>
              {trade.action != null && (
                <TradeSignalBlock
                  trade={trade}
                  currency={currency}
                  legend="BUY / SELL / WAIT from historical analogues · SL% ≈ avg MAE · TP% ≈ avg MFE / forward move"
                />
              )}

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">
                    {String(template.source) === 'chart_image' ? 'Chart template' : 'Current template'}
                  </p>
                  <p className="mt-1 text-sm text-slate-200">{String(template.shape_label ?? '—')}</p>
                  {String(template.source) === 'chart_image' ? (
                    <p className="text-xs text-slate-400">Digitized · Net {pct(template.net_return_pct)}</p>
                  ) : (
                    <>
                      <p className="text-xs text-slate-400">
                        {String(template.start_time ?? '').slice(0, 16)} → {String(template.end_time ?? '').slice(0, 16)}
                      </p>
                      <p className="text-xs text-slate-400">Net {pct(template.net_return_pct)} · LTP {String(template.ltp ?? '—')}</p>
                    </>
                  )}
                </div>
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Samples</p>
                  <p className="mt-1 text-lg font-semibold text-white">{String(summary.samples ?? matches.length)}</p>
                  <p className="text-xs text-slate-400">Avg sim {String(summary.avg_similarity_pct ?? '—')}%</p>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Before (hist)</p>
                  <p className={`mt-1 text-lg font-semibold ${Number(summary.avg_before_return_pct) >= 0 ? 'text-sky-300' : 'text-sky-400'}`}>
                    {pct(summary.avg_before_return_pct)}
                  </p>
                  <p className="text-xs text-slate-400">Up rate {String(summary.before_up_pct ?? '—')}%</p>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Next bar (hist)</p>
                  <p className={`mt-1 text-lg font-semibold ${Number(summary.avg_next_bar_return_pct) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                    {pct(summary.avg_next_bar_return_pct)}
                  </p>
                  <p className="text-xs text-slate-400">Up rate {String(summary.next_bar_up_pct ?? '—')}%</p>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">After (hist)</p>
                  <p className={`mt-1 text-lg font-semibold ${Number(summary.avg_forward_return_pct) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                    {pct(summary.avg_forward_return_pct)}
                  </p>
                  <p className="text-xs text-slate-400">
                    Median {pct(summary.median_forward_return_pct)} · Up {String(summary.forward_up_pct ?? '—')}%
                  </p>
                </div>
              </div>

              <PatternChartsBlock template={template} matches={matches} />

              <MatchTable matches={matches} />

              {result.ai_context ? (
                <AskAIPanel context={String(result.ai_context)} section="prediction/pattern-analogue" />
              ) : null}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function PatternAnaloguePanel({ data }: { data: Row }) {
  const results = useMemo(() => ((data?.results as Row[]) ?? []), [data])
  const cfg = (data?.config as Row) || {}

  if (!results.length) {
    return <p className="text-sm text-slate-500">{String(data?.error || 'No results')}</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>{String(data.strategy || 'Pattern Analogue')}</span>
        <span>
          TF {String(data.timeframe)} · pattern {String(cfg.pattern_bars ?? data.pattern_bars)} bars · before{' '}
          {String(cfg.before_bars ?? data.before_bars ?? 5)} · after {String(cfg.forward_bars ?? data.forward_bars)} bars
        </span>
        <span>
          Scanned {String(data.scanned ?? results.length)} · actionable {String(data.entry_count ?? 0)}
        </span>
        {String(data.template_source) === 'chart_image' ? (
          <span className="text-sky-400/90">Template from chart image</span>
        ) : null}
      </div>
      {results.map((r, i) => (
        <TickerCard key={String(r.ticker || i)} result={r} index={i} />
      ))}
      {data.disclaimer ? <p className="text-[11px] text-slate-600">{String(data.disclaimer)}</p> : null}
    </div>
  )
}
