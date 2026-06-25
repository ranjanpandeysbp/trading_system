import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, type UseQueryResult } from '@tanstack/react-query'
import { Activity, RefreshCw } from 'lucide-react'
import {
  apiErrorMessage,
  fetchHeatmap,
  fetchMarketPulseIndices,
  fetchMarketPulseIntelligence,
  fetchMarketPulseSections,
  fetchNiftyBreadth,
  fetchNiftyMonthly,
  fetchNiftyMovers,
  fetchOppositeHedge,
  fetchSectorRotation,
  fetchSectorRotationIntraday,
  fetchTomorrowOutlook,
  fetchWeek52,
  runCommodityScreener,
  runGainersLosers,
  runMtfBias,
  runStockRotation,
} from '../api/client'
import {
  BreadthPanel,
  CommodityPanel,
  HeatmapPanel,
  HedgePanel,
  IntelligencePanel,
  MonthlyPanel,
  MoversTable,
  MtfBiasPanel,
  SectorRotationPanel,
  StockRotationPanel,
  TomorrowOutlookPanel,
  Week52Panel,
} from '../components/market-pulse/MarketPulsePanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d', '1w', '1M']
const SLOW_SECTIONS = new Set(['sector_rotation', 'sector_rotation_intraday', 'opposite_hedge', 'week52', 'commodity_screener'])
const ACTION_SECTIONS = new Set(['gainers_losers', 'stock_rotation', 'commodity_screener', 'mtf_bias'])

type SectionData = Record<string, unknown>

function SectionContent({ section, data }: { section: string; data: SectionData }) {
  switch (section) {
    case 'tomorrow_outlook':
      return <TomorrowOutlookPanel data={data} />
    case 'intelligence':
      return <IntelligencePanel data={data} />
    case 'nifty_breadth':
      return <BreadthPanel data={data} />
    case 'nifty_monthly':
      return <MonthlyPanel data={data} />
    case 'nifty_movers':
      if (data.error) return <Alert type="error">{String(data.error)}</Alert>
      return <MoversTable gainers={data.gainers as SectionData[]} losers={data.losers as SectionData[]} emptyMessage="No gainers/losers — NSE may be unavailable; try during market hours." />
    case 'sector_rotation':
      return <SectorRotationPanel data={data} />
    case 'sector_rotation_intraday':
      return <SectorRotationPanel data={data} intraday />
    case 'opposite_hedge':
      return <HedgePanel data={data} />
    case 'week52':
      return <Week52Panel data={data} />
    case 'heatmap':
      return <HeatmapPanel data={data} />
    case 'gainers_losers':
      if (data.error) return <Alert type="error">{String(data.error)}</Alert>
      return <MoversTable gainers={data.gainers as SectionData[]} losers={data.losers as SectionData[]} />
    case 'stock_rotation':
      return <StockRotationPanel data={data} />
    case 'commodity_screener':
      return <CommodityPanel data={data} />
    case 'mtf_bias':
      return <MtfBiasPanel data={data} />
    default:
      return <p className="text-sm text-slate-500">Select a section to view market data.</p>
  }
}

