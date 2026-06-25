import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { LineChart, Search, Radar } from 'lucide-react'
import {
  apiErrorMessage,
  runMtfScanner,
  runSentimentScreener,
  runTickerInvestigation,
} from '../api/client'
import {
  MtfScannerPanel,
  SentimentScreenerPanel,
  TickerInvestigationPanel,
} from '../components/technical-analysis/TechnicalAnalysisPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const TABS = [
  { id: 'investigation', label: 'Ticker Investigation', icon: Search },
  { id: 'sentiment', label: 'Trend & Sentiment Screener', icon: Radar },
  { id: 'mtf', label: 'MTF Scanner', icon: LineChart },
] as const

const SENTIMENT_TFS = ['5m', '15m', '1h', '4h', '1d']
const MTF_TFS = ['5m', '15m', '1h', '4h', '1d']

type TabId = (typeof TABS)[number]['id']

function parseTickers(raw: string) {
  return raw.split(/[,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean)
}

export default function TechnicalAnalysis() {
  const [tab, setTab] = useState<TabId>('investigation')
  const [tickers, setTickers] = useState('RELIANCE, TCS, INFY, HDFCBANK')
  const [sentimentTfs, setSentimentTfs] = useState<string[]>(['1d', '4h'])
  const [mtfTfs, setMtfTfs] = useState<string[]>(['15m', '1h', '4h', '1d'])
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: async () => {
      const list = parseTickers(tickers)
      if (!list.length) throw new Error('Enter at least one ticker')
      switch (tab) {
        case 'investigation':
          return runTickerInvestigation(list)
        case 'sentiment':
          return runSentimentScreener({ tickers: list, timeframes: sentimentTfs })
        case 'mtf':
          return runMtfScanner({ tickers: list, timeframes: mtfTfs })
      }
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => setError(''),
  })

  const toggleTf = (tf: string, selected: string[], setter: (v: string[]) => void) => {
    setter(selected.includes(tf) ? selected.filter((t) => t !== tf) : [...selected, tf])
  }

  return (
    <div>
      <PageHeader
        title="Technical Analysis"
        description="Ticker Investigation · Trend & Sentiment Screener · MTF Scanner (Groww · India)"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <Chip key={id} selected={tab === id} onClick={() => { setTab(id); setError('') }}>
            <span className="inline-flex items-center gap-1.5">
              <Icon size={14} />
              {label}
            </span>
          </Chip>
        ))}
      </div>

      <Card className="mb-4">
        <FormField label="Tickers (comma-separated)">
          <Textarea rows={2} value={tickers} onChange={(e) => setTickers(e.target.value)} />
        </FormField>

        {tab === 'sentiment' && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Timeframes</p>
            <div className="flex flex-wrap gap-2">
              {SENTIMENT_TFS.map((tf) => (
                <Chip key={tf} selected={sentimentTfs.includes(tf)} onClick={() => toggleTf(tf, sentimentTfs, setSentimentTfs)}>
                  {tf}
                </Chip>
              ))}
            </div>
          </div>
        )}

        {tab === 'mtf' && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">MTF timeframes</p>
            <div className="flex flex-wrap gap-2">
              {MTF_TFS.map((tf) => (
                <Chip key={tf} selected={mtfTfs.includes(tf)} onClick={() => toggleTf(tf, mtfTfs, setMtfTfs)}>
                  {tf}
                </Chip>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4">
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? 'Scanning…' : tab === 'investigation' ? 'Investigate' : 'Run scan'}
          </Button>
        </div>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      {mutation.isPending && (
        <Loading message="Analysis can take 1–3 minutes per ticker — fetching Groww/yfinance data…" />
      )}

      {!mutation.isPending && mutation.data && (
        <Card>
          {tab === 'investigation' && <TickerInvestigationPanel data={mutation.data as Record<string, unknown>} />}
          {tab === 'sentiment' && <SentimentScreenerPanel data={mutation.data as Record<string, unknown>} />}
          {tab === 'mtf' && <MtfScannerPanel data={mutation.data as Record<string, unknown>} />}
        </Card>
      )}
    </div>
  )
}
