import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BarChart3,
  Bot,
  Clapperboard,
  Crosshair,
  Landmark,
  Search,
  Wallet,
  Layers,
  BookOpen,
  LineChart,
} from 'lucide-react'
import { getAccount, fetchStrategies } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { StatCard } from '../components/ui/StatCard'
import { Card } from '../components/ui/Card'
import { Loading } from '../components/ui/Feedback'
import { DataTable, SortableTh, Td, useSort } from '../components/ui/Table'
import { AutoTradeWidget } from '../components/auto-trade/AutoTradeWidget'

const quickLinks = [
  {
    to: '/pro-trade/pa-vp-smc',
    title: 'PA-VP-SMC',
    description:
      'Price Action + Volume Profile + Smart Money Concepts confluence · confidence-scored actionable trades',
    icon: Crosshair,
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
  },
  {
    to: '/investing-agent',
    title: 'Investing Agent',
    description: 'AI research agent for stocks and markets — ask, investigate, and get reasoned investment views.',
    icon: Bot,
    color: 'text-indigo-400',
    bg: 'bg-indigo-500/10',
  },
  {
    to: '/youtube-analysis',
    title: 'Youtube Analysis',
    description: 'Pull YouTube strategy videos and Gemini transcripts to extract trade ideas and rules.',
    icon: Clapperboard,
    color: 'text-red-400',
    bg: 'bg-red-500/10',
  },
  {
    to: '/command-center?tab=mutual_fund_holdings',
    title: 'Mutual Fund Holdings',
    description: 'Command Center — track stock-level holdings trends across Indian mutual funds.',
    icon: Landmark,
    color: 'text-teal-400',
    bg: 'bg-teal-500/10',
  },
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
  {
    to: '/trading-hubs?hub=swing&section=support_resistance',
    title: 'Support & Resistance Analysis',
    description: 'Break-and-retest zones, trendlines, EMA/RSI overlays, trade setups, breakout odds, candlestick patterns, and divergences.',
    icon: LineChart,
    color: 'text-cyan-400',
    bg: 'bg-cyan-500/10',
  },
]

export default function Dashboard() {
  const { data: account, isLoading: accLoading } = useQuery({
    queryKey: ['account'],
    queryFn: getAccount,
    refetchInterval: 15_000,
    refetchIntervalInBackground: true,
  })
  const { data: strategies } = useQuery({ queryKey: ['strategies'], queryFn: fetchStrategies })

  const { sorted: sortedPositions, sortKey: posSortKey, sortDir: posSortDir, handleSort: handlePosSort } = useSort(
    account?.positions ?? [],
    {
      ticker: (r) => r.ticker,
      quantity: (r) => r.quantity,
      avg_price: (r) => r.avg_price,
      ltp: (r) => r.ltp,
      pnl: (r) => r.pnl,
    },
  )

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

      <div className="mt-8">
        <AutoTradeWidget />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
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
                <SortableTh active={posSortKey === 'ticker'} direction={posSortDir} onSort={() => handlePosSort('ticker')}>Ticker</SortableTh>
                <SortableTh active={posSortKey === 'quantity'} direction={posSortDir} onSort={() => handlePosSort('quantity')}>Qty</SortableTh>
                <SortableTh active={posSortKey === 'avg_price'} direction={posSortDir} onSort={() => handlePosSort('avg_price')}>Avg</SortableTh>
                <SortableTh active={posSortKey === 'ltp'} direction={posSortDir} onSort={() => handlePosSort('ltp')}>LTP</SortableTh>
                <SortableTh active={posSortKey === 'pnl'} direction={posSortDir} onSort={() => handlePosSort('pnl')}>P&L</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedPositions.map((p) => (
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
