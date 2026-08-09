import { useMemo, useState } from 'react'
import { Badge } from '../ui/Badge'
import { DataTable, useSort } from '../ui/Table'
import { AskAIPanel } from '../ai/AskAIPanel'

type Row = Record<string, unknown>

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

function MatchTable({ matches }: { matches: Row[] }) {
  const { sorted, sortKey, sortDir, handleSort } = useSort(
    matches,
    {
      rank: (r) => Number(r.rank ?? 0),
      similarity: (r) => Number(r.similarity ?? 0),
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
    <DataTable title="Historical analogues">
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
          <th className="cursor-pointer" onClick={() => handleSort('next')}>
            Next bar{sortKey === 'next' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </th>
          <th className="cursor-pointer" onClick={() => handleSort('forward')}>
            Forward{sortKey === 'forward' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
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

function TickerCard({ result, index }: { result: Row; index: number }) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade))
  const pred = (result.prediction as Row) || {}
  const summary = (result.outcome_summary as Row) || {}
  const template = (result.template as Row) || {}
  const matches = (result.matches as Row[]) || []
  const bias = String(pred.bias || result.signal || 'WAIT')

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
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Current template</p>
                  <p className="mt-1 text-sm text-slate-200">{String(template.shape_label ?? '—')}</p>
                  <p className="text-xs text-slate-400">
                    {String(template.start_time ?? '').slice(0, 16)} → {String(template.end_time ?? '').slice(0, 16)}
                  </p>
                  <p className="text-xs text-slate-400">Net {pct(template.net_return_pct)} · LTP {String(template.ltp ?? '—')}</p>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Samples</p>
                  <p className="mt-1 text-lg font-semibold text-white">{String(summary.samples ?? matches.length)}</p>
                  <p className="text-xs text-slate-400">Avg sim {String(summary.avg_similarity_pct ?? '—')}%</p>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Next bar (hist)</p>
                  <p className={`mt-1 text-lg font-semibold ${Number(summary.avg_next_bar_return_pct) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                    {pct(summary.avg_next_bar_return_pct)}
                  </p>
                  <p className="text-xs text-slate-400">Up rate {String(summary.next_bar_up_pct ?? '—')}%</p>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">Forward (hist)</p>
                  <p className={`mt-1 text-lg font-semibold ${Number(summary.avg_forward_return_pct) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                    {pct(summary.avg_forward_return_pct)}
                  </p>
                  <p className="text-xs text-slate-400">
                    Median {pct(summary.median_forward_return_pct)} · Up {String(summary.forward_up_pct ?? '—')}%
                  </p>
                </div>
              </div>

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
          TF {String(data.timeframe)} · pattern {String(cfg.pattern_bars ?? data.pattern_bars)} bars · forward{' '}
          {String(cfg.forward_bars ?? data.forward_bars)} bars
        </span>
        <span>
          Scanned {String(data.scanned ?? results.length)} · actionable {String(data.entry_count ?? 0)}
        </span>
      </div>
      {results.map((r, i) => (
        <TickerCard key={String(r.ticker || i)} result={r} index={i} />
      ))}
      {data.disclaimer ? <p className="text-[11px] text-slate-600">{String(data.disclaimer)}</p> : null}
    </div>
  )
}
