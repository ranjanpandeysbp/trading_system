import { useCallback, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Compass, Radar, RefreshCw, Search, Sun } from 'lucide-react'
import {
  apiErrorMessage,
  fetchCommandCenterSections,
  fetchTomorrowOutlook,
  runBuySellAdvisor,
  runMegaAnalyser,
  runTickerInvestigation,
} from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import {
  AssetClassTickerPicker,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { CommandCenterResults } from '../components/command-center/CommandCenterPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const TABS = [
  { id: 'tomorrow_outlook', label: 'Tomorrow Outlook', icon: Sun },
  { id: 'mega_analyser', label: 'Mega Analyser', icon: Radar },
  { id: 'buy_sell', label: 'Buy or Sell', icon: Compass },
  { id: 'investigation', label: 'Ticker Investigation', icon: Search },
] as const

type TabId = (typeof TABS)[number]['id']
type AssetClass = 'india' | 'us' | 'crypto' | 'commodity'

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: ['1d'] }

export default function CommandCenter() {
  const [tab, setTab] = useState<TabId>('tomorrow_outlook')
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [result, setResult] = useState<unknown>(null)
  const [error, setError] = useState('')

  useQuery({ queryKey: ['cc-sections'], queryFn: fetchCommandCenterSections })

  const tomorrowQuery = useQuery({
    queryKey: ['cc-tomorrow'],
    queryFn: fetchTomorrowOutlook,
    enabled: tab === 'tomorrow_outlook',
  })

  const handlePickerChange = useCallback((v: TickerPickerValue) => {
    setPicker(v)
  }, [])

  const runMutation = useMutation({
    mutationFn: async () => {
      const { tickers, durations } = picker
      if (!tickers.length) throw new Error('Select at least one ticker')

      switch (tab) {
        case 'tomorrow_outlook':
          return fetchTomorrowOutlook()
        case 'mega_analyser':
          return runMegaAnalyser({ tickers, asset_class: assetClass, durations })
        case 'buy_sell':
          return runBuySellAdvisor({ tickers, asset_class: assetClass, durations })
        case 'investigation':
          return runTickerInvestigation({ tickers, asset_class: assetClass })
      }
    },
    onSuccess: (data) => { setResult(data); setError('') },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const displayData = tab === 'tomorrow_outlook' ? tomorrowQuery.data : result
  const loading = tab === 'tomorrow_outlook' ? tomorrowQuery.isLoading : runMutation.isPending
  const queryError = tomorrowQuery.isError ? apiErrorMessage(tomorrowQuery.error) : ''
  const askContext = displayData ? buildAskContext(TABS.find((t) => t.id === tab)?.label ?? tab, displayData) : ''

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
    setPicker(DEFAULT_PICKER)
    setResult(null)
    setError('')
  }

  return (
    <div>
      <PageHeader
        title="Command Center"
        description="Tomorrow's outlook · Mega Analyser · Buy/Sell advisor · Ticker Investigation (India · US · Crypto)"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <Chip key={id} selected={tab === id} onClick={() => { setTab(id); setError(''); setResult(null) }}>
            <span className="inline-flex items-center gap-1.5">
              <Icon size={14} />
              {label}
            </span>
          </Chip>
        ))}
      </div>

      {tab === 'tomorrow_outlook' ? (
        <Card className="mb-6">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => tomorrowQuery.refetch()}
            disabled={tomorrowQuery.isFetching}
          >
            <RefreshCw size={14} />
            {tomorrowQuery.isFetching ? 'Refreshing…' : 'Refresh outlook'}
          </Button>
          {(queryError || error) && (
            <div className="mt-3"><Alert type="error">{queryError || error}</Alert></div>
          )}
        </Card>
      ) : (
        <Card className="mb-6">
          <FormField label="Asset class">
            <Select
              value={assetClass}
              onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}
            >
              <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
              <option value="us">🇺🇸 US stocks (Yahoo)</option>
              <option value="crypto">₿ Crypto (CoinDCX)</option>
              <option value="commodity">🛢️ Commodity futures</option>
            </Select>
          </FormField>

          <AssetClassTickerPicker
            key={assetClass}
            assetClass={assetClass}
            single={tab === 'mega_analyser'}
            showDurations={tab === 'buy_sell' || tab === 'mega_analyser'}
            onChange={handlePickerChange}
          />

          <Button className="mt-4" onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
            {runMutation.isPending ? 'Running…' : 'Run analysis'}
          </Button>
          {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
        </Card>
      )}

      {loading && <Loading message="Running analysis…" />}

      {displayData && !loading && !queryError && (
        <Card>
          <CommandCenterResults tab={tab} data={displayData as Record<string, unknown>} />
        </Card>
      )}

      {askContext && !loading && (
        <AskAIPanel context={askContext} section={`command-center/${tab}`} />
      )}
    </div>
  )
}
