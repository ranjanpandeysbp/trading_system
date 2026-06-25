import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight, BarChart3, Search, Wallet, Layers, BookOpen } from 'lucide-react'
import { getAccount, fetchStrategies } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { StatCard } from '../components/ui/StatCard'
import { Card } from '../components/ui/Card'
import { Loading } from '../components/ui/Feedback'
import { DataTable, Th, Td } from '../components/ui/Table'

const quickLinks = [
  {
    to: '/strategies',
    title: 'Strategy Library',
    description: 'Browse 15 strategies by Scalping, Intraday, and Swing — read rules, indicators, and entry/exit logic.',
    icon: BookOpen,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
  },
  {
    to: '/scanner',
    title: 'Strategy Scanner',
    description: 'Scan multiple tickers across strategies and timeframes. Get BUY/SELL with SL%, TP%, and confidence.',
    icon: Search,
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
  },
  {
    to: '/backtester',
    title: 'Backtester',
    description: 'Evaluate strategy performance on historical data with transparent cost modelling.',
    icon: BarChart3,
    color: 'text-violet-400',
    bg: 'bg-violet-500/10',
  },
  {
    to: '/paper',
    title: 'Paper Trading',
    description: 'Execute demo trades from scanner signals or manual orders with virtual capital.',
    icon: Wallet,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
  },
]

export default function Dashboard() {
  const { data: account, isLoading: accLoading } = useQuery({ queryKey: ['account'], queryFn: getAccount })
  const { data: strategies } = useQuery({ queryKey: ['strategies'], queryFn: fetchStrategies })

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Paper trading demo for Indian equities — scanner, backtester, and 15 rule-based strategies"
      />

      {accLoading ? (
        <Loading message="Loading portfolio..." />
      ) : account ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Portfolio Value" value={`₹${account.portfolio_value.toLocaleString('en-IN')}`} />
          <StatCard label="Cash Balance" value={`₹${account.cash_balance.toLocaleString('en-IN')}`} />
          <StatCard
            label="Total P&L"
            value={`₹${account.total_pnl.toLocaleString('en-IN')} (${account.total_pnl_pct}%)`}
            trend={account.total_pnl >= 0 ? 'up' : 'down'}
          />
          <StatCard
            label="Strategies"
            value={strategies?.length ?? 15}
            icon={<Layers size={20} />}
          />
        </div>
      ) : null}

      <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {quickLinks.map(({ to, title, description, icon: Icon, color, bg }) => (
          <Link key={to} to={to}>
            <Card hover className="group h-full">
              <div className={`mb-4 inline-flex rounded-xl p-2.5 ${bg}`}>
                <Icon size={22} className={color} />
              </div>
              <h3 className="mb-2 font-semibold text-white group-hover:text-blue-300">{title}</h3>
              <p className="mb-4 text-sm leading-relaxed text-slate-500">{description}</p>
              <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-400">
                Open <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" />
              </span>
            </Card>
          </Link>
        ))}
      </div>

      {account && account.positions.length > 0 && (
        <Card className="mt-8">
          <h3 className="mb-4 text-lg font-semibold text-white">Open Positions</h3>
          <DataTable>
            <thead>
              <tr>
                <Th>Ticker</Th>
                <Th>Qty</Th>
                <Th>Avg</Th>
                <Th>LTP</Th>
                <Th>P&L</Th>
              </tr>
            </thead>
            <tbody>
              {account.positions.map((p) => (
                <tr key={p.id} className="hover:bg-slate-800/30">
                  <Td className="font-medium text-white">{p.ticker}</Td>
                  <Td>{p.quantity}</Td>
                  <Td>₹{p.avg_price}</Td>
                  <Td>₹{p.ltp}</Td>
                  <Td className={p.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    ₹{p.pnl} ({p.pnl_pct}%)
                  </Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Card>
      )}
    </div>
  )
}
