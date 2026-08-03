import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart2, Clock, Crosshair, FolderOpen, Save, Trash2, TrendingUp, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteIntraHedgingReport,
  fetchIntraHedgingJob,
  fetchIntraHedgingJobs,
  fetchIntraHedgingReport,
  fetchIntraHedgingReports,
  fetchTradingHubs,
  runTradingHubScan,
  saveIntraHedgingReport,
  startIntraHedgingJob,
  type TradingHub,
  type TradingHubSection,
} from '../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { TradingHubResultsPanel } from '../components/trading-hubs/TradingHubPanels'
import { Swing5Panel } from '../components/trading-hubs/Swing5Panel'
import { WatchlistMarketProvider, type WatchlistMarket } from '../components/watchlist/WatchlistMarketContext'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

interface IhSavedReportSummary {
  id: number
  name: string
  asset_class: string
  created_at: string
  summary?: {
    universe_desc?: string | null
    universe_mode?: string | null
    pair_count?: number
    best_pair?: string | null
    best_pair_confidence_pct?: number | null
  }
}

interface IhBgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: Record<string, unknown>
  meta?: {
    asset_class?: string
    universe_mode?: string | null
  }
  created_at?: number
}

function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const HUB_ICONS: Record<string, typeof TrendingUp> = {
  swing: TrendingUp,
  intraday: Clock,
  scalping: Crosshair,
  smart_money: BarChart2,
}

// Every Trading Hubs strategy trades a fixed timeframe (or fixed combination of
// timeframes) per its own strategy definition — there is no adjustable timeframe
// selector here on purpose. This is display-only context next to each section.
const SECTION_TIMEFRAME_LABEL: Record<string, string> = {
  swing_trading_st: 'Daily',
  swing_trading_st_mtf_mss: 'Weekly + Daily bias + 15m MSS execution',
  swing_trading_st_supertrend: 'Daily (Swing mode) / Weekly (Pyramid mode)',
  swing_trading_st_kiss: 'Weekly bias + 1h execution',
  swing_trading_st_ha_ema: 'Daily bias + 5m execution',
  swing_trading_st_simple_steal: 'Daily',
  swing_trend_breakout: 'Daily (weekly + index-daily context)',
  swing_trend_velocity: 'Daily (50/250-day moving averages) — position trade, months to years',
  swing_bb_vwap_reversal: 'HTF bias (1h/4h) + LTF entry (5m/15m selectable below)',
  smc_liquidity_silver_bullet: 'HTF bias (1h/4h/1d) + LTF sweep/MSS/FVG execution (5m/15m selectable below)',
  scalp_ny_open_bias: '1H bias candle (9:00 AM ET) + 1m execution — entry style selectable below',
  intraday_alpha_945: '30m opening range + Daily trend filter',
  intraday_7_wasted: 'Daily bias + 5m opening range + 1m execution',
  intraday_london_breakout:
    '5m · US Pre-Market 04:00–09:30 ET → RTH to 16:00 · Crypto Low Activity 04:00–11:00 IST → Peak 17:30–01:30 IST · India/Commodity unchanged',
  intraday_fib945: '30m opening-range bias + 5m execution',
  intra_hwp: '5m',
  intraday_vwap_fade: '15m HTF + 5m execution',
  intraday_mtf_breakout_retest: 'Daily bias + 30m/1h/4h HTF + 15m execution',
  scalp_arc: '5m',
  scalp_crt_fvg: '1h HTF sweep + 5m LTF FVG entry',
  scalp_multi_indicator: '1m',
  scalp_rectangle: '1m',
  scalp_heikin_ashi: '1m (India 09:45-11:45 IST / US 10:00-12:00 ET session window; crypto unrestricted)',
  scalp_livefree_fx: 'HTF 1D/4H/1H · 15m sessions · 5m sweep + BoS',
  scalp_smc: '4h HTF + 1h MTF + 5m LTF fusion',
  scalp_sr_mss: '1h HTF zone + 1m MSS entry',
  scalp_weekly: 'Weekly range (from daily) + configurable execution timeframe (15m/1h/4h)',
  scalp_ichimoku_crash: 'Configurable (1h/4h/1d selectable below) — crypto (ETH/BTC) or any market',
  scalp_2min: '2m (1m resampled) · Nifty 50 / Bank Nifty / Sensex only',
  weekly_candle_continuation: 'Configurable (entry timeframe selectable below)',
  smc_cisd: '1h bias + 15m execution',
  smc_htf_zone_sweep: 'Configurable (HTF/LTF selectable below)',
  smc_weekly_sweep_cisd: 'Weekly HTF sweep + 15m execution',
  smc_mtf_day_plan: '4h HTF + 1h MTF + 15m LTF day plan',
  smc_golden_bullet: '1h HTF + 15m NY kill-zone execution',
  smc_liquidity: '1h bias + 15m execution',
  smc_ttg_sniper: 'Configurable (LTF/HTF selectable below)',
  smb_snp: 'Daily HTF + 5m session-window execution',
  sc_fvg: '15m zone + 5m FVG + 1m entry',
  smc_sc_best: 'Configurable (LTF selectable below) + auto HTF resample for context',
  smc_lewiskelly: 'Configurable (Direction/POI TF selectable below) + fixed 1m confirmation entry',
}

