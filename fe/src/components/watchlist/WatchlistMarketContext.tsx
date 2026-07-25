import { createContext, useContext, type ReactNode } from 'react'

export type WatchlistMarket = 'india' | 'us' | 'crypto'

const WatchlistMarketContext = createContext<WatchlistMarket>('india')

export function WatchlistMarketProvider({
  market,
  children,
}: {
  market: WatchlistMarket
  children: ReactNode
}) {
  return (
    <WatchlistMarketContext.Provider value={market}>
      {children}
    </WatchlistMarketContext.Provider>
  )
}

export function useWatchlistMarket() {
  return useContext(WatchlistMarketContext)
}

export { WatchlistMarketContext }
