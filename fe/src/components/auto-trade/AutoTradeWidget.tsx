import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight, Radar } from 'lucide-react'
import { fetchAutoTradeSetups, fetchAutoTradeSuggestions } from '../../api/client'
import { Card } from '../ui/Card'

function actionColor(action: string): string {
  if (action === 'BUY') return 'text-emerald-400'
  if (action === 'SELL') return 'text-rose-400'
  return 'text-amber-400'
}

export function AutoTradeWidget({ limit = 5 }: { limit?: number }) {
  const setupsQuery = useQuery({ queryKey: ['auto-trade-setups'], queryFn: fetchAutoTradeSetups })
  const suggestionsQuery = useQuery({ queryKey: ['auto-trade-suggestions'], queryFn: () => fetchAutoTradeSuggestions() })

  const setups = setupsQuery.data?.setups ?? []
  const runningCount = setups.filter((s) => s.enabled).length
  const everRun = setups.some((s) => s.last_run_at)

  const top = useMemo(
    () =>
      [...(suggestionsQuery.data?.suggestions ?? [])]
        .filter((s) => s.action !== 'WAIT')
        .sort((a, b) => b.confidence_pct - a.confidence_pct)
        .slice(0, limit),
    [suggestionsQuery.data, limit],
  )

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

      {setups.length === 0 ? (
        <p className="text-sm text-slate-500">
          No setups yet — open Auto Trade to create one for any market + trading style you want scanned automatically.
        </p>
      ) : !everRun ? (
        <p className="text-sm text-slate-500">
          {setups.length} setup{setups.length === 1 ? '' : 's'} created, none run yet — start one or click "Run now" in Auto Trade.
        </p>
      ) : top.length === 0 ? (
        <p className="text-sm text-slate-500">Latest sweeps found no actionable BUY/SELL ideas — everything is a WAIT right now.</p>
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

      {setups.length > 0 && (
        <p className="mt-2 text-[11px] text-slate-600">
          {runningCount} of {setups.length} setup{setups.length === 1 ? '' : 's'} running
        </p>
      )}
    </Card>
  )
}
