import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Loader2, Play, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  apiErrorMessage,
  createAlertMonitor,
  createAlertSchedule,
  deleteAlertMonitor,
  deleteAlertSchedule,
  deleteAlertScheduleHit,
  deleteAlertScheduleHits,
  enableAlertSchedule,
  fetchAlertMonitors,
  fetchAlertNotifyConfig,
  fetchAlertScheduleCatalog,
  fetchAlertScheduleHits,
  fetchAlertSchedules,
  fetchAlertsConfig,
  pollAlerts,
  runAlertSchedule,
  runDueAlertSchedules,
  saveAlertNotifyConfig,
  toggleAlertMonitor,
  type AlertScheduleCatalogGroup,
} from '../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert } from '../components/ui/Feedback'
import { DataTable, SortableTh, Td, Th, useSort } from '../components/ui/Table'

const ALL_TFS = ['1m', '3m', '5m', '15m', '1d']
const DEFAULT_INDICATORS = [{ type: 'rsi', period: 14 }, { type: 'ema', period: 20 }]
const DEFAULT_ENTRY = [{ left: 'rsi_14', op: '<', right_type: 'value', right_val: '35' }]

type TabId = 'monitors' | 'schedules' | 'notify'

export default function Alerts() {
  const [tab, setTab] = useState<TabId>('schedules')
  const configQuery = useQuery({ queryKey: ['alerts-config'], queryFn: fetchAlertsConfig })
  const config = configQuery.data as Record<string, unknown> | undefined

  return (
    <div>
      <PageHeader
        title="Strategy Alerts"
        description="Monitors · Setup & Schedule · SMTP / Telegram — actionable trades emailed or messaged"
      />

      {config && (
        <div className="mb-4 flex flex-wrap gap-2 text-xs">
          <span className={`rounded-lg px-2.5 py-1 ring-1 ${config.alerts_enabled ? 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30' : 'bg-slate-500/15 text-slate-400 ring-slate-500/30'}`}>
            Alerts {config.alerts_enabled ? 'enabled' : 'disabled'}
          </span>
          <span className={`rounded-lg px-2.5 py-1 ring-1 ${config.telegram_configured ? 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30' : 'bg-slate-500/15 text-slate-400 ring-slate-500/30'}`}>
            Telegram {config.telegram_configured ? 'ready' : 'not configured'}
          </span>
          <span className={`rounded-lg px-2.5 py-1 ring-1 ${config.email_configured ? 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30' : 'bg-slate-500/15 text-slate-400 ring-slate-500/30'}`}>
            Email {config.email_configured ? 'ready' : 'not configured'}
          </span>
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        <Chip selected={tab === 'monitors'} onClick={() => setTab('monitors')}>Monitors</Chip>
        <Chip selected={tab === 'schedules'} onClick={() => setTab('schedules')}>Setup & Schedule</Chip>
        <Chip selected={tab === 'notify'} onClick={() => setTab('notify')}>Notify config</Chip>
      </div>

      {tab === 'monitors' && <MonitorsPanel />}
      {tab === 'schedules' && <SchedulesPanel />}
      {tab === 'notify' && <NotifyConfigPanel />}
    </div>
  )
}

function MonitorsPanel() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [name, setName] = useState('RSI oversold alert')
  const [ticker, setTicker] = useState('RELIANCE')
  const [timeframe, setTimeframe] = useState('1d')
  const [pollMinutes, setPollMinutes] = useState(15)

  const monitorsQuery = useQuery({ queryKey: ['alerts-monitors'], queryFn: fetchAlertMonitors })
  const createMut = useMutation({
    mutationFn: () =>
      createAlertMonitor({
        name,
        ticker: ticker.toUpperCase(),
        timeframe,
        poll_minutes: pollMinutes,
        indicators: DEFAULT_INDICATORS,
        entry_rules: DEFAULT_ENTRY,
        exit_rules: [],
        strategy_name: 'RSI oversold',
        notify_telegram: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alerts-monitors'] })
      setError('')
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  const pollMut = useMutation({
    mutationFn: (force: boolean) => pollAlerts(force),
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts-monitors'] }),
  })
  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteAlertMonitor(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts-monitors'] }),
  })
  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => toggleAlertMonitor(id, enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts-monitors'] }),
  })

  const monitors = ((monitorsQuery.data as { monitors?: Record<string, unknown>[] })?.monitors) ?? []
  const { sorted: sortedMonitors, sortKey: monitorsSortKey, sortDir: monitorsSortDir, handleSort: handleMonitorsSort } = useSort(
    monitors,
    {
      name: (r) => String(r.name ?? ''),
      ticker: (r) => String(r.ticker ?? ''),
      timeframe: (r) => String(r.timeframe ?? ''),
      last_signal: (r) => String(r.last_signal ?? ''),
      poll_minutes: (r) => Number(r.poll_minutes),
      enabled: (r) => (r.enabled ? 1 : 0),
    },
  )

  return (
    <>
      <Card className="mb-4">
        <h3 className="mb-4 flex items-center gap-2 font-medium text-white">
          <Plus size={16} />
          New monitor
        </h3>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <FormField label="Ticker">
            <Input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} />
          </FormField>
          <FormField label="Timeframe">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {['5m', '15m', '1h', '4h', '1d'].map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </Select>
          </FormField>
          <FormField label="Poll every (minutes)">
            <Input type="number" min={1} value={pollMinutes} onChange={(e) => setPollMinutes(Number(e.target.value))} />
          </FormField>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Default strategy: RSI &lt; 35 with EMA(20). Prefer Setup & Schedule for multi-ticker scans.
        </p>
        <Button className="mt-4" onClick={() => createMut.mutate()} disabled={createMut.isPending}>
          Create monitor
        </Button>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      <Card>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 font-medium text-white">
            <Bell size={16} />
            Active monitors ({monitors.length})
          </h3>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => pollMut.mutate(false)} disabled={pollMut.isPending}>
              <RefreshCw size={14} className="mr-1.5" />
              Poll due
            </Button>
            <Button variant="secondary" onClick={() => pollMut.mutate(true)} disabled={pollMut.isPending}>
              Force poll all
            </Button>
          </div>
        </div>

        {monitors.length === 0 ? (
          <p className="text-sm text-slate-500">No monitors yet.</p>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <SortableTh active={monitorsSortKey === 'name'} direction={monitorsSortDir} onSort={() => handleMonitorsSort('name')}>Name</SortableTh>
                <SortableTh active={monitorsSortKey === 'ticker'} direction={monitorsSortDir} onSort={() => handleMonitorsSort('ticker')}>Ticker</SortableTh>
                <SortableTh active={monitorsSortKey === 'timeframe'} direction={monitorsSortDir} onSort={() => handleMonitorsSort('timeframe')}>TF</SortableTh>
                <SortableTh active={monitorsSortKey === 'last_signal'} direction={monitorsSortDir} onSort={() => handleMonitorsSort('last_signal')}>Signal</SortableTh>
                <SortableTh active={monitorsSortKey === 'poll_minutes'} direction={monitorsSortDir} onSort={() => handleMonitorsSort('poll_minutes')}>Poll</SortableTh>
                <SortableTh active={monitorsSortKey === 'enabled'} direction={monitorsSortDir} onSort={() => handleMonitorsSort('enabled')}>Status</SortableTh>
                <Th />
              </tr>
            </thead>
            <tbody>
              {sortedMonitors.map((m) => (
                <tr key={Number(m.id)}>
                  <Td>{String(m.name)}</Td>
                  <Td className="font-medium">{String(m.ticker)}</Td>
                  <Td>{String(m.timeframe)}</Td>
                  <Td>{String(m.last_signal ?? '—')}</Td>
                  <Td>{String(m.poll_minutes)}m</Td>
                  <Td>
                    <button
                      type="button"
                      onClick={() => toggleMut.mutate({ id: Number(m.id), enabled: !m.enabled })}
                      className="text-sm text-blue-400 hover:underline"
                    >
                      {m.enabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </Td>
                  <Td>
                    <button type="button" aria-label="Delete monitor" onClick={() => deleteMut.mutate(Number(m.id))} className="text-slate-500 hover:text-rose-400">
                      <Trash2 size={16} />
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Card>
    </>
  )
}

function SchedulesPanel() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [name, setName] = useState('My rotation scan')
  const [market, setMarket] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [timeframes, setTimeframes] = useState<string[]>(['15m', '1d'])
  const [strategies, setStrategies] = useState<string[]>([])
  const [mode, setMode] = useState<'interval' | 'daily_at'>('interval')
  const [pollMinutes, setPollMinutes] = useState(15)
  const [dailyTime, setDailyTime] = useState('09:30')
  const [notifyTg, setNotifyTg] = useState(true)
  const [notifyEmail, setNotifyEmail] = useState(true)

  const catalogQ = useQuery({
    queryKey: ['alert-schedule-catalog'],
    queryFn: fetchAlertScheduleCatalog,
  })
  const schedulesQ = useQuery({ queryKey: ['alert-schedules'], queryFn: fetchAlertSchedules })
  const hitsQ = useQuery({ queryKey: ['alert-schedule-hits'], queryFn: () => fetchAlertScheduleHits({ limit: 50 }) })

  const catalogGroups = catalogQ.data?.groups ?? []
  const runnableSelected = useMemo(
    () => strategies.filter((id) => id.startsWith('scanner:') || id.startsWith('hub:') || id.startsWith('ta:') || !id.includes(':')).length,
    [strategies],
  )
  const schedules = ((schedulesQ.data as { schedules?: Record<string, unknown>[] })?.schedules) ?? []
  const hits = ((hitsQ.data as { hits?: Record<string, unknown>[] })?.hits) ?? []

  const createMut = useMutation({
    mutationFn: () =>
      createAlertSchedule({
        name,
        market,
        tickers: picker.tickers,
        timeframes,
        strategies,
        schedule_mode: mode,
        poll_minutes: pollMinutes,
        daily_time: mode === 'daily_at' ? dailyTime : null,
        notify_telegram: notifyTg,
        notify_email: notifyEmail,
        enabled: false,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-schedules'] })
      setError('')
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const [runMsg, setRunMsg] = useState('')
  const [runningId, setRunningId] = useState<number | null>(null)
  const [selectedHits, setSelectedHits] = useState<number[]>([])

  const enableMut = useMutation({
    mutationFn: async ({ id, enabled }: { id: number; enabled: boolean }) => {
      await enableAlertSchedule(id, enabled)
      // Start used to only flip the flag — also force-run so something happens immediately.
      if (enabled) {
        setRunningId(id)
        setRunMsg(`Starting scan for schedule #${id}…`)
        return runAlertSchedule(id, true)
      }
      return { enabled: false }
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['alert-schedules'] })
      qc.invalidateQueries({ queryKey: ['alert-schedule-hits'] })
      setRunningId(null)
      if (data && typeof data === 'object' && 'status' in data) {
        setRunMsg(String((data as { status?: string }).status ?? JSON.stringify(data)))
        setError('')
      } else if (data && typeof data === 'object' && 'error' in data) {
        setError(String((data as { error?: string }).error))
        setRunMsg('')
      }
    },
    onError: (e) => {
      setRunningId(null)
      setError(apiErrorMessage(e))
    },
  })
  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteAlertSchedule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alert-schedules'] }),
  })
  const runMut = useMutation({
    mutationFn: (id: number) => {
      setRunningId(id)
      setRunMsg(`Scanning schedule #${id}…`)
      setError('')
      return runAlertSchedule(id, true)
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['alert-schedules'] })
      qc.invalidateQueries({ queryKey: ['alert-schedule-hits'] })
      setRunningId(null)
      if (data && typeof data === 'object' && 'error' in data && (data as { error?: string }).error) {
        setError(String((data as { error?: string }).error))
        setRunMsg('')
      } else {
        setRunMsg(String((data as { status?: string })?.status ?? JSON.stringify(data)))
      }
    },
    onError: (e) => {
      setRunningId(null)
      setError(apiErrorMessage(e))
      setRunMsg('')
    },
  })
  const runDueMut = useMutation({
    mutationFn: () => runDueAlertSchedules(),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['alert-schedules'] })
      qc.invalidateQueries({ queryKey: ['alert-schedule-hits'] })
      setRunMsg(`Run due: ${JSON.stringify(data)}`)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const deleteHitMut = useMutation({
    mutationFn: (id: number) => deleteAlertScheduleHit(id),
    onSuccess: (_d, id) => {
      setSelectedHits((prev) => prev.filter((x) => x !== id))
      qc.invalidateQueries({ queryKey: ['alert-schedule-hits'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })
  const deleteHitsMut = useMutation({
    mutationFn: (payload: { ids?: number[]; delete_all?: boolean }) => deleteAlertScheduleHits(payload),
    onSuccess: () => {
      setSelectedHits([])
      qc.invalidateQueries({ queryKey: ['alert-schedule-hits'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const hitIds = hits.map((h) => Number(h.id))
  const allHitsSelected = hitIds.length > 0 && hitIds.every((id) => selectedHits.includes(id))
  const toggleHit = (id: number) =>
    setSelectedHits((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  const toggleAllHits = () =>
    setSelectedHits(allHitsSelected ? [] : hitIds)

  const toggleTf = (tf: string) =>
    setTimeframes((prev) => (prev.includes(tf) ? prev.filter((x) => x !== tf) : [...prev, tf]))
  const toggleStrategy = (id: string) =>
    setStrategies((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 font-medium text-white">Create schedule</h3>
        <p className="mb-3 text-xs text-slate-500">
          Named multi-ticker × timeframe × strategy jobs. Start or Play scans immediately; Start also enables the
          background worker. Scanner auto-picks matching TFs per strategy category (scalp/intraday/swing).
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Schedule name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <FormField label="Market">
            <div className="flex flex-wrap gap-1.5 pt-1">
              {(['india', 'us', 'crypto'] as AssetClass[]).map((m) => (
                <Chip key={m} selected={market === m} onClick={() => { setMarket(m); setPicker({ tickers: [], durations: ['1d'] }) }}>{m}</Chip>
              ))}
            </div>
          </FormField>
          <FormField label="Mode">
            <Select value={mode} onChange={(e) => setMode(e.target.value as 'interval' | 'daily_at')}>
              <option value="interval">Interval</option>
              <option value="daily_at">Daily at time (IST)</option>
            </Select>
          </FormField>
          {mode === 'interval' ? (
            <FormField label="Every (minutes)">
              <Input type="number" min={1} value={pollMinutes} onChange={(e) => setPollMinutes(Number(e.target.value))} />
            </FormField>
          ) : (
            <FormField label="Daily time (HH:MM IST)">
              <Input value={dailyTime} onChange={(e) => setDailyTime(e.target.value)} placeholder="09:30" />
            </FormField>
          )}
          <FormField label="Notify">
            <div className="flex gap-3 pt-2 text-sm text-slate-300">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={notifyTg} onChange={(e) => setNotifyTg(e.target.checked)} />
                Telegram
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={notifyEmail} onChange={(e) => setNotifyEmail(e.target.checked)} />
                Email
              </label>
            </div>
          </FormField>
        </div>

        <div className="mt-4">
          <AssetClassTickerPicker
            key={market}
            assetClass={market}
            onChange={setPicker}
            showDurations={false}
          />
        </div>

        <div className="mt-4">
          <p className="mb-2 text-xs text-slate-500">Timeframes</p>
          <div className="flex flex-wrap gap-1.5">
            {ALL_TFS.map((tf) => (
              <Chip key={tf} selected={timeframes.includes(tf)} onClick={() => toggleTf(tf)}>{tf}</Chip>
            ))}
          </div>
        </div>

        <div className="mt-4">
          <p className="mb-1 text-xs text-slate-500">
            Strategies ({strategies.length} selected · {runnableSelected} Force-run capable).
            Scanner / Trading Hubs / TA run now; other groups are saved for later runners.
          </p>
          {catalogQ.isLoading && <p className="text-xs text-slate-500">Loading catalog…</p>}
          <div className="mt-2 max-h-80 space-y-2 overflow-y-auto rounded-lg border border-slate-800/80 p-2">
            {catalogGroups.map((g) => (
              <CatalogGroupBlock
                key={g.id}
                group={g}
                selected={strategies}
                onToggle={toggleStrategy}
              />
            ))}
          </div>
        </div>

        <Button
          className="mt-4"
          disabled={createMut.isPending || !name.trim() || !picker.tickers.length || !timeframes.length || !strategies.length}
          onClick={() => createMut.mutate()}
        >
          Save schedule
        </Button>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-medium text-white">Saved schedules ({schedules.length})</h3>
          <Button variant="secondary" onClick={() => runDueMut.mutate()} disabled={runDueMut.isPending || runningId != null}>
            <RefreshCw size={14} className={`mr-1.5 ${runDueMut.isPending ? 'animate-spin' : ''}`} />
            Run due now
          </Button>
        </div>
        {(runMut.isPending || (enableMut.isPending && runningId != null)) && (
          <p className="mb-3 text-sm text-amber-300/90">Scanning… (can take a minute for many tickers)</p>
        )}
        {runMsg && !runMut.isPending && runningId == null && (
          <div className="mb-3">
            <Alert type="success">{runMsg}</Alert>
          </div>
        )}
        {schedules.length === 0 ? (
          <p className="text-sm text-slate-500">No schedules yet.</p>
        ) : (
          <DataTable minWidth={800}>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Market</Th>
                <Th>Tickers</Th>
                <Th>TFs</Th>
                <Th>Strategies</Th>
                <Th>Cadence</Th>
                <Th>Last run</Th>
                <Th>Worker</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => {
                const id = Number(s.id)
                const tks = (s.tickers as string[]) ?? []
                const tfs = (s.timeframes as string[]) ?? []
                const strats = (s.strategies as string[]) ?? []
                const busy = runningId === id
                return (
                  <tr key={id}>
                    <Td className="font-medium">{String(s.name)}</Td>
                    <Td>{String(s.market)}</Td>
                    <Td className="max-w-[8rem] truncate text-xs" title={tks.join(', ')}>{tks.length}</Td>
                    <Td className="text-xs">{tfs.join(', ')}</Td>
                    <Td className="max-w-[8rem] truncate text-xs" title={strats.join(', ')}>{strats.length}</Td>
                    <Td className="text-xs">
                      {s.schedule_mode === 'daily_at' ? `Daily ${String(s.daily_time ?? '')}` : `${String(s.poll_minutes)}m`}
                    </Td>
                    <Td className="max-w-[14rem] truncate text-xs text-slate-400" title={String(s.last_status ?? '')}>
                      {String(s.last_status ?? '—')}
                    </Td>
                    <Td>
                      <button
                        type="button"
                        className="text-sm text-blue-400 hover:underline disabled:opacity-50"
                        disabled={busy || runMut.isPending}
                        onClick={() => enableMut.mutate({ id, enabled: !s.enabled })}
                      >
                        {s.enabled ? 'Stop' : 'Start'}
                      </button>
                    </Td>
                    <Td>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          title="Force run now"
                          disabled={busy || runMut.isPending}
                          onClick={() => runMut.mutate(id)}
                          className="text-emerald-400 hover:text-emerald-300 disabled:opacity-40"
                        >
                          {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                        </button>
                        <button type="button" title="Delete" onClick={() => deleteMut.mutate(id)} className="text-slate-500 hover:text-rose-400">
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </DataTable>
        )}
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-medium text-white">Actionable hits ({hits.length})</h3>
          {hits.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                disabled={selectedHits.length === 0 || deleteHitsMut.isPending}
                onClick={() => deleteHitsMut.mutate({ ids: selectedHits })}
              >
                <Trash2 size={14} className="mr-1.5" />
                Delete selected ({selectedHits.length})
              </Button>
              <Button
                variant="danger"
                disabled={deleteHitsMut.isPending}
                onClick={() => {
                  if (window.confirm('Delete ALL actionable hits for your account? This cannot be undone.')) {
                    deleteHitsMut.mutate({ delete_all: true })
                  }
                }}
              >
                Delete all
              </Button>
            </div>
          )}
        </div>
        {hits.length === 0 ? (
          <p className="text-sm text-slate-500">No hits yet. Force-run a schedule to populate.</p>
        ) : (
          <DataTable minWidth={760}>
            <thead>
              <tr>
                <Th>
                  <input
                    type="checkbox"
                    checked={allHitsSelected}
                    onChange={toggleAllHits}
                    aria-label="Select all hits"
                  />
                </Th>
                <Th>When</Th>
                <Th>Schedule</Th>
                <Th>Strategy</Th>
                <Th>Ticker</Th>
                <Th>TF</Th>
                <Th>Verdict</Th>
                <Th>Reasons</Th>
                <Th>Sent</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {hits.map((h) => {
                const id = Number(h.id)
                return (
                  <tr key={id}>
                    <Td>
                      <input
                        type="checkbox"
                        checked={selectedHits.includes(id)}
                        onChange={() => toggleHit(id)}
                        aria-label={`Select hit ${id}`}
                      />
                    </Td>
                    <Td className="text-xs">{String(h.created_at ?? '').replace('T', ' ').slice(0, 19)}</Td>
                    <Td>{String(h.schedule_name)}</Td>
                    <Td className="text-xs">{String(h.strategy_name)}</Td>
                    <Td className="font-medium">{String(h.ticker)}</Td>
                    <Td>{String(h.timeframe)}</Td>
                    <Td>{String(h.verdict)}</Td>
                    <Td className="max-w-xs truncate text-xs" title={((h.reasons as string[]) ?? []).join(' · ')}>
                      {((h.reasons as string[]) ?? []).join(' · ') || '—'}
                    </Td>
                    <Td className="text-xs">
                      {h.notified_telegram ? 'TG ' : ''}
                      {h.notified_email ? 'Email' : ''}
                      {!h.notified_telegram && !h.notified_email ? '—' : ''}
                    </Td>
                    <Td>
                      <button
                        type="button"
                        title="Delete hit"
                        disabled={deleteHitMut.isPending}
                        onClick={() => deleteHitMut.mutate(id)}
                        className="text-slate-500 hover:text-rose-400 disabled:opacity-40"
                      >
                        <Trash2 size={16} />
                      </button>
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </DataTable>
        )}
      </Card>
    </div>
  )
}

function NotifyConfigPanel() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [smtpHost, setSmtpHost] = useState('')
  const [smtpPort, setSmtpPort] = useState(587)
  const [smtpUser, setSmtpUser] = useState('')
  const [smtpPassword, setSmtpPassword] = useState('')
  const [smtpFrom, setSmtpFrom] = useState('')
  const [emailTo, setEmailTo] = useState('')
  const [tgToken, setTgToken] = useState('')
  const [tgChats, setTgChats] = useState('')

  const cfgQ = useQuery({
    queryKey: ['alert-notify-config'],
    queryFn: fetchAlertNotifyConfig,
  })

  const data = cfgQ.data as Record<string, unknown> | undefined
  useEffect(() => {
    if (!data) return
    setSmtpHost(String(data.smtp_host ?? ''))
    setSmtpPort(Number(data.smtp_port ?? 587))
    setSmtpUser(String(data.smtp_user ?? ''))
    setSmtpFrom(String(data.smtp_from ?? ''))
    setEmailTo(String(data.email_to ?? ''))
    setTgChats(String(data.telegram_chat_ids ?? ''))
  }, [data])

  const saveMut = useMutation({
    mutationFn: () =>
      saveAlertNotifyConfig({
        smtp_host: smtpHost || null,
        smtp_port: smtpPort,
        smtp_user: smtpUser || null,
        smtp_password: smtpPassword || null,
        smtp_from: smtpFrom || null,
        email_to: emailTo || null,
        telegram_bot_token: tgToken || null,
        telegram_chat_ids: tgChats || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-notify-config'] })
      qc.invalidateQueries({ queryKey: ['alerts-config'] })
      setSmtpPassword('')
      setTgToken('')
      setError('')
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  return (
    <Card>
      <h3 className="mb-2 font-medium text-white">SMTP & Telegram</h3>
      <p className="mb-4 text-xs text-slate-500">
        Leave blank to fall back to server `.env`. Multiple email TOs and Telegram chat IDs: comma-separated.
        {data?.smtp_password_set ? ' · SMTP password set' : ''}
        {data?.telegram_bot_token_set ? ' · Telegram token set' : ''}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="SMTP host">
          <Input value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} placeholder="smtp.gmail.com" />
        </FormField>
        <FormField label="SMTP port">
          <Input type="number" value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value))} />
        </FormField>
        <FormField label="SMTP user">
          <Input value={smtpUser} onChange={(e) => setSmtpUser(e.target.value)} />
        </FormField>
        <FormField label="SMTP password">
          <Input type="password" value={smtpPassword} onChange={(e) => setSmtpPassword(e.target.value)} placeholder={data?.smtp_password_set ? '(unchanged)' : ''} />
        </FormField>
        <FormField label="From email">
          <Input value={smtpFrom} onChange={(e) => setSmtpFrom(e.target.value)} />
        </FormField>
        <FormField label="To emails (comma-separated)">
          <Input value={emailTo} onChange={(e) => setEmailTo(e.target.value)} placeholder="a@x.com, b@y.com" />
        </FormField>
        <FormField label="Telegram bot token">
          <Input type="password" value={tgToken} onChange={(e) => setTgToken(e.target.value)} placeholder={data?.telegram_bot_token_set ? '(unchanged)' : ''} />
        </FormField>
        <FormField label="Telegram chat IDs (comma-separated)">
          <Input value={tgChats} onChange={(e) => setTgChats(e.target.value)} />
        </FormField>
      </div>
      <Button className="mt-4" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
        Save notify config
      </Button>
      {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      {data && (
        <p className="mt-3 text-xs text-slate-500">
          Effective: Telegram {data.telegram_configured ? 'ready' : 'not ready'} · Email {data.email_configured ? 'ready' : 'not ready'}
        </p>
      )}
    </Card>
  )
}

function CatalogGroupBlock({
  group,
  selected,
  onToggle,
}: {
  group: AlertScheduleCatalogGroup
  selected: string[]
  onToggle: (id: string) => void
}) {
  const [open, setOpen] = useState(group.id === 'scanner' || group.id === 'trading_hubs')
  const flatItems = [
    ...(group.items ?? []),
    ...(group.subgroups ?? []).flatMap((sg) => sg.items),
  ]
  const selCount = flatItems.filter((i) => selected.includes(i.id)).length

  return (
    <div className="rounded-md bg-slate-900/40">
      <button
        type="button"
        className="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-sm text-slate-200 hover:bg-slate-800/50"
        onClick={() => setOpen((v) => !v)}
      >
        <span>{group.label}</span>
        <span className="text-xs text-slate-500">
          {selCount ? `${selCount} selected · ` : ''}
          {open ? '▾' : '▸'}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-800/60 px-2.5 py-2">
          {(group.subgroups ?? []).map((sg) => (
            <div key={sg.id}>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">{sg.label}</p>
              <div className="flex flex-wrap gap-1.5">
                {sg.items.map((item) => (
                  <Chip
                    key={item.id}
                    selected={selected.includes(item.id)}
                    onClick={() => onToggle(item.id)}
                    title={item.runnable ? 'Force-run capable' : 'Catalog only — not executed yet'}
                  >
                    {item.label}{!item.runnable ? ' · later' : ''}
                  </Chip>
                ))}
              </div>
            </div>
          ))}
          {(group.items?.length ?? 0) > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {(group.items ?? []).map((item) => (
                <Chip
                  key={item.id}
                  selected={selected.includes(item.id)}
                  onClick={() => onToggle(item.id)}
                  title={item.runnable ? 'Force-run capable' : 'Catalog only — not executed yet'}
                >
                  {item.label}{!item.runnable ? ' · later' : ''}
                </Chip>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
