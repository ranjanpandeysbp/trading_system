import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Beaker, Grid3X3, ListFilter, BookOpen, Trophy } from 'lucide-react'
import { fetchStrategyLabPresets, fetchStrategyLabSections } from '../api/client'
import { type AssetClass } from '../components/command-center/AssetClassTickerPicker'
import { LeaderboardPanel } from '../components/strategy-lab/LeaderboardPanel'
import { BuilderTester } from '../components/strategy-lab/BuilderTester'
import { StrategyCatalogLeaderboard } from '../components/backtester/StrategyCatalogLeaderboard'
import { WatchlistMarketProvider, type WatchlistMarket } from '../components/watchlist/WatchlistMarketContext'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Chip } from '../components/ui/Chip'
import { FormField, Select } from '../components/ui/Form'
import { Loading } from '../components/ui/Feedback'

const TABS = [
  { id: 'leaderboard', label: 'Strategy Leaderboard', icon: Trophy },
  { id: 'builder', label: 'Builder & Tester', icon: Beaker },
  { id: 'multi_combo', label: 'Multi-Combo', icon: Grid3X3 },
  { id: 'screener', label: 'Advanced Screener', icon: ListFilter },
  { id: 'presets', label: 'Encyclopedia', icon: BookOpen },
] as const

type TabId = (typeof TABS)[number]['id']

export default function StrategyLab() {
  const [tab, setTab] = useState<TabId>('builder')
  const [assetClass, setAssetClass] = useState<AssetClass>('india')

  useQuery({ queryKey: ['sl-sections'], queryFn: fetchStrategyLabSections })
  const presetsQuery = useQuery({
    queryKey: ['sl-presets', assetClass],
    queryFn: () => fetchStrategyLabPresets(undefined, assetClass),
    enabled: tab === 'presets',
  })

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
  }

  const result = tab === 'presets' ? presetsQuery.data : undefined
  const loading = tab === 'presets' ? presetsQuery.isLoading : false

  const watchlistMarket: WatchlistMarket =
    assetClass === 'us' || assetClass === 'commodity' ? 'us' : assetClass === 'crypto' ? 'crypto' : 'india'

  return (
    <WatchlistMarketProvider market={watchlistMarket}>
    <div>
      <PageHeader
        title="Strategy Lab"
        description="Backtest presets · Multi-combo scanner · Rule screener · Full hub encyclopedia — Command Center · Market Pulse · TA · Trading Hubs · Pro Trade · Options"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <Chip
            key={id}
            selected={tab === id}
            onClick={() => {
              setTab(id)
              if (id === 'leaderboard' && assetClass === 'commodity') setAssetClass('india')
            }}
          >
            <span className="inline-flex items-center gap-1.5">
              <Icon size={14} />
              {label}
            </span>
          </Chip>
        ))}
      </div>

      {tab !== 'presets' && (
        <Card className="mb-4">
          <FormField label="Asset class">
            <Select value={assetClass} onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}>
              <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
              <option value="us">🇺🇸 US stocks (Yahoo)</option>
              <option value="crypto">₿ Crypto (CoinDCX)</option>
              {tab !== 'leaderboard' && <option value="commodity">🛢️ Commodity futures</option>}
            </Select>
          </FormField>
        </Card>
      )}

      {tab === 'leaderboard' && <LeaderboardPanel assetClass={assetClass} />}

      {tab === 'builder' && <BuilderTester key={assetClass} assetClass={assetClass} />}

      {tab === 'multi_combo' && (
        <StrategyCatalogLeaderboard
          key={assetClass}
          assetClass={assetClass}
          tickerMode="multi"
          heading="Compare many tickers across many strategies from the full catalog — walk-forward backtested."
          runLabel="Run multi-combo"
        />
      )}

      {tab === 'screener' && (
        <StrategyCatalogLeaderboard
          key={assetClass}
          assetClass={assetClass}
          tickerMode="multi"
          heading="Screen a universe of tickers against the full strategy catalog to surface the combos worth watching."
          runLabel="Run screener"
        />
      )}

      {loading && <Loading message="Loading encyclopedia…" />}

      {!loading && result && tab === 'presets' && (
        <Card className="mb-4">
          <PresetsPanel data={result as Record<string, unknown>} />
        </Card>
      )}
    </div>
    </WatchlistMarketProvider>
  )
}

function PresetsPanel({ data }: { data: Record<string, unknown> }) {
  const presets = (data.presets as Record<string, { description?: string; recommended_timeframe?: string }>) ?? {}
  const categories = (data.categories as Record<string, string[]>) ?? {}
  const encyclopedia = data.encyclopedia as
    | {
        hubs?: Array<{
          hub: string
          count: number
          sections: Array<{ id: string; title: string; guide?: string | null; extra?: string | null }>
        }>
        section_count?: number
        hub_count?: number
        overview?: string
        workflows?: string
        when_to_use?: string
        strategy_lab_detail?: string
      }
    | undefined

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">
        {encyclopedia?.section_count ?? 0} hub sections across {encyclopedia?.hub_count ?? 0} hubs
        {' · '}
        {Object.keys(presets).length} builder presets for {String(data.market)} ({String(data.asset_class ?? '')})
      </p>

      {encyclopedia?.hubs?.length ? (
        <div className="space-y-4">
          <h4 className="font-medium text-white">All hubs & strategies</h4>
          {encyclopedia.overview && (
            <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium text-slate-200">App overview</summary>
              <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{encyclopedia.overview}</pre>
            </details>
          )}
          {encyclopedia.workflows && (
            <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium text-slate-200">Workflows</summary>
              <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{encyclopedia.workflows}</pre>
            </details>
          )}
          {encyclopedia.when_to_use && (
            <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
              <summary className="cursor-pointer text-sm font-medium text-slate-200">When to use what</summary>
              <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{encyclopedia.when_to_use}</pre>
            </details>
          )}
          {encyclopedia.hubs.map((hub) => (
            <div key={hub.hub}>
              <h5 className="mb-2 text-sm font-semibold text-slate-100">
                {hub.hub}{' '}
                <span className="font-normal text-slate-500">({hub.count})</span>
              </h5>
              <div className="space-y-2">
                {hub.sections.map((section) => (
                  <details
                    key={section.id}
                    className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2"
                  >
                    <summary className="cursor-pointer text-sm font-medium text-slate-200">
                      {section.title}
                    </summary>
                    <p className="mt-1 text-[11px] text-slate-600">{section.id}</p>
                    {section.guide ? (
                      <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
                        {section.guide}
                      </pre>
                    ) : (
                      <p className="mt-2 text-xs text-slate-500">No guide available yet.</p>
                    )}
                    {section.extra && (
                      <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
                        {section.extra}
                      </pre>
                    )}
                  </details>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {encyclopedia?.strategy_lab_detail && (
        <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-slate-200">Strategy Lab & tools detail</summary>
          <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
            {encyclopedia.strategy_lab_detail}
          </pre>
        </details>
      )}

      {Object.entries(categories).map(([cat, names]) => (
        <div key={cat}>
          <h4 className="mb-2 font-medium capitalize text-white">
            Builder presets — {cat.replace(/_/g, ' ')}
          </h4>
          <ul className="space-y-2">
            {names.map((name) => (
              <li key={name} className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2 text-sm">
                <span className="font-medium text-slate-200">{name}</span>
                {presets[name]?.description && (
                  <p className="mt-1 text-slate-500">{presets[name].description}</p>
                )}
                {presets[name]?.recommended_timeframe && (
                  <p className="text-xs text-slate-600">TF: {presets[name].recommended_timeframe}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
