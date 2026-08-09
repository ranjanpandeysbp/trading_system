import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { LineChart, Search, Radar } from 'lucide-react'
import {
  apiErrorMessage,
  fetchTaScreeners,
  runMtfScanner,
  runSentimentScreener,
  runTaScreener,
  runTickerInvestigation,
} from '../api/client'
import { AskAIPanel, buildAskContext } from '../components/ai/AskAIPanel'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import {
  MtfScannerPanel,
  SentimentScreenerPanel,
  TickerInvestigationPanel,
} from '../components/technical-analysis/TechnicalAnalysisPanels'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../components/analysis/AnalysisBackground'
import { TaScreenerResultsPanel } from '../components/technical-analysis/TaScreenerResultsPanel'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { StrategyDataSourceBar } from '../components/ui/StrategyDataSourceBar'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Select, Textarea } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const CORE_ICONS: Record<string, typeof Search> = {
  ticker_investigation: Search,
  sentiment_screener: Radar,
  mtf_scanner: LineChart,
}

const SENTIMENT_TFS = ['5m', '15m', '1h', '4h', '1d']
const MTF_TFS = ['5m', '15m', '1h', '4h', '1d']
const ENGINE_TFS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
const WSSR_TFS = ['5m', '15m', '30m', '1h', '4h', '1d']

type ScreenerMeta = {
  id: string
  label: string
  markets?: string[]
  api?: string
  engine?: string
  default_tf?: string
}

