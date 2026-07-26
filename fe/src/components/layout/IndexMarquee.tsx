import { useQuery } from '@tanstack/react-query'
import { fetchMarketMarquee } from '../../api/client'

type Quote = {
  id: string
  label: string
  symbol: string
  market: string
  price: number | null
  change_pct: number | null
  is_live: boolean
}

function formatPrice(n: number | null | undefined, market: string) {
  if (n == null || Number.isNaN(n)) return '—'
  if (market === 'crypto' && n >= 1000) {
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  }
  if (n >= 1000) {
    return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })
}

function QuoteChip({ q }: { q: Quote }) {
  const ch = q.change_pct
  const up = ch != null && ch > 0
  const down = ch != null && ch < 0
  const chColor = up ? 'text-emerald-400' : down ? 'text-rose-400' : 'text-slate-500'
  return (
    <span className="mx-4 inline-flex shrink-0 items-baseline gap-2 whitespace-nowrap text-sm">
      <span className="font-medium text-slate-300">{q.label}</span>
      <span className="font-semibold tabular-nums text-white">{formatPrice(q.price, q.market)}</span>
      {ch != null && (
        <span className={`tabular-nums text-xs ${chColor}`}>
          {up ? '+' : ''}
          {ch.toFixed(2)}%
        </span>
      )}
    </span>
  )
}

export function IndexMarquee() {
  const q = useQuery({
    queryKey: ['market-marquee'],
    queryFn: fetchMarketMarquee,
    refetchInterval: 20_000,
    staleTime: 15_000,
  })

  const quotes = ((q.data as { quotes?: Quote[] } | undefined)?.quotes) ?? []

  return (
    <div className="relative overflow-hidden bg-slate-950/40">
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-8 bg-gradient-to-r from-slate-950 to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-gradient-to-l from-slate-950 to-transparent" />
      <div className="flex items-center gap-2 px-2 py-1.5 lg:px-4">
        <span className="shrink-0 rounded bg-slate-800/80 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          Live
        </span>
        {q.isLoading && !quotes.length ? (
          <span className="text-xs text-slate-500">Loading indices…</span>
        ) : quotes.length === 0 ? (
          <span className="text-xs text-slate-500">Index quotes unavailable</span>
        ) : (
          <div className="min-w-0 flex-1 overflow-hidden">
            <div className="index-marquee-track flex w-max">
              {[0, 1].map((copy) => (
                <div key={copy} className="flex items-center" aria-hidden={copy === 1}>
                  {quotes.map((item) => (
                    <QuoteChip key={`${copy}-${item.id}`} q={item} />
                  ))}
                  <span className="mx-2 text-slate-700">·</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <style>{`
        @keyframes index-marquee-scroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .index-marquee-track {
          animation: index-marquee-scroll 48s linear infinite;
        }
        .index-marquee-track:hover {
          animation-play-state: paused;
        }
        @media (prefers-reduced-motion: reduce) {
          .index-marquee-track { animation: none; }
        }
      `}</style>
    </div>
  )
}
