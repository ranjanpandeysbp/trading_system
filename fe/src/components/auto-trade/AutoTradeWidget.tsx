import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight, Radar } from 'lucide-react'
import { fetchAutoTradeSchedule, fetchAutoTradeSuggestions } from '../../api/client'
import { Card } from '../ui/Card'

function actionColor(action: string): string {
  if (action === 'BUY') return 'text-emerald-400'
  if (action === 'SELL') return 'text-rose-400'
  return 'text-amber-400'
}

export function AutoTradeWidget({ limit = 5 }: { limit?: number }) {
  const scheduleQuery = useQuery({ queryKey: ['auto-trade-schedule'], queryFn: fetchAutoTradeSchedule })
  const suggestionsQuery = useQuery({ queryKey: ['auto-trade-suggestions'], queryFn: () => fetchAutoTradeSuggestions() })

  const top = useMemo(
    () =>
      [...(suggestionsQuery.data?.suggestions ?? [])]
        .filter((s) => s.action !== 'WAIT')
        .sort((a, b) => b.confidence_pct - a.confidence_pct)
        .slice(0, limit),
    [suggestionsQuery.data, limit],
  )

  const schedule = scheduleQuery.data

  return (
    <Card className="mb-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="inline-flex items-center gap-2 font-semibold text-white">
          <Radar size={16} className="text-teal-400" /> Auto Trade
        </h3>
        <Link to="/auto-trade" className="inline-flex items-center gap-1 text-xs font-medium text-blue-400 hover:text-blue-300">
          Open <ArrowRight size={12} />
        </Link>
      </div>

      {!schedule?.last_run_at ? (
        <p className="text-sm text-slate-500">
          Not run yet — open Auto Trade to start automated scanning across India, US, Crypto and Commodities.
        </p>
      ) : top.length === 0 ? (
        <p className="text-sm text-slate-500">Last sweep found no actionable BUY/SELL ideas — everything is a WAIT right now.</p>
      ) : (
        <div className="space-y-1.5">
          {top.map((s) => (
            <div key={s.id} className="flex items-center justify-between gap-2 rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-1.5 text-sm">
              <span className="font-medium text-white">{s.ticker}</span>
              <span className="text-xs text-slate-500">{s.asset_class} · {s.style}</span>
              <span className={`text-xs font-semibold ${actionColor(s.action)}`}>{s.action}</span>
              <span className="text-xs text-slate-400">{s.confidence_pct.toFixed(0)}% · {s.grade}</span>
            </div>
          ))}
        </div>
      )}

      {schedule?.enabled && (
        <p className="mt-2 text-[11px] text-slate-600">
          Automation running every {schedule.interval_minutes}m — {schedule.last_status || 'awaiting first run'}
        </p>
      )}
    </Card>
  )
}
