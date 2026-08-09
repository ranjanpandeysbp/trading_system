import { useMemo, useState } from 'react'
import { Badge } from '../ui/Badge'
import { DataTable } from '../ui/Table'
import { AskAIPanel } from '../ai/AskAIPanel'

type Row = Record<string, unknown>

function tone(bias: string): 'BUY' | 'SELL' | 'HOLD' {
  const b = (bias || '').toUpperCase()
  if (b.includes('BUY') || b === 'LONG') return 'BUY'
  if (b.includes('SELL') || b === 'SHORT') return 'SELL'
  return 'HOLD'
}

function ResultCard({ result, index }: { result: Row; index: number }) {
  const [open, setOpen] = useState(index === 0)
  const pred = (result.prediction as Row) || {}
  const live = (result.live as Row) || {}
  const bias = String(pred.bias || live.verdict || 'WAIT')

  return (
    <div className="rounded-xl border border-slate-800/70 bg-slate-950/40">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">{String(result.ticker || result.strategy || 'Calendar')}</span>
            <Badge action={tone(bias)} />
            {live.confidence_pct != null && (
              <span className="text-xs text-slate-400">{String(live.confidence_pct)}% conf</span>
            )}
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-slate-400">
            {String(pred.plain_english || result.error || '—')}
          </p>
        </div>
        <span className="shrink-0 text-slate-500">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-4 py-3 text-sm text-slate-300">
          {result.error ? (
            <p className="text-rose-300">{String(result.error)}</p>
          ) : (
            <>
              {result.now ? (
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
                  {Object.entries(result.now as Row).map(([k, v]) => (
                    <div key={k} className="rounded-lg bg-slate-900/50 p-2">
                      <p className="text-slate-500">{k}</p>
                      <p className="text-slate-200">{String(v)}</p>
                    </div>
                  ))}
                </div>
              ) : null}

              {Array.isArray(result.upcoming_events) && (result.upcoming_events as Row[]).length > 0 && (
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-400">Upcoming lunar events</p>
                  <DataTable title="lunar-events">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Type</th>
                        <th>Elong°</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(result.upcoming_events as Row[]).map((e) => (
                        <tr key={`${e.date}-${e.type}`}>
                          <td>{String(e.date)}</td>
                          <td>{String(e.type)}</td>
                          <td>{String(e.elongation_deg ?? '—')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              )}

              {(result.stats_amavasya || result.stats_poornima) && (
                <div className="grid gap-2 sm:grid-cols-2 text-xs">
                  {(['stats_amavasya', 'stats_poornima'] as const).map((key) => {
                    const s = (result[key] as Row) || {}
                    return (
                      <div key={key} className="rounded-lg bg-slate-900/50 p-3">
                        <p className="font-medium text-slate-200">{key.replace('stats_', '')}</p>
                        <p>n={String(s.samples ?? 0)}</p>
                        <p>Avg fwd {String(s.avg_forward_return_pct ?? '—')}%</p>
                        <p>Up rate {String(s.up_rate_pct ?? '—')}%</p>
                        <p>Avg range {String(s.avg_range_pct ?? '—')}%</p>
                      </div>
                    )
                  })}
                </div>
              )}

              {(Array.isArray(result.supports) || Array.isArray(result.resistances)) && (
                <div className="grid gap-3 lg:grid-cols-2">
                  <div>
                    <p className="mb-1 text-xs font-medium text-emerald-300/90">Amavasya supports</p>
                    <DataTable title="amavasya-supports">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Low</th>
                          <th>Touches</th>
                        </tr>
                      </thead>
                      <tbody>
                        {((result.supports as Row[]) || []).map((s) => (
                          <tr key={`s-${s.amavasya_date}-${s.low}`}>
                            <td>{String(s.amavasya_date)}</td>
                            <td>{String(s.low)}</td>
                            <td>{String(s.touches ?? '—')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-medium text-rose-300/90">Amavasya resistances</p>
                    <DataTable title="amavasya-resistances">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>High</th>
                          <th>Touches</th>
                        </tr>
                      </thead>
                      <tbody>
                        {((result.resistances as Row[]) || []).map((s) => (
                          <tr key={`r-${s.amavasya_date}-${s.high}`}>
                            <td>{String(s.amavasya_date)}</td>
                            <td>{String(s.high)}</td>
                            <td>{String(s.touches ?? '—')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </div>
                </div>
              )}

              {Array.isArray(result.bhadra_windows) && (
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-400">
                    Bhadra windows {result.bhadra_active_now ? '(ACTIVE now)' : ''}
                  </p>
                  <DataTable title="bhadra-windows">
                    <thead>
                      <tr>
                        <th>Start</th>
                        <th>End</th>
                        <th>TZ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {((result.bhadra_windows as Row[]) || []).slice(0, 12).map((w) => (
                        <tr key={`${w.start}-${w.end}`}>
                          <td className="text-xs">{String(w.start).slice(0, 19)}</td>
                          <td className="text-xs">{String(w.end).slice(0, 19)}</td>
                          <td>{String(w.timezone)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              )}

              {(result.stats_mars || result.stats_venus) && (
                <div className="grid gap-2 sm:grid-cols-2 text-xs">
                  {(['stats_mars', 'stats_venus'] as const).map((key) => {
                    const s = (result[key] as Row) || {}
                    return (
                      <div key={key} className="rounded-lg bg-slate-900/50 p-3">
                        <p className="font-medium text-slate-200">{key.replace('stats_', '')}</p>
                        <p>n={String(s.samples ?? 0)}</p>
                        <p>Gap up {String(s.gap_up_pct ?? '—')}%</p>
                        <p>Gap down {String(s.gap_down_pct ?? '—')}%</p>
                        <p>Avg |gap| {String(s.avg_abs_gap_pct ?? '—')}%</p>
                      </div>
                    )
                  })}
                </div>
              )}

              {Array.isArray(result.upcoming_ingresses) && (result.upcoming_ingresses as Row[]).length > 0 && (
                <DataTable title="ingresses">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Planet</th>
                      <th>Into</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.upcoming_ingresses as Row[]).map((e) => (
                      <tr key={`${e.date}-${e.planet}`}>
                        <td>{String(e.date)}</td>
                        <td>{String(e.planet)}</td>
                        <td>
                          {String(e.from_sign)} → {String(e.to_sign)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              )}

              {Array.isArray(result.favorable_days_next_35) && (
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-400">Favorable Moon-sign days</p>
                  <DataTable title="fav-days">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Moon sign</th>
                        <th>Phase</th>
                      </tr>
                    </thead>
                    <tbody>
                      {((result.favorable_days_next_35 as Row[]) || []).slice(0, 14).map((d) => (
                        <tr key={String(d.date)}>
                          <td>{String(d.date)}</td>
                          <td>{String(d.moon_sign)}</td>
                          <td className="text-xs">{String(d.phase)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              )}

              {Array.isArray(result.muhurat_today) && (
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-400">Today’s Muhurat (approx sunrise→sunset)</p>
                  <DataTable title="muhurat">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Start</th>
                        <th>End</th>
                        <th>Exec?</th>
                      </tr>
                    </thead>
                    <tbody>
                      {((result.muhurat_today as Row[]) || []).map((m) => (
                        <tr key={String(m.name) + String(m.start_local)}>
                          <td>{String(m.name)}</td>
                          <td className="text-xs">{String(m.start_local).slice(11, 19)}</td>
                          <td className="text-xs">{String(m.end_local).slice(11, 19)}</td>
                          <td>{m.favorable_execution ? 'Yes' : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              )}

              {Array.isArray(result.commodity_planet_map) && (
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-400">Commodity ↔ planet map</p>
                  <DataTable title="commodity-planets">
                    <thead>
                      <tr>
                        <th>Commodity</th>
                        <th>Planets</th>
                        <th>Symbols</th>
                      </tr>
                    </thead>
                    <tbody>
                      {((result.commodity_planet_map as Row[]) || []).map((c) => (
                        <tr key={String(c.commodity)}>
                          <td>{String(c.commodity)}</td>
                          <td>{String(c.planets)}</td>
                          <td className="text-xs">{((c.symbols as string[]) || []).join(', ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              )}

              {result.fifth_house_note ? (
                <p className="text-xs text-slate-500">{String(result.fifth_house_note)}</p>
              ) : null}
              {result.remedies_note ? (
                <p className="text-xs text-slate-600">{String(result.remedies_note)}</p>
              ) : null}

              {result.ai_context ? (
                <AskAIPanel context={String(result.ai_context)} section="prediction/astro-finance" />
              ) : null}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function AstroFinancePanel({ data }: { data: Row }) {
  const results = useMemo(() => ((data?.results as Row[]) ?? []), [data])
  if (!results.length) {
    return <p className="text-sm text-slate-500">{String(data?.error || 'No results')}</p>
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>{String(data.strategy_label || data.strategy)}</span>
        <span>
          Scanned {String(data.scanned ?? results.length)} · actionable {String(data.entry_count ?? 0)}
        </span>
      </div>
      {results.map((r, i) => (
        <ResultCard key={String(r.ticker || r.strategy || i)} result={r} index={i} />
      ))}
      {data.disclaimer ? <p className="text-[11px] text-slate-600">{String(data.disclaimer)}</p> : null}
    </div>
  )
}