function parseTickers(raw: string) {
  return raw.split(/[,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean)
}

function isEngineScreener(s: ScreenerMeta) {
  return Boolean(s.engine)
}

export default function TechnicalAnalysis() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = searchParams.get('tab')
  const [tab, setTab] = useState(tabFromUrl || 'ticker_investigation')
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [tickers, setTickers] = useState('RELIANCE, TCS, INFY, HDFCBANK')
  const [sentimentTfs, setSentimentTfs] = useState<string[]>(['1d', '4h'])
  const [mtfTfs, setMtfTfs] = useState<string[]>(['15m', '1h', '4h', '1d'])
  const [wssrTfs, setWssrTfs] = useState<string[]>(['15m', '1h', '1d'])
  const [engineTf, setEngineTf] = useState('')
  const [error, setError] = useState('')
  const bg = useAnalysisBackground('technical_analysis', tab)

  const { data: catalog } = useQuery({ queryKey: ['ta-screeners'], queryFn: fetchTaScreeners })

  const screeners = useMemo(() => {
    const list = (catalog as { screeners?: ScreenerMeta[] })?.screeners ?? []
    return list
  }, [catalog])

  useEffect(() => {
    const next = searchParams.get('tab')
    if (next && next !== tab && screeners.some((s) => s.id === next)) {
      setTab(next)
      const meta = screeners.find((s) => s.id === next)
      if (meta?.default_tf) setEngineTf(meta.default_tf)
    }
  }, [searchParams, screeners, tab])

  const active = screeners.find((s) => s.id === tab)
  const isEngine = active ? isEngineScreener(active) : false

  const handlePickerChange = useCallback((v: TickerPickerValue) => {
    setPicker(v)
  }, [])

  const mutation = useMutation({
    mutationFn: async () => {
      const list = tab === 'ticker_investigation' ? picker.tickers : parseTickers(tickers)
      if (!list.length && tab !== 'big_whale') throw new Error('Enter at least one ticker')

      switch (tab) {
        case 'ticker_investigation':
          return runTickerInvestigation({ tickers: list, asset_class: assetClass })
        case 'sentiment_screener':
          return runSentimentScreener({ tickers: list, timeframes: sentimentTfs })
        case 'mtf_scanner':
          return runMtfScanner({ tickers: list, timeframes: mtfTfs })
        default:
          return runTaScreener({
            screener_id: tab,
            tickers: tab === 'big_whale' ? ['BTC'] : list,
            timeframe:
              tab === 'weak_strong_sr'
                ? wssrTfs[0] || active?.default_tf || undefined
                : engineTf || active?.default_tf || undefined,
            asset_class: assetClass,
            ...(tab === 'weak_strong_sr'
              ? { options: { timeframes: wssrTfs.length ? wssrTfs : ['15m'] } }
              : {}),
          })
      }
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => { setError(''); bg.setViewedReportId(null) },
  })

  const buildPayload = () => {
    const list = tab === 'ticker_investigation' ? picker.tickers : parseTickers(tickers)
    const base: Record<string, unknown> = {
      tickers: tab === 'big_whale' ? ['BTC'] : list,
      asset_class: assetClass,
    }
    switch (tab) {
      case 'sentiment_screener':
        return { ...base, timeframes: sentimentTfs }
      case 'mtf_scanner':
        return { ...base, timeframes: mtfTfs }
      case 'weak_strong_sr':
        return {
          ...base,
          timeframe: wssrTfs[0] || active?.default_tf || undefined,
          options: { timeframes: wssrTfs.length ? wssrTfs : ['15m'] },
        }
      default:
        return {
          ...base,
          screener_id: tab,
          timeframe: engineTf || active?.default_tf || undefined,
        }
    }
  }

  const validateRun = () => {
    const list = tab === 'ticker_investigation' ? picker.tickers : parseTickers(tickers)
    if (!list.length && tab !== 'big_whale') return 'Enter at least one ticker'
    return null
  }

  const displayData = bg.viewedPayload ?? mutation.data

  const toggleTf = (tf: string, selected: string[], setter: (v: string[]) => void) => {
    setter(selected.includes(tf) ? selected.filter((t) => t !== tf) : [...selected, tf])
  }

  const selectTab = (id: string) => {
    setTab(id)
    setError('')
    const meta = screeners.find((s) => s.id === id)
    if (meta?.default_tf) setEngineTf(meta.default_tf)
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev)
      p.set('tab', id)
      return p
    }, { replace: true })
  }

  const coreScreeners = screeners.filter((s) => !isEngineScreener(s))
  const engineScreeners = screeners.filter((s) => isEngineScreener(s))

  return (
    <div>
      <PageHeader
        title="Technical Analysis"
        description="TA screeners — Ticker Investigation · Sentiment · MTF · Price Action · S/R · Fakeout · SMC · Crypto engines"
      />

      <p className="mb-3 text-sm text-slate-500">
        {(catalog as { count?: number })?.count ?? screeners.length} TA screeners · no ticker count limit
      </p>

      <div className="mb-2">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-600">Core</p>
        <div className="flex flex-wrap gap-2">
          {coreScreeners.map((s) => {
            const Icon = CORE_ICONS[s.id] ?? Search
            return (
              <Chip key={s.id} selected={tab === s.id} onClick={() => selectTab(s.id)}>
                <span className="inline-flex items-center gap-1.5">
                  <Icon size={14} />
                  {s.label}
                </span>
              </Chip>
            )
          })}
        </div>
      </div>

      <div className="mb-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-600">Engine screeners</p>
        <div className="flex flex-wrap gap-2">
          {engineScreeners.map((s) => (
            <Chip key={s.id} selected={tab === s.id} onClick={() => selectTab(s.id)}>
              {s.label}
            </Chip>
          ))}
        </div>
      </div>

      <Card className="mb-4">
        <FormField label="Asset class">
          <Select
            value={assetClass}
            onChange={(e) => {
              setAssetClass(e.target.value as AssetClass)
              setPicker({ tickers: [], durations: [] })
            }}
          >
            <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
            <option value="us">🇺🇸 US stocks (Yahoo)</option>
            <option value="crypto">₿ Crypto (CoinDCX)</option>
            <option value="commodity">🛢️ Commodity futures</option>
          </Select>
        </FormField>

        {tab === 'ticker_investigation' && (
          <AssetClassTickerPicker
            key={assetClass}
            assetClass={assetClass}
            onChange={handlePickerChange}
          />
        )}

        {tab !== 'big_whale' && tab !== 'ticker_investigation' && (
          <FormField label="Tickers (comma-separated, no count limit)">
            <Textarea rows={2} value={tickers} onChange={(e) => setTickers(e.target.value)} />
          </FormField>
        )}

        {tab === 'big_whale' && (
          <p className="mb-4 text-sm text-slate-400">
            Big Whale scan runs a global crypto universe scan — no tickers required.
          </p>
        )}

        {tab === 'sentiment_screener' && (
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

        {tab === 'mtf_scanner' && (
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

        {tab === 'weak_strong_sr' && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
              Weak Strong S-R timeframes (MTF aggregate when 2+)
            </p>
            <div className="flex flex-wrap gap-2">
              {WSSR_TFS.map((tf) => (
                <Chip key={tf} selected={wssrTfs.includes(tf)} onClick={() => toggleTf(tf, wssrTfs, setWssrTfs)}>
                  {tf}
                </Chip>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Strong/weak S/R · consolidation · supply/demand · VWAP · Volume · Supertrend · RSI · MTF
            </p>
          </div>
        )}

        {isEngine && tab !== 'big_whale' && tab !== 'weak_strong_sr' && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
              Chart timeframe (default: {active?.default_tf ?? '15m'})
            </p>
            <div className="flex flex-wrap gap-2">
              {ENGINE_TFS.map((tf) => (
                <Chip
                  key={tf}
                  selected={(engineTf || active?.default_tf) === tf}
                  onClick={() => setEngineTf(tf)}
                >
                  {tf}
                </Chip>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || bg.runInBackground}>
            {mutation.isPending
              ? `Scanning…`
              : tab === 'ticker_investigation'
                ? `Investigate${picker.tickers.length ? ` (${picker.tickers.length})` : ''}`
                : tab === 'big_whale'
                  ? 'Run whale scan'
                  : `Run scan${parseTickers(tickers).length ? ` (${parseTickers(tickers).length})` : ''}`}
          </Button>
          {tab !== 'big_whale' && (
            <span className="text-xs text-slate-500">Full selected universe is scanned — no ticker cap.</span>
          )}
        </div>
        <AnalysisBackgroundControls
          bg={bg}
          placeholder={`${active?.label ?? tab} · ${new Date().toLocaleDateString()}`}
          onStart={() => bg.startBackground(buildPayload(), validateRun)}
        />
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {mutation.isPending && !bg.viewedPayload && (
        <Loading message="Analysis can take 1–3 minutes per ticker — fetching Groww/yfinance data…" />
      )}

      {(!mutation.isPending || bg.viewedPayload) && displayData && (
        <Card>
          {bg.viewedReportMeta?.name && (
            <p className="mb-3 text-sm text-slate-400">
              Viewing saved report: <span className="text-slate-200">{bg.viewedReportMeta.name}</span>
            </p>
          )}
          <StrategyDataSourceBar data={displayData as Record<string, unknown>} assetClass={assetClass} />
          {tab === 'ticker_investigation' && (
            <TickerInvestigationPanel data={displayData as Record<string, unknown>} />
          )}
          {tab === 'sentiment_screener' && (
            <SentimentScreenerPanel data={displayData as Record<string, unknown>} />
          )}
          {tab === 'mtf_scanner' && <MtfScannerPanel data={displayData as Record<string, unknown>} />}
          {isEngine && <TaScreenerResultsPanel data={displayData as Record<string, unknown>} />}
        </Card>
      )}

      {displayData && (
        <AskAIPanel
          context={buildAskContext(active?.label ?? tab, displayData)}
          section={`technical-analysis/${tab}`}
        />
      )}
    </div>
  )
}
