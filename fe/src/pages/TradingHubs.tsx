import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BarChart2, Clock, Crosshair, TrendingUp } from 'lucide-react'
import {
  apiErrorMessage,
  fetchTradingHubs,
  runTradingHubScan,
  type TradingHub,
  type TradingHubSection,
} from '../api/client'
import { TradingHubResultsPanel } from '../components/trading-hubs/TradingHubPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const HUB_ICONS: Record<string, typeof TrendingUp> = {
  swing: TrendingUp,
  intraday: Clock,
  scalping: Crosshair,
  smart_money: BarChart2,
}

const DEFAULT_TICKERS = 'RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK'

function parseTickers(raw: string) {
  return raw.split(/[,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean)
}

function defaultConfig(section: TradingHubSection | undefined): Record<string, string> {
  if (!section?.config_options) return {}
  const out: Record<string, string> = {}
  for (const [key, opt] of Object.entries(section.config_options)) {
    if (opt.default != null) out[key] = String(opt.default)
  }
  return out
}

export default function TradingHubs() {
  const [hubId, setHubId] = useState('swing')
  const [sectionId, setSectionId] = useState('')
  const [tickers, setTickers] = useState(DEFAULT_TICKERS)
  const [config, setConfig] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  const hubsQ = useQuery({ queryKey: ['trading-hubs'], queryFn: fetchTradingHubs })

  const activeHub = useMemo(
    () => hubsQ.data?.hubs?.find((h) => h.id === hubId) as TradingHub | undefined,
    [hubsQ.data, hubId],
  )

  const activeSection = useMemo(
    () => activeHub?.sections?.find((s) => s.id === sectionId) as TradingHubSection | undefined,
    [activeHub, sectionId],
  )

  useEffect(() => {
    const first = activeHub?.sections?.[0]?.id
    if (first && (!sectionId || !activeHub?.sections?.some((s) => s.id === sectionId))) {
      setSectionId(first)
    }
  }, [activeHub, sectionId])

  useEffect(() => {
    setConfig(defaultConfig(activeSection))
  }, [activeSection?.id])

  const scanMutation = useMutation({
    mutationFn: () => {
      const list = parseTickers(tickers)
      if (!list.length) throw new Error('Enter at least one ticker')
      if (!sectionId) throw new Error('Select a section')
      return runTradingHubScan({
        section_id: sectionId,
        tickers: list,
        config: Object.keys(config).length ? config : undefined,
      })
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => setError(''),
  })

  return (
    <div>
      <PageHeader
        title="Trading Hubs"
        description="Swing Trading · Intraday · Scalping · Smart Money — India (Groww/NSE)"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {(hubsQ.data?.hubs ?? []).map((hub) => {
          const Icon = HUB_ICONS[hub.id] ?? TrendingUp
          return (
            <Chip key={hub.id} selected={hubId === hub.id} onClick={() => { setHubId(hub.id); setError('') }}>
              <span className="inline-flex items-center gap-1.5">
                <Icon size={14} />
                {hub.label}
              </span>
            </Chip>
          )
        })}
      </div>

      {activeHub && (
        <p className="mb-4 text-sm text-slate-400">{activeHub.description}</p>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        {activeHub?.sections?.map((s) => (
          <Chip key={s.id} selected={sectionId === s.id} onClick={() => { setSectionId(s.id); setError('') }}>
            {s.label}
          </Chip>
        ))}
      </div>

      <Card className="mb-4">
        {activeSection && (
          <p className="mb-4 text-sm text-slate-400">{activeSection.description}</p>
        )}

        <FormField label="Tickers (comma-separated)">
          <Textarea rows={2} value={tickers} onChange={(e) => setTickers(e.target.value)} />
        </FormField>

        {activeSection && Object.entries(activeSection.config_options ?? {}).map(([key, opt]) => (
          <div key={key} className="mt-4">
            <FormField label={opt.label}>
              {opt.type === 'select' && opt.choices ? (
                <Select value={config[key] ?? opt.default ?? ''} onChange={(e) => setConfig((c) => ({ ...c, [key]: e.target.value }))}>
                  {opt.choices.map((ch) => (
                    <option key={ch.value} value={ch.value}>{ch.label}</option>
                  ))}
                </Select>
              ) : null}
            </FormField>
          </div>
        ))}

        <div className="mt-4">
          <Button onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending || !sectionId}>
            {scanMutation.isPending ? 'Scanning…' : 'Run live scan'}
          </Button>
        </div>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      {hubsQ.isLoading && <Loading message="Loading trading hubs…" />}
      {scanMutation.isPending && (
        <Loading message="Running live scan — fetching OHLCV from Groww/yfinance (1–3 min)…" />
      )}

      {!scanMutation.isPending && scanMutation.data && (
        <Card>
          <TradingHubResultsPanel data={scanMutation.data as Record<string, unknown>} />
        </Card>
      )}
    </div>
  )
}
