import { type ReactNode } from 'react'
import { Card } from './Card'

interface StatCardProps {
  label: string
  value: ReactNode
  trend?: 'up' | 'down' | 'neutral'
  icon?: ReactNode
}

export function StatCard({ label, value, trend = 'neutral', icon }: StatCardProps) {
  const trendColors = {
    up: 'text-emerald-400',
    down: 'text-rose-400',
    neutral: 'text-white',
  }

  return (
    <Card className="relative overflow-hidden">
      <div className="absolute -right-4 -top-4 h-24 w-24 rounded-full bg-blue-500/5 blur-2xl" />
      <div className="relative flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[10px] font-medium uppercase tracking-wider text-slate-500 sm:text-xs">
            {label}
          </p>
          <p className={`mt-1.5 text-lg font-bold tabular-nums sm:mt-2 sm:text-2xl ${trendColors[trend]}`}>
            {value}
          </p>
        </div>
        {icon && <div className="shrink-0 rounded-xl bg-slate-800/80 p-2 text-blue-400 sm:p-2.5">{icon}</div>}
      </div>
    </Card>
  )
}