export default function MarketPulse() {
  const [section, setSection] = useState('tomorrow_outlook')
  const [indexName, setIndexName] = useState('NIFTY 50')
  const [tfKey, setTfKey] = useState('1d')
  const [lookback, setLookback] = useState(5)
  const [breadthOffset, setBreadthOffset] = useState(0)
  const [monthlyOffset, setMonthlyOffset] = useState(0)
  const [tickers, setTickers] = useState('RELIANCE, TCS, INFY, HDFCBANK')
  const [error, setError] = useState('')

  const { data: sections } = useQuery({ queryKey: ['mp-sections'], queryFn: fetchMarketPulseSections })
  const { data: indices } = useQuery({ queryKey: ['mp-indices'], queryFn: fetchMarketPulseIndices })

  const indexOptions = useMemo(() => indices?.indices?.map((i) => i.name) ?? ['NIFTY 50'], [indices])

  const tomorrowQ = useQuery({
    queryKey: ['mp-tomorrow'],
    queryFn: fetchTomorrowOutlook,
    enabled: section === 'tomorrow_outlook',
  })

  const intelligenceQ = useQuery({
    queryKey: ['mp-intelligence'],
    queryFn: fetchMarketPulseIntelligence,
    enabled: section === 'intelligence',
  })

  const breadthQ = useQuery({
    queryKey: ['mp-breadth', breadthOffset],
    queryFn: () => fetchNiftyBreadth(breadthOffset, 10),
    enabled: section === 'nifty_breadth',
  })

  const monthlyQ = useQuery({
    queryKey: ['mp-monthly', monthlyOffset],
    queryFn: () => fetchNiftyMonthly(monthlyOffset, 2),
    enabled: section === 'nifty_monthly',
  })

  const moversQ = useQuery({
    queryKey: ['mp-nifty-movers', indexName],
    queryFn: () => fetchNiftyMovers(indexName),
    enabled: section === 'nifty_movers',
  })

  const sectorQ = useQuery({
    queryKey: ['mp-sector'],
    queryFn: fetchSectorRotation,
    enabled: section === 'sector_rotation',
  })

  const sectorIntraQ = useQuery({
    queryKey: ['mp-sector-intra'],
    queryFn: fetchSectorRotationIntraday,
    enabled: section === 'sector_rotation_intraday',
  })

  const hedgeQ = useQuery({
    queryKey: ['mp-hedge'],
    queryFn: () => fetchOppositeHedge(),
    enabled: section === 'opposite_hedge',
  })

  const week52Q = useQuery({
    queryKey: ['mp-week52', indexName],
    queryFn: () => fetchWeek52(indexName),
    enabled: section === 'week52',
  })

  const heatmapQ = useQuery({
    queryKey: ['mp-heatmap', tfKey],
    queryFn: () => fetchHeatmap(tfKey),
    enabled: section === 'heatmap',
  })

  const actionMutation = useMutation({
    mutationFn: async () => {
      const payload = { index_name: indexName, tf_key: tfKey, lookback_bars: lookback }
      switch (section) {
        case 'gainers_losers':
          return runGainersLosers(payload)
        case 'stock_rotation':
          return runStockRotation(payload)
        case 'commodity_screener':
          return runCommodityScreener(['1 day', '1 week'])
        case 'mtf_bias':
          return runMtfBias(tickers.split(/[,\s]+/).filter(Boolean))
        default:
          return null
      }
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  // Auto-run scan sections when selected (no manual click required)
  useEffect(() => {
    if (!ACTION_SECTIONS.has(section)) return
    setError('')
    actionMutation.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section])

  const activeQuery: UseQueryResult | null = useMemo(() => {
    switch (section) {
      case 'tomorrow_outlook': return tomorrowQ
      case 'intelligence': return intelligenceQ
      case 'nifty_breadth': return breadthQ
      case 'nifty_monthly': return monthlyQ
      case 'nifty_movers': return moversQ
      case 'sector_rotation': return sectorQ
      case 'sector_rotation_intraday': return sectorIntraQ
      case 'opposite_hedge': return hedgeQ
      case 'week52': return week52Q
      case 'heatmap': return heatmapQ
      default: return null
    }
  }, [section, tomorrowQ, intelligenceQ, breadthQ, monthlyQ, moversQ, sectorQ, sectorIntraQ, hedgeQ, week52Q, heatmapQ])

  const activeData = useMemo(() => {
    switch (section) {
      case 'tomorrow_outlook': return tomorrowQ.data
      case 'intelligence': return intelligenceQ.data
      case 'nifty_breadth': return breadthQ.data
      case 'nifty_monthly': return monthlyQ.data
      case 'nifty_movers': return moversQ.data
      case 'sector_rotation': return sectorQ.data
      case 'sector_rotation_intraday': return sectorIntraQ.data
      case 'opposite_hedge': return hedgeQ.data
      case 'week52': return week52Q.data
      case 'heatmap': return heatmapQ.data
      default: return actionMutation.data
    }
  }, [section, tomorrowQ.data, intelligenceQ.data, breadthQ.data, monthlyQ.data, moversQ.data, sectorQ.data, sectorIntraQ.data, hedgeQ.data, week52Q.data, heatmapQ.data, actionMutation.data])

  const isLoading = (
    (activeQuery?.isFetching && activeQuery.isEnabled) ||
    (ACTION_SECTIONS.has(section) && actionMutation.isPending)
  )

  const needsAction = ACTION_SECTIONS.has(section)
  const loadingMessage = SLOW_SECTIONS.has(section)
    ? 'Loading — sector scans can take 1–3 minutes…'
    : 'Loading market data…'
  const queryError = activeQuery?.isError ? apiErrorMessage(activeQuery.error) : ''

  return (
    <div>
      <PageHeader
        title="Market Pulse"
        description="Live NSE intelligence — India markets only (ported from truebacktesting)"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {(sections?.sections ?? []).map((s) => (
          <Chip key={s.id} selected={section === s.id} onClick={() => { setSection(s.id); setError('') }}>
            {s.label}
          </Chip>
        ))}
      </div>

      <Card className="mb-4">
        <div className="grid gap-4 md:grid-cols-3">
          {section !== 'intelligence' && section !== 'tomorrow_outlook' && section !== 'mtf_bias' && (
            <FormField label="Index">
              <Select value={indexName} onChange={(e) => setIndexName(e.target.value)}>
                {indexOptions.map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
            </FormField>
          )}
          {['gainers_losers', 'stock_rotation', 'heatmap'].includes(section) && (
            <FormField label="Timeframe">
              <Select value={tfKey} onChange={(e) => setTfKey(e.target.value)}>
                {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
              </Select>
            </FormField>
          )}
          {['gainers_losers', 'stock_rotation'].includes(section) && (
            <FormField label="Lookback bars">
              <Input type="number" value={lookback} onChange={(e) => setLookback(Number(e.target.value))} />
            </FormField>
          )}
          {section === 'mtf_bias' && (
            <FormField label="Tickers">
              <Input value={tickers} onChange={(e) => setTickers(e.target.value)} />
            </FormField>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {section === 'nifty_breadth' && (
            <>
              <Button variant="secondary" size="sm" onClick={() => setBreadthOffset((o) => Math.max(0, o - 10))}>Prev 10</Button>
              <Button size="sm" onClick={() => setBreadthOffset((o) => o + 10)}>Next 10</Button>
            </>
          )}
          {section === 'nifty_monthly' && (
            <>
              <Button variant="secondary" size="sm" onClick={() => setMonthlyOffset((o) => Math.max(0, o - 2))}>Prev</Button>
              <Button size="sm" onClick={() => setMonthlyOffset((o) => o + 2)}>Next</Button>
            </>
          )}
          {needsAction && (
            <Button onClick={() => { setError(''); actionMutation.mutate() }} disabled={actionMutation.isPending}>
              <Activity size={16} />
              {actionMutation.isPending ? 'Running…' : 'Re-run scan'}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => {
            intelligenceQ.refetch(); tomorrowQ.refetch(); breadthQ.refetch(); monthlyQ.refetch(); moversQ.refetch()
            sectorQ.refetch(); sectorIntraQ.refetch(); hedgeQ.refetch(); week52Q.refetch(); heatmapQ.refetch()
          }}>
            <RefreshCw size={16} />
            Refresh
          </Button>
        </div>
        {(error || queryError) && (
          <div className="mt-3"><Alert type="error">{error || queryError}</Alert></div>
        )}
      </Card>

      {isLoading && <Loading message={loadingMessage} />}

      {!isLoading && !queryError && activeData && (
        <Card>
          <SectionContent section={section} data={activeData as SectionData} />
        </Card>
      )}

      {!isLoading && !queryError && !activeData && needsAction && actionMutation.isError && (
        <Card><Alert type="error">{error || 'Scan failed'}</Alert></Card>
      )}
    </div>
  )
}
