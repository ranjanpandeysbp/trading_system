import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  ChevronRight,
  Clock,
  Droplets,
  Layers,
  LineChart,
  Scale,
  Search,
  Sparkles,
  X,
  Zap,
} from 'lucide-react'
import { fetchStrategyCategories, type StrategyInfo } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { Loading } from '../components/ui/Feedback'

const CATEGORY_STYLES: Record<string, { icon: typeof Zap; accent: string; chip: string }> = {
  scalping: { icon: Zap, accent: 'text-amber-400', chip: 'bg-amber-500/15 text-amber-300' },
  intraday: { icon: Clock, accent: 'text-blue-400', chip: 'bg-blue-500/15 text-blue-300' },
  swing: { icon: Layers, accent: 'text-violet-400', chip: 'bg-violet-500/15 text-violet-300' },
}

const RESEARCH_LINKS = [
  {
    to: '/command-center?tab=oil_dollar_bond',
    title: 'Oil · Dollar · Bond',
    description: 'Macro tape with S/R — DXY, Brent, yields, metals, Nifty/Dow/Nasdaq, BTC/ETH',
    icon: Droplets,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
  },
  {
    to: '/pro-trade/ticker-chart',
    title: 'Ticker Chart',
    description: 'India / US / Crypto / Commodities OHLC with autosuggest + S1/S2 · R1/R2',
    icon: LineChart,
    color: 'text-sky-400',
    bg: 'bg-sky-500/10',
  },
  {
    to: '/command-center?tab=advance_decline_graph',
    title: 'Advance Decline',
    description: 'Multi-asset breadth — healthy vs hollow advances',
    icon: Activity,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
  },
  {
    to: '/command-center?tab=comparative_strength',
    title: 'Comparative Strength',
    description: 'Relative long/short vs a base index or ticker',
    icon: Scale,
    color: 'text-lime-400',
    bg: 'bg-lime-500/10',
  },
  {
    to: '/options?section=market_prediction',
    title: 'Market Prediction',
    description: 'Options — is today’s move backed by derivatives conviction?',
    icon: Sparkles,
    color: 'text-fuchsia-400',
    bg: 'bg-fuchsia-500/10',
  },
  {
    to: '/strategy-lab',
    title: 'Strategy Encyclopedia',
    description: 'Full hub map, workflows, and when-to-use matrix for every section',
    icon: BookOpen,
    color: 'text-violet-400',
    bg: 'bg-violet-500/10',
  },
] as const

