import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, Settings2, Wifi } from 'lucide-react'
import { getSettings, testProvider, updateSettings } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const modules = [
  'Data: yfinance / Groww providers (pluggable)',
  'Strategies: 15 rule-based (scalping / intraday / swing)',
  'Scanner: multi-ticker × strategy × timeframe',
  'Backtester: transparent signal evaluation',
  'Paper Trading: SQLite-backed virtual portfolio',
]

export default function ManageSettings() {
  const qc = useQueryClient()
  const { data: settings, isLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings })

  const [provider, setProvider] = useState('yfinance')
  const [growwToken, setGrowwToken] = useState('')
  const [growwExchange, setGrowwExchange] = useState('NSE')
  const [initialCapital, setInitialCapital] = useState(1000000)
  const [costsPct, setCostsPct] = useState(0.0008)
  const [benchmark, setBenchmark] = useState('^NSEI')
  const [msg, setMsg] = useState('')
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    if (settings) {
      setProvider(settings.data_provider)
      setGrowwExchange(settings.groww_exchange ?? 'NSE')
      setInitialCapital(settings.initial_capital)
      setCostsPct(settings.costs_pct)
      setBenchmark(settings.benchmark_ticker)
    }
  }, [settings])

  const saveMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['settings'] }); setMsg('Settings saved'); setGrowwToken('') },
    onError: (e: Error) => setMsg(e.message),
  })

  const testMutation = useMutation({
    mutationFn: testProvider,
    onSuccess: (data) => setTestResult(data),
    onError: (e: Error) => setTestResult({ ok: false, error: e.message }),
  })

  if (isLoading) return <Loading message="Loading settings..." />

  return (
    <div>
      <PageHeader
        title="Manage Settings"
        description="Configure data provider, API tokens, capital, and benchmark index"
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-5 flex items-center gap-2">
            <Settings2 className="text-blue-400" size={20} />
            <h3 className="font-semibold text-white">Data Provider</h3>
          </div>

          <FormField label="Provider">
            <Select value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="yfinance">yfinance (default, free)</option>
              <option value="groww">Groww (REST + charting, token optional)</option>
            </Select>
          </FormField>

          {provider === 'groww' && (
            <>
              <FormField label={`Groww Bearer Token ${settings?.groww_token_set ? '(saved — enter new to replace)' : '(optional)'}`}>
                <Input
                  type="password"
                  value={growwToken}
                  onChange={(e) => setGrowwToken(e.target.value)}
                  placeholder="Paste Groww API bearer token"
                />
                <p className="mt-1.5 text-xs text-slate-500">
                  Without token: public charting API. With token: authenticated REST + live quotes.
                </p>
              </FormField>
              <FormField label="Exchange">
                <Select value={growwExchange} onChange={(e) => setGrowwExchange(e.target.value)}>
                  <option value="NSE">NSE</option>
                  <option value="BSE">BSE</option>
                </Select>
              </FormField>
            </>
          )}

          <FormField label="Benchmark Ticker (for relative strength strategy)">
            <Input value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
          </FormField>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <Button
              className="w-full sm:w-auto"
              onClick={() => saveMutation.mutate({
                data_provider: provider,
                ...(growwToken ? { groww_api_token: growwToken } : {}),
                groww_exchange: growwExchange,
                benchmark_ticker: benchmark,
                initial_capital: initialCapital,
                costs_pct: costsPct,
              })}
              disabled={saveMutation.isPending}
            >
              Save Settings
            </Button>
            <Button className="w-full sm:w-auto" variant="secondary" onClick={() => testMutation.mutate()} disabled={testMutation.isPending}>
              <Wifi size={16} />
              Test Provider
            </Button>
          </div>

          {msg && <Alert type="success">{msg}</Alert>}
          {testResult && (
            <Alert type={testResult.ok ? 'success' : 'error'}>
              {testResult.ok
                ? `Provider OK — ${String(testResult.provider)} (${String(testResult.mode ?? 'connected')}, ${String(testResult.rows ?? '')} bars)`
                : `Failed: ${String(testResult.error)}`}
            </Alert>
          )}
        </Card>

        <div className="space-y-6">
          <Card>
            <h3 className="mb-5 font-semibold text-white">Trading Defaults</h3>
            <FormField label="Initial Paper Capital (₹)">
              <Input type="number" value={initialCapital} onChange={(e) => setInitialCapital(parseFloat(e.target.value))} />
            </FormField>
            <FormField label="Default Round-trip Cost %">
              <Input type="number" step="0.0001" value={costsPct} onChange={(e) => setCostsPct(parseFloat(e.target.value))} />
            </FormField>
          </Card>

          <Card>
            <div className="mb-4 flex items-center gap-2">
              <Database className="text-violet-400" size={20} />
              <h3 className="font-semibold text-white">Module Architecture</h3>
            </div>
            <ul className="space-y-2">
              {modules.map((item) => (
                <li key={item} className="flex items-start gap-2 text-sm text-slate-400">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                  {item}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  )
}
