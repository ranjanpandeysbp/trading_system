import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Search, LineChart, Wallet, Settings, TrendingUp, Menu, X, BookOpen, LogOut, User, Activity, BarChart3, Layers, Landmark, Compass, Beaker, CalendarRange, Bell, Eye, ArrowUp, Calculator, Target, ChevronDown, Clapperboard, Bot, Crosshair, Radar, ListTodo, Trophy, MessageSquare, Sparkles, GitBranch, Medal, Building2, Flame } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { IndexMarquee } from './IndexMarquee'

type NavChild = { to: string; label: string }
type NavEntry = { to: string; label: string; shortLabel: string; icon: typeof LayoutDashboard; children?: NavChild[] }

const nav: NavEntry[] = [
  { to: '/trading-agent', label: 'Trading Agent (TA)', shortLabel: 'TA', icon: MessageSquare },
  { to: '/investing-agent', label: 'Investing Agent (FA)', shortLabel: 'FA', icon: Bot },
  {
    to: '/workflow',
    label: 'Workflow',
    shortLabel: 'Flow',
    icon: GitBranch,
    children: [
      { to: '/workflow/india', label: 'India (F&O / Intraday)' },
      { to: '/workflow/us', label: 'US (Swing / Pairs)' },
      { to: '/workflow/crypto', label: 'Crypto (Scalp / Intraday)' },
      { to: '/workflow/commodities', label: 'Commodities (Gold / Oil)' },
    ],
  },
  {
    to: '/best-strategies',
    label: 'Best Strategies',
    shortLabel: 'Best',
    icon: Medal,
    children: [
      { to: '/best-strategies/india', label: 'India (Equities & F&O)' },
      { to: '/best-strategies/us', label: 'US Equities' },
      { to: '/best-strategies/crypto', label: 'Crypto' },
      { to: '/best-strategies/commodities', label: 'Commodities' },
    ],
  },
  {
    to: '/institutional-accuracy',
    label: 'Institutional Accuracy',
    shortLabel: 'Inst',
    icon: Building2,
    children: [
      { to: '/institutional-accuracy/india', label: 'India' },
      { to: '/institutional-accuracy/us', label: 'US' },
      { to: '/institutional-accuracy/crypto', label: 'Crypto' },
      { to: '/institutional-accuracy/commodities', label: 'Commodities' },
    ],
  },
  { to: '/dashboard', label: 'Dashboard', shortLabel: 'Home', icon: LayoutDashboard },
  { to: '/auto-trade', label: 'Auto Trade', shortLabel: 'Auto', icon: Radar },
  {
    to: '/command-center',
    label: 'Command Center',
    shortLabel: 'Command',
    icon: Compass,
    children: [
      { to: '/command-center', label: 'Tools & scanners' },
      { to: '/command-center?tab=all_strategies', label: 'All Strategies Explained' },
      { to: '/command-center?tab=playbook', label: 'Trading Playbook' },
      { to: '/command-center?tab=mega_analyser', label: 'Mega Analyser' },
      { to: '/command-center?tab=buy_sell', label: 'Buy or Sell' },
      { to: '/command-center?tab=advance_decline_graph', label: 'Advance Decline' },
      { to: '/command-center?tab=comparative_strength', label: 'Comparative Strength' },
      { to: '/command-center?tab=oil_dollar_bond', label: 'Oil · Dollar · Bond' },
      { to: '/command-center?tab=option_chain', label: 'Option Chain' },
      { to: '/strategy-lab', label: 'Strategy Lab Encyclopedia' },
    ],
  },
  { to: '/strategies', label: 'Strategies', shortLabel: 'Rules', icon: BookOpen },
  { to: '/market-pulse', label: 'Market Pulse', shortLabel: 'Pulse', icon: Activity },
  { to: '/etf-ta-in', label: 'ETF TA IN', shortLabel: 'ETF', icon: Landmark },
  { to: '/etf-28-sma', label: 'ETF 28 SMA', shortLabel: '28 SMA', icon: TrendingUp },
  { to: '/etf-top-down', label: 'ETF Top Down', shortLabel: 'Top Down', icon: ArrowUp },
  { to: '/trading-hubs', label: 'Trading Hubs', shortLabel: 'Hubs', icon: Layers },
  {
    to: '/trade-candidate',
    label: 'Trade Candidate',
    shortLabel: 'Candidate',
    icon: Target,
    children: [
      { to: '/trade-candidate/configure', label: 'Configure' },
      { to: '/trade-candidate/signals-crypto', label: 'Live Signals · Crypto' },
      { to: '/trade-candidate/signals-india', label: 'Live Signals · India' },
      { to: '/trade-candidate/signals-us', label: 'Live Signals · US' },
      { to: '/trade-candidate/signals-commodity', label: 'Live Signals · Commodities' },
      { to: '/trade-candidate/setups', label: 'Saved Setups' },
      { to: '/trade-candidate/history-crypto', label: 'Trigger History · Crypto' },
      { to: '/trade-candidate/history-india', label: 'Trigger History · India' },
      { to: '/trade-candidate/history-us', label: 'Trigger History · US' },
      { to: '/trade-candidate/history-commodity', label: 'Trigger History · Commodities' },
    ],
  },
  { to: '/options', label: 'Options', shortLabel: 'Options', icon: Calculator },
  {
    to: '/pro-trade',
    label: 'Pro Trade',
    shortLabel: 'Pro',
    icon: Crosshair,
    children: [
      { to: '/pro-trade/volume-profile-ce', label: 'Volume Profile CE' },
      { to: '/pro-trade/volume-profile-poc', label: 'Volume Profile POC' },
      { to: '/pro-trade/pa-volume-profile', label: 'PA - Volume Profile' },
      { to: '/pro-trade/pa-vp-smc', label: 'PA-VP-SMC' },
      { to: '/pro-trade/volume-spread-next-candle', label: 'Volume Spread - Next Candle' },
      { to: '/pro-trade/elliott-wave', label: 'Elliott Wave' },
      { to: '/pro-trade/fibonacci-pro', label: 'Fibonacci Pro' },
      { to: '/pro-trade/bb-mean-reversion', label: 'BB Mean Reversion' },
      { to: '/pro-trade/traffic-light-indicator', label: 'Traffic Light Indicator' },
      { to: '/pro-trade/buy-low-sell-high', label: 'Buy Low Sell High' },
      { to: '/pro-trade/rlb-breakout', label: 'RLB - Breakout' },
      { to: '/pro-trade/3-in-1-trade-system', label: '3-in-1 Trade System' },
      { to: '/pro-trade/simple-effective', label: 'Simple Effective' },
      { to: '/trading-hubs?hub=swing&section=support_resistance', label: 'Support & Resistance' },
      { to: '/pro-trade/btst', label: 'Buy Today Sell Tomorrow' },
      { to: '/pro-trade/ticker-chart', label: 'Ticker Chart' },
    ],
  },
  {
    to: '/prediction',
    label: 'Prediction',
    shortLabel: 'Predict',
    icon: Sparkles,
    children: [
      { to: '/prediction/pattern-analogue', label: 'Pattern Analogue' },
      { to: '/prediction/astro-finance', label: 'Astro Finance' },
      { to: '/options?section=market_prediction', label: 'Market Prediction' },
      { to: '/options?section=call_put_writing', label: 'Call Put Writing' },
    ],
  },
  { to: '/technical-analysis', label: 'Technical Analysis', shortLabel: 'TA', icon: BarChart3 },
  { to: '/strategy-lab', label: 'Strategy Lab', shortLabel: 'Lab', icon: Beaker },
  { to: '/seasonality', label: 'Seasonality', shortLabel: 'Season', icon: CalendarRange },
  { to: '/youtube-analysis', label: 'Youtube Analysis', shortLabel: 'YT', icon: Clapperboard },
  { to: '/alerts', label: 'Alerts', shortLabel: 'Alerts', icon: Bell },
  { to: '/watchlist', label: 'Watchlist', shortLabel: 'Watch', icon: Eye },
  { to: '/todos', label: 'Todos', shortLabel: 'Todos', icon: ListTodo },
  { to: '/best-mf', label: 'Best MF', shortLabel: 'Best MF', icon: Trophy },
  { to: '/mf-fire', label: 'MF FIRE', shortLabel: 'FIRE', icon: Flame },
  { to: '/scanner', label: 'Scanner', shortLabel: 'Scan', icon: Search },
  { to: '/backtester', label: 'Backtester', shortLabel: 'Test', icon: LineChart },
  { to: '/paper', label: 'Paper Trading', shortLabel: 'Paper', icon: Wallet },
  { to: '/settings', label: 'Manage', shortLabel: 'Settings', icon: Settings },
]

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation()

  const childMatches = (childTo: string) => {
    const pathOnly = childTo.split('?')[0]
    if (location.pathname === pathOnly) {
      if (!childTo.includes('?')) {
        // Plain path child (e.g. Command Center → Tools): active only when no tab query,
        // or when tab is not claimed by a sibling deep-link.
        const tab = new URLSearchParams(location.search).get('tab')
        if (pathOnly === '/command-center' && tab && tab !== 'nse_world_indices') return false
        return true
      }
      // Query-string children (e.g. Trading Hubs deep-links): match pathname + required params.
      const want = new URLSearchParams(childTo.split('?')[1] || '')
      const have = new URLSearchParams(location.search)
      for (const [k, v] of want.entries()) {
        if (have.get(k) !== v) return false
      }
      return true
    }
    return location.pathname.startsWith(`${pathOnly}/`)
  }

  const groupMatches = (entry: NavEntry) => {
    if (entry.children?.some((c) => childMatches(c.to))) return true
    // Keep Pro Trade expanded for any /pro-trade/* route (including new sections).
    if (entry.to === '/pro-trade' && location.pathname.startsWith('/pro-trade')) return true
    if (entry.to === '/prediction' && location.pathname.startsWith('/prediction')) return true
    if (entry.to === '/workflow' && location.pathname.startsWith('/workflow')) return true
    if (entry.to === '/best-strategies' && location.pathname.startsWith('/best-strategies')) return true
    if (entry.to === '/institutional-accuracy' && location.pathname.startsWith('/institutional-accuracy')) return true
    if (entry.to === '/command-center' && location.pathname.startsWith('/command-center')) return true
    // Prediction also deep-links Options → Market Prediction / Call Put Writing.
    if (
      entry.to === '/prediction'
      && location.pathname === '/options'
      && ['market_prediction', 'call_put_writing'].includes(
        new URLSearchParams(location.search).get('section') ?? '',
      )
    ) {
      return true
    }
    return false
  }

  const [openGroup, setOpenGroup] = useState<string | null>(
    () => nav.find((n) => n.children && groupMatches(n))?.to ?? null,
  )

  useEffect(() => {
    const match = nav.find((n) => n.children && groupMatches(n))
    if (match) setOpenGroup(match.to)
  }, [location.pathname, location.search])

  return (
    <>
      {nav.map(({ to, label, icon: Icon, children }) => {
        const entry = { to, label, shortLabel: '', icon: Icon, children }
        const groupActive = Boolean(children && groupMatches(entry))
        const expanded = openGroup === to

        if (children) {
          return (
            <div key={to}>
              <button
                type="button"
                onClick={() => setOpenGroup((prev) => (prev === to ? null : to))}
                className={`flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-left text-sm font-medium transition-all ${
                  groupActive
                    ? 'bg-blue-500/15 text-blue-400 shadow-sm shadow-blue-500/10'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`}
              >
                <Icon size={18} strokeWidth={2} className="shrink-0" />
                <span className="flex-1">{label}</span>
                <ChevronDown size={15} className={`shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`} />
              </button>
              {expanded && (
                <div className="ml-4 mt-1 flex flex-col gap-0.5 border-l border-slate-800/80 pl-4">
                  {children.map((c) => (
                    <NavLink
                      key={c.to}
                      to={c.to}
                      onClick={onNavigate}
                      className={() =>
                        `rounded-lg px-3 py-2 text-sm transition-all ${
                          childMatches(c.to)
                            ? 'bg-blue-500/15 text-blue-400'
                            : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                        }`
                      }
                    >
                      {c.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        }

        return (
          <NavLink
            key={to}
            to={to}
            end={to === '/trading-agent' || to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all ${
                isActive
                  ? 'bg-blue-500/15 text-blue-400 shadow-sm shadow-blue-500/10'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
              }`
            }
          >
            <Icon size={18} strokeWidth={2} className="shrink-0" />
            <span>{label}</span>
          </NavLink>
        )
      })}
    </>
  )
}

export function AppLayout({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [showScrollTop, setShowScrollTop] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [menuOpen])

  // The layout grows with content (min-h-screen, not h-screen), so the
  // window/document scrolls rather than <main> internally — track that.
  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 400)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    window.scrollTo({ top: 0 })
    setShowScrollTop(false)
  }, [location.pathname])

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* Mobile overlay */}
      {menuOpen && (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setMenuOpen(false)}
        />
      )}

      {/* Sidebar — drawer on mobile, fixed on desktop */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[min(100vw-3rem,18rem)] flex-col border-r border-slate-800/80 bg-slate-900/95 p-5 backdrop-blur-xl transition-transform duration-300 ease-out lg:static lg:z-auto lg:w-64 lg:translate-x-0 lg:bg-slate-900/40 lg:backdrop-blur-xl xl:w-72 ${
          menuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="mb-6 flex items-center justify-between gap-3 lg:mb-8">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-emerald-500 text-base font-bold text-white shadow-lg shadow-blue-500/30 sm:h-11 sm:w-11 sm:text-lg">
              ₹
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-base font-bold text-white">QueryMe</h1>
              <p className="text-xs text-slate-500">Trading &amp; Investing Buddy</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close navigation"
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white lg:hidden"
            onClick={() => setMenuOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
          <NavItems onNavigate={() => setMenuOpen(false)} />
        </nav>

        <div className="mt-4 space-y-3">
          {user && (
            <div className="rounded-xl border border-slate-800/60 bg-slate-800/30 p-3">
              <div className="flex items-center gap-2 text-sm text-white">
                <User size={16} className="shrink-0 text-slate-400" />
                <div className="min-w-0">
                  <p className="truncate font-medium">{user.name}</p>
                  <p className="truncate text-xs text-slate-500">{user.email}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700/60 px-3 py-2 text-sm text-slate-300 transition-colors hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-300"
              >
                <LogOut size={16} />
                Logout
              </button>
            </div>
          )}

          <footer className="hidden rounded-xl border border-slate-800/60 bg-slate-800/30 p-3 sm:block">
          <div className="mb-1 flex items-center gap-1.5 text-xs text-slate-500">
            <TrendingUp size={12} />
            <span>Paper trading only</span>
          </div>
          <p className="text-[10px] leading-relaxed text-slate-600">
            Educational demo — not investment advice
          </p>
        </footer>
        </div>
      </aside>

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-xl">
          {/* Mobile top bar */}
          <header className="flex items-center justify-between gap-3 px-4 py-3 lg:hidden">
            <button
              type="button"
              aria-label="Open navigation"
              className="rounded-lg p-2 text-slate-300 hover:bg-slate-800"
              onClick={() => setMenuOpen(true)}
            >
              <Menu size={22} />
            </button>
            <div className="flex min-w-0 flex-1 items-center justify-center gap-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-emerald-500 text-sm font-bold text-white">
                ₹
              </div>
              <span className="truncate font-semibold text-white">
                {nav.find((n) => location.pathname === n.to || location.pathname.startsWith(`${n.to}/`))?.label ?? 'QueryMe'}
              </span>
            </div>
            <div className="w-10" aria-hidden />
          </header>

          <IndexMarquee />
        </div>

        <main className="flex-1 overflow-x-hidden p-4 pb-safe sm:p-6 lg:p-8 lg:pb-8">
          <div className="mx-auto w-full max-w-7xl">{children}</div>
        </main>

        {/* Mobile scroll-to-top */}
        {showScrollTop && (
          <button
            type="button"
            aria-label="Scroll to top"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="fixed bottom-[max(1rem,env(safe-area-inset-bottom))] right-4 z-30 flex h-11 w-11 items-center justify-center rounded-full border border-slate-700/60 bg-slate-800/90 text-slate-200 shadow-lg shadow-black/30 backdrop-blur-xl transition-colors hover:bg-slate-700 lg:hidden"
          >
            <ArrowUp size={20} />
          </button>
        )}
      </div>
    </div>
  )
}
