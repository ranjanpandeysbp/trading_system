import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Chip } from '../components/ui/Chip'
import { Select } from '../components/ui/Form'
import { PageHeader } from '../components/ui/PageHeader'
import { StrategyCatalogLeaderboard } from '../components/backtester/StrategyCatalogLeaderboard'
import { WatchlistMarketProvider, type WatchlistMarket } from '../components/watchlist/WatchlistMarketContext'

type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

export default function Backtester() {
  const [searchParams] = useSearchParams()
  const [mode, setMode] = useState<'single' | 'leaderboard'>('single')
  const [assetClass, setAssetClass] = useState<AssetClass>('india')

  const strategyFromUrl = searchParams.get('strategy')

  const watchlistMarket: WatchlistMarket =
    assetClass === 'us' || assetClass === 'commodity' ? 'us' : assetClass === 'crypto' ? 'crypto' : 'india'

  return (
    <WatchlistMarketProvider market={watchlistMarket}>
    <div>
      <PageHeader
        title="Backtester"
        description="Backtest built-in rules, Trading Hubs, TA screeners, and Strategy Lab presets on historical data — India · US · Crypto · Commodities"
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          <Chip selected={mode === 'single'} onClick={() => setMode('single')}>Single Backtest</Chip>
          <Chip selected={mode === 'leaderboard'} onClick={() => setMode('leaderboard')}>Leaderboard (multi-ticker)</Chip>
        </div>
        <Select
          value={assetClass}
          onChange={(e) => setAssetClass(e.target.value as AssetClass)}
          className="w-auto"
        >
          <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
          <option value="us">🇺🇸 US stocks (Yahoo)</option>
          <option value="crypto">₿ Crypto (CoinDCX)</option>
          <option value="commodity">🛢️ Commodity futures</option>
        </Select>
      </div>

      {mode === 'leaderboard' ? (
        <StrategyCatalogLeaderboard
          key={`multi-${assetClass}`}
          assetClass={assetClass}
          tickerMode="multi"
          runLabel="Run leaderboard"
        />
      ) : (
        <StrategyCatalogLeaderboard
          key={`single-${assetClass}`}
          assetClass={assetClass}
          tickerMode="single"
          heading="Test one ticker against any number of strategies from the full catalog — walk-forward backtested, with History bars and Forward bars control."
          runLabel="Run backtest"
          initialStrategyIds={strategyFromUrl ? [strategyFromUrl] : undefined}
        />
      )}
    </div>
    </WatchlistMarketProvider>
  )
}