const DEFAULT_PICKER: TickerPickerValue = { tickers: [], durations: [] }

function defaultConfig(section: TradingHubSection | undefined): Record<string, string> {
  if (!section?.config_options) return {}
  const out: Record<string, string> = {}
  for (const [key, opt] of Object.entries(section.config_options)) {
    if (opt.default != null) out[key] = String(opt.default)
  }
  return out
}

function sectionHasFixedUniverse(section: TradingHubSection | undefined): boolean {
  return Boolean(section?.fixed_universe?.length)
}

export default function TradingHubs() {
  const [searchParams] = useSearchParams()
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [hubId, setHubId] = useState(searchParams.get('hub') || 'swing')
  const [sectionId, setSectionId] = useState(searchParams.get('section') || '')
  const [picker, setPicker] = useState<TickerPickerValue>(DEFAULT_PICKER)
  const [config, setConfig] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  const queryClient = useQueryClient()
  const isIntraHedging = sectionId === 'intra_hedging'
  const [runInBackground, setRunInBackground] = useState(false)
  const [bgReportName, setBgReportName] = useState('')
  const [bgJobIds, setBgJobIds] = useState<string[]>([])
  const [bgError, setBgError] = useState('')
  const [bgMsg, setBgMsg] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const handledDoneRef = useRef<Set<string>>(new Set())

  const ihReportsQuery = useQuery({
    queryKey: ['ih-reports'],
    queryFn: fetchIntraHedgingReports,
    enabled: isIntraHedging,
  })
  const ihReports = ((ihReportsQuery.data as { reports?: IhSavedReportSummary[] } | undefined)?.reports) ?? []

  const ihRunningJobsQuery = useQuery({
    queryKey: ['ih-jobs-running'],
    queryFn: () => fetchIntraHedgingJobs('running'),
    enabled: isIntraHedging,
    refetchInterval: isIntraHedging ? 2000 : false,
  })
  const ihRecentJobsQuery = useQuery({
    queryKey: ['ih-jobs-recent'],
    queryFn: () => fetchIntraHedgingJobs('all'),
    enabled: isIntraHedging,
  })
  const ihRecentJobs = ((ihRecentJobsQuery.data as { jobs?: IhBgJobStatus[] } | undefined)?.jobs) ?? []
  const ihRecentFinished = ihRecentJobs.filter((j) => j.status !== 'running').slice(0, 8)

  useEffect(() => {
    const serverJobs = ((ihRunningJobsQuery.data as { jobs?: IhBgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [ihRunningJobsQuery.data])

  const ihJobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['ih-job', id],
      queryFn: () => fetchIntraHedgingJob(id) as Promise<IhBgJobStatus>,
      enabled: isIntraHedging,
      refetchInterval: (q: { state: { data?: IhBgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })
  const ihJobById = useMemo(() => {
    const map = new Map<string, IhBgJobStatus>()
    ihJobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as IhBgJobStatus)
    })
    return map
  }, [ihJobQueries, bgJobIds])

  useEffect(() => {
    if (!isIntraHedging) return
    let changed = false
    const stillRunning: string[] = []
    for (const id of bgJobIds) {
      const job = ihJobById.get(id)
      if (!job || job.status === 'running') {
        stillRunning.push(id)
        continue
      }
      if (!handledDoneRef.current.has(id)) {
        handledDoneRef.current.add(id)
        changed = true
        if (job.status === 'done' && job.report_id) {
          setViewedReportId(job.report_id)
          setBgMsg(`Background report saved${job.name ? `: ${job.name}` : ''}.`)
        } else if (job.status === 'done') {
          setBgMsg(job.name ? `Background run "${job.name}" finished.` : 'Background run finished.')
        } else if (job.status === 'error') {
          setBgError(job.error || `Background job failed: ${job.name || id}`)
        }
      }
    }
    if (stillRunning.length !== bgJobIds.length) setBgJobIds(stillRunning)
    if (changed) {
      queryClient.invalidateQueries({ queryKey: ['ih-reports'] })
      queryClient.invalidateQueries({ queryKey: ['ih-jobs-running'] })
      queryClient.invalidateQueries({ queryKey: ['ih-jobs-recent'] })
    }
  }, [bgJobIds, ihJobById, isIntraHedging, queryClient])

  const ihOngoingBg = bgJobIds
    .map((id) => ihJobById.get(id))
    .filter((j): j is IhBgJobStatus => !!j && j.status === 'running')
  const ihServerRunning = ((ihRunningJobsQuery.data as { jobs?: IhBgJobStatus[] } | undefined)?.jobs) ?? []
  const ihOngoingMap = new Map<string, IhBgJobStatus>()
  for (const j of [...ihServerRunning, ...ihOngoingBg]) {
    if (j.status === 'running') ihOngoingMap.set(j.job_id, j)
  }
  const ihOngoingList = Array.from(ihOngoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const ihReportDetailQuery = useQuery({
    queryKey: ['ih-report', viewedReportId],
    queryFn: () => fetchIntraHedgingReport(viewedReportId as number),
    enabled: isIntraHedging && viewedReportId != null,
  })

  const ihStartBgMutation = useMutation({
    mutationFn: startIntraHedgingJob,
    onSuccess: (data) => {
      const id = data.job_id as string
      setBgError('')
      setBgMsg(`Background run started${data.name ? `: ${data.name}` : ''}.`)
      setBgReportName('')
      setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
      queryClient.invalidateQueries({ queryKey: ['ih-jobs-running'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const ihSaveReportMutation = useMutation({
    mutationFn: saveIntraHedgingReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['ih-reports'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const ihDeleteReportMutation = useMutation({
    mutationFn: deleteIntraHedgingReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['ih-reports'] })
    },
  })

  useEffect(() => {
    setViewedReportId(null)
    setBgError('')
    setBgMsg('')
    setRunInBackground(false)
  }, [sectionId])

  const hubsQ = useQuery({ queryKey: ['trading-hubs'], queryFn: fetchTradingHubs })

  const activeHub = useMemo(
    () => hubsQ.data?.hubs?.find((h) => h.id === hubId) as TradingHub | undefined,
    [hubsQ.data, hubId],
  )

  const activeSection = useMemo(
    () => activeHub?.sections?.find((s) => s.id === sectionId) as TradingHubSection | undefined,
    [activeHub, sectionId],
  )

  const fixedUniverse = sectionHasFixedUniverse(activeSection)
  const scanTickers = useMemo(
    () => (fixedUniverse ? (activeSection?.fixed_universe ?? []) : picker.tickers),
    [fixedUniverse, activeSection?.fixed_universe, picker.tickers],
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

  const handleAssetClassChange = (next: AssetClass) => {
    setAssetClass(next)
    setPicker(DEFAULT_PICKER)
    setError('')
  }

  const handlePickerChange = useCallback((v: TickerPickerValue) => {
    setPicker(v)
  }, [])

  const scanMutation = useMutation({
    mutationFn: () => {
      if (!sectionId) throw new Error('Select a section')
      const tickers = fixedUniverse
        ? (activeSection?.fixed_universe ?? [])
        : picker.tickers
      if (!tickers.length) throw new Error('Select at least one ticker')
      return runTradingHubScan({
        section_id: sectionId,
        tickers,
        // Fixed-universe strategies (e.g. Scalp-2mins) are India indices only.
        asset_class: fixedUniverse ? 'india' : assetClass,
        config: Object.keys(config).length ? config : undefined,
      })
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => { setError(''); setViewedReportId(null) },
  })

  const startIntraHedgingBackgroundRun = () => {
    if (!scanTickers.length) {
      setBgError('Select at least one ticker')
      return
    }
    if (!bgReportName.trim()) {
      setBgError('Enter a report name for the background run')
      return
    }
    setBgError('')
    setBgMsg('')
    ihStartBgMutation.mutate({
      tickers: scanTickers,
      asset_class: fixedUniverse ? 'india' : assetClass,
      config: Object.keys(config).length ? config : undefined,
      run_in_background: true,
      report_name: bgReportName.trim(),
    })
  }

  const ihViewedReport = ihReportDetailQuery.data as { name?: string; payload?: Record<string, unknown>; created_at?: string; error?: string } | undefined
  const ihResult: Record<string, unknown> | undefined =
    isIntraHedging && viewedReportId != null ? ihViewedReport?.payload : (scanMutation.data as Record<string, unknown> | undefined)

  const watchlistMarket: WatchlistMarket =
    assetClass === 'us' || assetClass === 'commodity' ? 'us' : assetClass === 'crypto' ? 'crypto' : 'india'

  return (
    <WatchlistMarketProvider market={watchlistMarket}>
    <div>
      <PageHeader
        title="Trading Hubs"
        description="Swing Trading · Intraday · Scalping · Smart Money — India · US · Crypto · Commodities"
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
          <div className="mb-4">
            <p className="text-sm text-slate-400">{activeSection.description}</p>
            {!activeSection.multi_strategy && (
              <p className="mt-1 text-xs text-slate-500">
                🕒 Fixed timeframe: <span className="text-slate-300">{SECTION_TIMEFRAME_LABEL[activeSection.id] ?? 'Per strategy definition'}</span>
                {' — not user-adjustable, this strategy always trades this timeframe.'}
              </p>
            )}
            {activeSection.guide && (
              <details className="mt-3 rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium text-slate-200">
                  What this strategy does
                </summary>
                <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{activeSection.guide}</pre>
              </details>
            )}
          </div>
        )}

        {fixedUniverse ? (
          <div className="rounded-lg border border-slate-700/80 bg-slate-900/50 px-4 py-3">
            <p className="text-sm font-medium text-slate-200">
              {activeSection?.fixed_universe_label ?? 'Fixed scan universe'}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              This strategy does not use the Crypto / US / commodity ticker picker. It always scans:{' '}
              <span className="text-slate-300">{(activeSection?.fixed_universe ?? []).join(' · ')}</span>
            </p>
          </div>
        ) : (
          <>
            <FormField label="Asset class">
              <Select value={assetClass} onChange={(e) => handleAssetClassChange(e.target.value as AssetClass)}>
                <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
                <option value="us">🇺🇸 US stocks (Yahoo)</option>
                <option value="crypto">₿ Crypto (CoinDCX)</option>
                <option value="commodity">🛢️ Commodity futures</option>
              </Select>
            </FormField>

            <div className="mt-4">
              <AssetClassTickerPicker
                key={assetClass}
                assetClass={assetClass}
                showDurations={false}
                onChange={handlePickerChange}
              />
            </div>
          </>
        )}

        {activeSection?.multi_strategy ? (
          <div className="mt-4">
            <Swing5Panel
              tickers={scanTickers}
              assetClass={assetClass}
              strategyKeys={activeSection.strategy_keys ?? []}
              strategyLabels={activeSection.strategy_labels ?? {}}
              timeframeOptions={activeSection.timeframe_options ?? []}
            />
          </div>
        ) : (
          <>
            {activeSection && Object.entries(activeSection.config_options ?? {}).map(([key, opt]) => (
              <div key={key} className="mt-4">
                <FormField label={opt.label}>
                  {opt.type === 'select' && opt.choices ? (
                    <Select value={config[key] ?? opt.default ?? ''} onChange={(e) => setConfig((c) => ({ ...c, [key]: e.target.value }))}>
                      {opt.choices.map((ch) => (
                        <option key={ch.value} value={ch.value}>{ch.label}</option>
                      ))}
                    </Select>
                  ) : opt.type === 'number' ? (
                    <Input
                      type="number"
                      step={opt.step != null ? String(opt.step) : undefined}
                      min={opt.min != null ? String(opt.min) : undefined}
                      max={opt.max != null ? String(opt.max) : undefined}
                      value={config[key] ?? String(opt.default ?? '')}
                      onChange={(e) => setConfig((c) => ({ ...c, [key]: e.target.value }))}
                    />
                  ) : opt.type === 'text' ? (
                    <Input
                      type="text"
                      placeholder={String(opt.default ?? '')}
                      value={config[key] ?? ''}
                      onChange={(e) => setConfig((c) => ({ ...c, [key]: e.target.value }))}
                    />
                  ) : null}
                </FormField>
              </div>
            ))}

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending || !sectionId || !scanTickers.length || (isIntraHedging && runInBackground)}>
                {scanMutation.isPending
                  ? `Scanning ${scanTickers.length} ticker${scanTickers.length === 1 ? '' : 's'}…`
                  : `Run live scan${scanTickers.length ? ` (${scanTickers.length})` : ''}`}
              </Button>
              {scanTickers.length > 0 && (
                <span className="text-xs text-slate-500">No ticker count limit — full selected universe is scanned.</span>
              )}
            </div>
            {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}

            {isIntraHedging && (
              <div className="mt-4 space-y-3 rounded-xl border border-slate-800/60 bg-slate-900/30 p-3">
                <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-800 text-teal-500"
                    checked={runInBackground}
                    onChange={(e) => setRunInBackground(e.target.checked)}
                  />
                  <span>
                    <span className="font-medium text-slate-100">Run in background</span>
                    <span className="mt-0.5 block text-xs text-slate-500">
                      Name the run — it keeps going if you leave this page, then auto-saves into Saved
                      reports below when done. You can start several background runs at once.
                    </span>
                  </span>
                </label>
                {runInBackground && (
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-[16rem] flex-1">
                      <FormField label="Report name">
                        <Input
                          value={bgReportName}
                          onChange={(e) => setBgReportName(e.target.value)}
                          placeholder={`Intra-Hedging · ${new Date().toLocaleDateString()}`}
                          maxLength={200}
                        />
                      </FormField>
                    </div>
                    <Button onClick={startIntraHedgingBackgroundRun} disabled={ihStartBgMutation.isPending}>
                      {ihStartBgMutation.isPending ? 'Starting…' : 'Start background run'}
                    </Button>
                  </div>
                )}
                {bgError && <Alert type="error">{bgError}</Alert>}
                {bgMsg && <Alert type="success">{bgMsg}</Alert>}
              </div>
            )}
          </>
        )}
      </Card>

      {hubsQ.isLoading && <Loading message="Loading trading hubs…" />}

      {isIntraHedging && ihOngoingList.length > 0 && (
        <Card className="mb-4">
          <h4 className="mb-3 font-medium text-white">Background runs in progress ({ihOngoingList.length})</h4>
          <div className="space-y-3">
            {ihOngoingList.map((job) => (
              <div key={job.job_id} className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-amber-100">{job.name || 'Untitled background run'}</p>
                  <p className="text-xs text-slate-500">{Math.round((job.progress ?? 0) * 100)}%</p>
                </div>
                <p className="mt-1 text-sm text-slate-300">{job.progress_note || 'Starting…'}</p>
                <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-amber-400 transition-all"
                    style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {isIntraHedging && ihRecentFinished.length > 0 && (
        <Card className="mb-4">
          <h4 className="mb-3 font-medium text-white">Recent background runs</h4>
          <div className="space-y-2">
            {ihRecentFinished.map((job) => (
              <div
                key={job.job_id}
                className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${
                  job.status === 'error' ? 'border-rose-500/30 bg-rose-500/5' : 'border-slate-800/60 bg-slate-900/40'
                }`}
              >
                <div>
                  {job.status === 'done' && job.report_id ? (
                    <button className="font-medium text-slate-200 hover:text-teal-400" onClick={() => setViewedReportId(job.report_id as number)}>
                      {job.name || 'Untitled background run'}
                    </button>
                  ) : (
                    <span className="font-medium text-slate-200">{job.name || 'Untitled background run'}</span>
                  )}
                  {job.status === 'error' && (
                    <p className="mt-1 text-xs text-rose-400">{job.error || 'Failed — no further detail available.'}</p>
                  )}
                </div>
                <span className={`text-xs font-medium ${job.status === 'error' ? 'text-rose-400' : job.report_id ? 'text-emerald-400' : 'text-slate-400'}`}>
                  {job.status === 'error' ? 'Failed' : job.report_id ? 'Saved' : 'Done (not saved)'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {isIntraHedging && (
        <Card className="mb-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h4 className="inline-flex items-center gap-2 font-medium text-white">
              <FolderOpen size={16} className="text-slate-400" />
              Saved reports
              <span className="text-sm font-normal text-slate-500">({ihReports.length})</span>
            </h4>
            <Button variant="ghost" size="sm" onClick={() => ihReportsQuery.refetch()} disabled={ihReportsQuery.isFetching}>
              Refresh
            </Button>
          </div>
          {ihReportsQuery.isLoading && <Loading message="Loading saved reports…" />}
          {!ihReportsQuery.isLoading && !ihReports.length && (
            <p className="text-sm text-slate-500">No saved reports yet. Run a scan and save it, or start a named background run.</p>
          )}
          <div className="space-y-2">
            {ihReports.map((r) => {
              const s = r.summary
              return (
                <div
                  key={r.id}
                  className={`flex flex-wrap items-start justify-between gap-2 rounded-lg border px-3 py-2.5 text-sm ${
                    viewedReportId === r.id ? 'border-teal-500/50 bg-teal-500/5' : 'border-slate-800/60 bg-slate-900/40'
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <button className="font-medium text-slate-200 hover:text-teal-400" onClick={() => setViewedReportId(r.id)}>
                      {r.name}
                    </button>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Saved {formatWhen(r.created_at)}
                      {s?.universe_desc ? ` · ${s.universe_desc}` : ''}
                    </p>
                    {s?.best_pair && (
                      <p className="mt-1 text-xs text-teal-400/90">
                        Best pair: {s.best_pair}{s.best_pair_confidence_pct != null ? ` · ${s.best_pair_confidence_pct.toFixed(0)}% confidence` : ''}
                        {s.pair_count != null ? ` · ${s.pair_count} pair(s) found` : ''}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (window.confirm(`Delete saved report "${r.name}"? This cannot be undone.`)) {
                        ihDeleteReportMutation.mutate(r.id)
                      }
                    }}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {!activeSection?.multi_strategy && scanMutation.isPending && (
        <Loading message="Running live scan — fetching OHLCV from Groww/yfinance (1–3 min)…" />
      )}

      {!activeSection?.multi_strategy && !scanMutation.isPending && ihResult && (
        <Card>
          {isIntraHedging && (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                {viewedReportId != null && ihViewedReport?.name && (
                  <p className="text-sm text-slate-400">
                    Viewing saved report: <span className="text-slate-200">{ihViewedReport.name}</span>
                    {ihViewedReport.created_at ? ` · saved ${formatWhen(ihViewedReport.created_at)}` : ''}
                  </p>
                )}
              </div>
              <div className="flex gap-2">
                {viewedReportId == null && (
                  <Button variant="secondary" size="sm" onClick={() => setShowSaveForm(true)}>
                    <span className="inline-flex items-center gap-1.5"><Save size={14} />Save for future reference</span>
                  </Button>
                )}
                {viewedReportId != null && (
                  <Button variant="ghost" size="sm" onClick={() => setViewedReportId(null)}>
                    <X size={14} />
                  </Button>
                )}
              </div>
            </div>
          )}
          {isIntraHedging && showSaveForm && (
            <div className="mb-4 rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
              <FormField label="Report name">
                <div className="flex gap-2">
                  <Input
                    value={saveName}
                    onChange={(e) => setSaveName(e.target.value)}
                    placeholder={`Intra-Hedging — ${new Date().toLocaleDateString()}`}
                  />
                  <Button
                    onClick={() => ihSaveReportMutation.mutate({
                      name: saveName.trim() || `Intra-Hedging ${new Date().toLocaleString()}`,
                      payload: ihResult,
                    })}
                    disabled={ihSaveReportMutation.isPending}
                  >
                    <span className="inline-flex items-center gap-1.5"><Save size={14} />Save</span>
                  </Button>
                  <Button variant="ghost" onClick={() => setShowSaveForm(false)}>Cancel</Button>
                </div>
              </FormField>
              {saveMsg && <p className="mt-2 text-xs text-emerald-400">{saveMsg}</p>}
            </div>
          )}
          <TradingHubResultsPanel data={ihResult} sectionId={sectionId} assetClass={fixedUniverse ? 'india' : assetClass} />
        </Card>
      )}
    </div>
    </WatchlistMarketProvider>
  )
}