function StrategyDetail({ strategy, onClose }: { strategy: StrategyInfo; onClose: () => void }) {
  const style = CATEGORY_STYLES[strategy.category] ?? CATEGORY_STYLES.intraday

  return (
    <Card className="lg:sticky lg:top-6">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${style.chip}`}>
            {strategy.category_label}
          </span>
          <h3 className="mt-2 text-xl font-semibold text-white">{strategy.name}</h3>
          <p className="mt-1 text-sm text-slate-400">{strategy.summary}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="font-medium uppercase tracking-wider text-slate-500">Data source</span>
            <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 font-semibold text-emerald-300 ring-1 ring-emerald-500/30">Groww</span>
            <span className="text-slate-600">India primary</span>
            <span className="rounded-md bg-sky-500/15 px-2 py-0.5 font-semibold text-sky-300 ring-1 ring-sky-500/30">yfinance</span>
            <span className="text-slate-600">US / fallback</span>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-2 text-slate-500 hover:bg-slate-800 hover:text-white lg:hidden"
          aria-label="Close details"
        >
          <X size={18} />
        </button>
      </div>

      <p className="text-sm leading-relaxed text-slate-300">{strategy.description}</p>

      <div className="mt-5 flex flex-wrap gap-2">
        {strategy.timeframes.map((tf) => (
          <span key={tf} className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-300">{tf}</span>
        ))}
        {strategy.needs_benchmark && (
          <span className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-300">Benchmark index</span>
        )}
        <span className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-300">Min {strategy.min_bars} bars</span>
      </div>

      {strategy.indicators.length > 0 && (
        <div className="mt-5">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Indicators</h4>
          <div className="flex flex-wrap gap-2">
            {strategy.indicators.map((ind) => (
              <span key={ind} className="rounded-lg border border-slate-700/60 px-2.5 py-1 text-xs text-slate-300">{ind}</span>
            ))}
          </div>
        </div>
      )}

      {strategy.entry_rules.length > 0 && (
        <div className="mt-5">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Entry rules</h4>
          <ul className="space-y-2 text-sm text-slate-300">
            {strategy.entry_rules.map((rule) => (
              <li key={rule} className="flex gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                {rule}
              </li>
            ))}
          </ul>
        </div>
      )}

      {strategy.exit_rules.length > 0 && (
        <div className="mt-5">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Exit rules</h4>
          <ul className="space-y-2 text-sm text-slate-300">
            {strategy.exit_rules.map((rule) => (
              <li key={rule} className="flex gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" />
                {rule}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-6 flex flex-col gap-2 sm:flex-row">
        <Link to={`/scanner?strategy=${strategy.id}`} className="flex-1">
          <Button variant="secondary" className="w-full">
            <Search size={16} />
            Scan with strategy
          </Button>
        </Link>
        <Link to={`/backtester?strategy=${strategy.id}`} className="flex-1">
          <Button className="w-full">
            <BarChart3 size={16} />
            Backtest
          </Button>
        </Link>
      </div>
    </Card>
  )
}

export default function Strategies() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [activeCategory, setActiveCategory] = useState<string>('all')
  const [selectedId, setSelectedId] = useState<string | null>(id ?? null)

  const { data: categories, isLoading } = useQuery({
    queryKey: ['strategy-categories'],
    queryFn: fetchStrategyCategories,
  })

  const allStrategies = useMemo(
    () => categories?.flatMap((c) => c.strategies) ?? [],
    [categories],
  )

  const selected = allStrategies.find((s) => s.id === selectedId) ?? null

  useEffect(() => {
    if (id) setSelectedId(id)
  }, [id])

  const filteredCategories = activeCategory === 'all'
    ? categories ?? []
    : (categories ?? []).filter((c) => c.id === activeCategory)

  const selectStrategy = (strategyId: string) => {
    setSelectedId(strategyId)
    navigate(`/strategies/${strategyId}`, { replace: true })
  }

  if (isLoading) return <Loading message="Loading strategies..." />

  return (
    <div>
      <PageHeader
        title="Strategies"
        description="15 rule-based strategies across Scalping, Intraday, and Swing — plus quick links to macro, charts, breadth, and the full encyclopedia"
      />

      <div className="mb-6">
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Research tools</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {RESEARCH_LINKS.map(({ to, title, description, icon: Icon, color, bg }) => (
            <Link key={to} to={to}>
              <Card hover className="group h-full">
                <div className={`mb-3 inline-flex rounded-xl p-2 ${bg}`}>
                  <Icon size={18} className={color} />
                </div>
                <h3 className="mb-1 text-sm font-semibold text-white group-hover:text-blue-300">{title}</h3>
                <p className="mb-2 text-xs leading-relaxed text-slate-500">{description}</p>
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-400">
                  Open <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" />
                </span>
              </Card>
            </Link>
          ))}
        </div>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        <Chip selected={activeCategory === 'all'} onClick={() => setActiveCategory('all')}>All</Chip>
        {categories?.map((cat) => {
          const Icon = CATEGORY_STYLES[cat.id]?.icon ?? Layers
          return (
            <Chip key={cat.id} selected={activeCategory === cat.id} onClick={() => setActiveCategory(cat.id)}>
              <span className="inline-flex items-center gap-1.5">
                <Icon size={14} />
                {cat.label}
              </span>
            </Chip>
          )
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          {filteredCategories.map((cat) => {
            const style = CATEGORY_STYLES[cat.id] ?? CATEGORY_STYLES.intraday
            const Icon = style.icon
            return (
              <Card key={cat.id}>
                <div className="mb-4 flex items-start gap-3">
                  <div className={`rounded-xl bg-slate-800/60 p-2.5 ${style.accent}`}>
                    <Icon size={22} />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-white">{cat.label}</h3>
                    <p className="mt-1 text-sm text-slate-500">
                      {cat.description} · Timeframes: {cat.timeframes.join(', ')}
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  {cat.strategies.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => selectStrategy(s.id)}
                      className={`flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors ${
                        selectedId === s.id
                          ? 'border-blue-500/50 bg-blue-500/10'
                          : 'border-slate-800/60 bg-slate-800/20 hover:border-slate-700 hover:bg-slate-800/40'
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="font-medium text-white">{s.name}</p>
                        <p className="mt-0.5 truncate text-xs text-slate-500">{s.summary}</p>
                      </div>
                      <ChevronRight size={16} className="shrink-0 text-slate-500" />
                    </button>
                  ))}
                </div>
              </Card>
            )
          })}
        </div>

        <div className="lg:col-span-2">
          {selected ? (
            <StrategyDetail strategy={selected} onClose={() => { setSelectedId(null); navigate('/strategies') }} />
          ) : (
            <Card className="flex min-h-[280px] items-center justify-center text-center">
              <div className="px-4">
                <Layers className="mx-auto mb-3 text-slate-600" size={36} />
                <p className="text-sm text-slate-500">Select a strategy to read entry/exit rules and indicators</p>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
