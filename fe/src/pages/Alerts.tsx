import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  apiErrorMessage,
  createAlertMonitor,
  deleteAlertMonitor,
  fetchAlertMonitors,
  fetchAlertsConfig,
  pollAlerts,
  toggleAlertMonitor,
} from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert } from '../components/ui/Feedback'
import { DataTable, SortableTh, Td, Th, useSort } from '../components/ui/Table'

const DEFAULT_INDICATORS = [{ type: 'rsi', period: 14 }, { type: 'ema', period: 20 }]
const DEFAULT_ENTRY = [{ left: 'rsi_14', op: '<', right_type: 'value', right_val: '35' }]

export default function Alerts() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [name, setName] = useState('RSI oversold alert')
  const [ticker, setTicker] = useState('RELIANCE')
  const [timeframe, setTimeframe] = useState('1d')
  const [pollMinutes, setPollMinutes] = useState(15)

  const configQuery = useQuery({ queryKey: ['alerts-config'], queryFn: fetchAlertsConfig })
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

  const config = configQuery.data as Record<string, unknown> | undefined
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
    <div>
      <PageHeader
        title="Strategy Alerts"
        description="Monitor entry rules on a schedule · Telegram / email when setup activates"
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
            <Input
              type="number"
              min={1}
              value={pollMinutes}
              onChange={(e) => setPollMinutes(Number(e.target.value))}
            />
          </FormField>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Default strategy: RSI &lt; 35 with EMA(20). Configure Telegram/email in Manage settings / env.
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
            <Button
              variant="secondary"
              onClick={() => pollMut.mutate(false)}
              disabled={pollMut.isPending}
            >
              <RefreshCw size={14} className="mr-1.5" />
              Poll due
            </Button>
            <Button
              variant="secondary"
              onClick={() => pollMut.mutate(true)}
              disabled={pollMut.isPending}
            >
              Force poll all
            </Button>
          </div>
        </div>

        {monitors.length === 0 ? (
          <p className="text-sm text-slate-500">No monitors yet. Create one above.</p>
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
                      onClick={() =>
                        toggleMut.mutate({ id: Number(m.id), enabled: !m.enabled })
                      }
                      className="text-sm text-blue-400 hover:underline"
                    >
                      {m.enabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </Td>
                  <Td>
                    <button
                      type="button"
                      aria-label="Delete monitor"
                      onClick={() => deleteMut.mutate(Number(m.id))}
                      className="text-slate-500 hover:text-rose-400"
                    >
                      <Trash2 size={16} />
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}

        {pollMut.data && (
          <pre className="mt-4 max-h-48 overflow-auto rounded-lg bg-slate-900/60 p-3 text-xs text-slate-400">
            {JSON.stringify(pollMut.data, null, 2)}
          </pre>
        )}
      </Card>
    </div>
  )
}
