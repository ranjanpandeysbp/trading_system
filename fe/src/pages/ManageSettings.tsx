import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Database, Settings2, Wifi } from 'lucide-react'
import { getSettings, testProvider, updateSettings } from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'

const GROQ_MODELS = [
  'llama-3.3-70b-versatile',
  'llama-3.1-8b-instant',
  'llama3-70b-8192',
  'mixtral-8x7b-32768',
]

const GEMINI_MODELS = [
  'gemini-2.5-flash',
  'gemini-2.5-pro',
  'gemini-2.0-flash',
  'gemini-1.5-flash',
  'gemini-1.5-pro',
  'gemini-3.1-flash-lite',
]

const CLAUDE_MODELS = [
  'claude-sonnet-5',
  'claude-opus-4-1',
  'claude-sonnet-4-5',
  'claude-haiku-4-5',
]

const OPENAI_MODELS = [
  'gpt-5-nano',
  'gpt-5-mini',
  'gpt-5',
  'gpt-4.1',
  'gpt-4.1-mini',
  'gpt-4o',
  'gpt-4o-mini',
]

const DEFAULT_CLAUDE_ENDPOINT = 'https://atul-mjil3w7p-swedencentral.services.ai.azure.com/anthropic'
const DEFAULT_OPENAI_ENDPOINT = 'https://aiadvisorassis8258039388.services.ai.azure.com/openai/v1'

const MARKETS = [
  'Groww (India Stocks)',
  'US Stocks (Yahoo)',
  'CoinDCX Futures',
]

export default function ManageSettings() {
  const qc = useQueryClient()
  const { data: settings, isLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings })

  const [provider, setProvider] = useState('yfinance')
  const [growwToken, setGrowwToken] = useState('')
  const [growwExchange, setGrowwExchange] = useState('NSE')
  const [geminiKey, setGeminiKey] = useState('')
  const [groqKey, setGroqKey] = useState('')
  const [claudeKey, setClaudeKey] = useState('')
  const [openaiKey, setOpenaiKey] = useState('')
  const [youtubeKey, setYoutubeKey] = useState('')
  const [superinvestingToken, setSuperinvestingToken] = useState('')
  const [aiProvider, setAiProvider] = useState('Google Gemini')
  const [groqModel, setGroqModel] = useState(GROQ_MODELS[0])
  const [geminiModel, setGeminiModel] = useState(GEMINI_MODELS[0])
  const [claudeModel, setClaudeModel] = useState(CLAUDE_MODELS[0])
  const [claudeEndpoint, setClaudeEndpoint] = useState(DEFAULT_CLAUDE_ENDPOINT)
  const [openaiModel, setOpenaiModel] = useState(OPENAI_MODELS[0])
  const [openaiEndpoint, setOpenaiEndpoint] = useState(DEFAULT_OPENAI_ENDPOINT)
  const [defaultMarket, setDefaultMarket] = useState(MARKETS[0])
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
      setAiProvider(settings.ai_provider ?? 'Google Gemini')
      setGroqModel(settings.groq_model ?? GROQ_MODELS[0])
      setGeminiModel(settings.gemini_model ?? GEMINI_MODELS[0])
      setClaudeModel(settings.claude_model ?? CLAUDE_MODELS[0])
      setClaudeEndpoint(settings.claude_endpoint ?? DEFAULT_CLAUDE_ENDPOINT)
      setOpenaiModel(settings.openai_model ?? OPENAI_MODELS[0])
      setOpenaiEndpoint(settings.openai_endpoint ?? DEFAULT_OPENAI_ENDPOINT)
      setDefaultMarket(settings.default_market ?? MARKETS[0])
    }
  }, [settings])

  const saveMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['investing-agent-status'] })
      setMsg('Settings saved')
      setGrowwToken('')
      setGeminiKey('')
      setGroqKey('')
      setClaudeKey('')
      setOpenaiKey('')
      setYoutubeKey('')
      setSuperinvestingToken('')
    },
    onError: (e: Error) => setMsg(e.message),
  })
  const testMutation = useMutation({
    mutationFn: testProvider,
    onSuccess: (data) => setTestResult(data),
    onError: (e: Error) => setTestResult({ ok: false, error: e.message }),
  })

  const savePayload = () => ({
    data_provider: provider,
    ...(growwToken ? { groww_api_token: growwToken } : {}),
    groww_exchange: growwExchange,
    ...(geminiKey ? { gemini_api_key: geminiKey } : {}),
    ...(groqKey ? { groq_api_key: groqKey } : {}),
    ...(claudeKey ? { claude_api_key: claudeKey } : {}),
    ...(openaiKey ? { openai_api_key: openaiKey } : {}),
    ...(youtubeKey ? { youtube_api_key: youtubeKey } : {}),
    ...(superinvestingToken ? { superinvesting_token: superinvestingToken } : {}),
    ai_provider: aiProvider,
    groq_model: groqModel,
    gemini_model: geminiModel,
    claude_model: claudeModel,
    claude_endpoint: claudeEndpoint,
    openai_model: openaiModel,
    openai_endpoint: openaiEndpoint,
    default_market: defaultMarket,
    benchmark_ticker: benchmark,
    initial_capital: initialCapital,
    costs_pct: costsPct,
  })

  if (isLoading) return <Loading message="Loading settings..." />

  return (
    <div>
      <PageHeader
        title="Manage Settings"
        description="Data provider · Groww · Gemini · Groq · Claude · OpenAI · Investing Agent · paper trading defaults"
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

          <FormField label="Default market (India · US · Crypto)">
            <Select value={defaultMarket} onChange={(e) => setDefaultMarket(e.target.value)}>
              {MARKETS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </Select>
          </FormField>

          {provider === 'groww' && (
            <>
              <FormField label={`Groww Bearer Token ${settings?.groww_token_set ? '(saved — enter new to replace)' : '(optional)'}`}>
                <Input type="password" value={growwToken} onChange={(e) => setGrowwToken(e.target.value)} placeholder="Paste Groww API bearer token" />
              </FormField>
              <FormField label="Exchange">
                <Select value={growwExchange} onChange={(e) => setGrowwExchange(e.target.value)}>
                  <option value="NSE">NSE</option>
                  <option value="BSE">BSE</option>
                </Select>
              </FormField>
            </>
          )}

          <FormField label="Benchmark Ticker">
            <Input value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
          </FormField>

          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <Button className="w-full sm:w-auto" onClick={() => saveMutation.mutate(savePayload())} disabled={saveMutation.isPending}>
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
                ? `Provider OK — ${String(testResult.provider)}`
                : `Failed: ${String(testResult.error)}`}
            </Alert>
          )}
        </Card>

        <Card>
          <div className="mb-5 flex items-center gap-2">
            <Bot className="text-violet-400" size={20} />
            <h3 className="font-semibold text-white">AI Settings (Ask AI · AI View)</h3>
          </div>

          <FormField label="AI Provider">
            <Select value={aiProvider} onChange={(e) => setAiProvider(e.target.value)}>
              <option value="Google Gemini">Google Gemini</option>
              <option value="Groq (LLaMA)">Groq (LLaMA)</option>
              <option value="Claude (Azure)">Claude (Azure)</option>
              <option value="OpenAI (Azure)">OpenAI (Azure)</option>
              <option value="Investing Agent">Investing Agent</option>
            </Select>
          </FormField>

          <FormField label={`Gemini API Key ${settings?.gemini_token_set ? '(saved)' : ''}`}>
            <Input type="password" value={geminiKey} onChange={(e) => setGeminiKey(e.target.value)} placeholder="AIza…" />
          </FormField>

          <FormField label={`Groq API Key ${settings?.groq_token_set ? '(saved)' : ''}`}>
            <Input type="password" value={groqKey} onChange={(e) => setGroqKey(e.target.value)} placeholder="gsk_…" />
          </FormField>

          <FormField label={`Claude API Key (Azure Foundry) ${settings?.claude_token_set ? '(saved)' : ''}`}>
            <Input type="password" value={claudeKey} onChange={(e) => setClaudeKey(e.target.value)} placeholder="Azure Anthropic API key" autoComplete="off" />
          </FormField>

          <FormField label={`OpenAI API Key (Azure Foundry) ${settings?.openai_token_set ? '(saved)' : ''}`}>
            <Input type="password" value={openaiKey} onChange={(e) => setOpenaiKey(e.target.value)} placeholder="Azure OpenAI API key" autoComplete="off" />
          </FormField>

          <FormField
            label={`Investing Agent Token (SuperInvesting) ${settings?.superinvesting_token_set ? '(saved — enter new to replace)' : ''}`}
          >
            <Input
              type="password"
              value={superinvestingToken}
              onChange={(e) => setSuperinvestingToken(e.target.value)}
              placeholder="eyJhbGciOi… (Bearer JWT)"
              autoComplete="off"
            />
          </FormField>

          <FormField label={`YouTube Data API Key ${settings?.youtube_api_key_set ? '(saved)' : ''}`}>
            <Input type="password" value={youtubeKey} onChange={(e) => setYoutubeKey(e.target.value)} placeholder="AIza… (YouTube Data API v3)" />
          </FormField>

          {aiProvider === 'Groq (LLaMA)' ? (
            <FormField label="Groq Model">
              <Select value={groqModel} onChange={(e) => setGroqModel(e.target.value)}>
                {GROQ_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </FormField>
          ) : aiProvider === 'Claude (Azure)' ? (
            <>
              <FormField label="Claude Endpoint">
                <Input value={claudeEndpoint} onChange={(e) => setClaudeEndpoint(e.target.value)} placeholder={DEFAULT_CLAUDE_ENDPOINT} />
              </FormField>
              <FormField label="Claude Deployment / Model">
                <Select value={claudeModel} onChange={(e) => setClaudeModel(e.target.value)}>
                  {[claudeModel, ...CLAUDE_MODELS.filter((m) => m !== claudeModel)].map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </Select>
              </FormField>
              <p className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-slate-400">
                Uses Anthropic Foundry on Azure (`AnthropicFoundry` + `/anthropic` base URL). Deployment example: <code className="text-slate-300">claude-sonnet-5</code>.
              </p>
            </>
          ) : aiProvider === 'OpenAI (Azure)' ? (
            <>
              <FormField label="OpenAI Endpoint">
                <Input value={openaiEndpoint} onChange={(e) => setOpenaiEndpoint(e.target.value)} placeholder={DEFAULT_OPENAI_ENDPOINT} />
              </FormField>
              <FormField label="OpenAI Deployment / Model">
                <Select value={openaiModel} onChange={(e) => setOpenaiModel(e.target.value)}>
                  {[openaiModel, ...OPENAI_MODELS.filter((m) => m !== openaiModel)].map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </Select>
              </FormField>
              <p className="mb-4 rounded-xl border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-xs text-slate-400">
                Uses Azure AI Foundry OpenAI (`base_url` …`/openai/v1`, Responses API). Deployment example: <code className="text-slate-300">gpt-5-nano</code>.
              </p>
            </>
          ) : aiProvider === 'Investing Agent' ? (
            <p className="mb-4 rounded-xl border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-xs text-slate-400">
              Investing Agent uses SuperInvesting chat (screener + research tools). No model picker.
              Token is shared with the Investing Agent page. Ask AI may take 1–2 minutes. JWT expires ~every 3 days.
            </p>
          ) : (
            <FormField label="Gemini Model">
              <Select value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)}>
                {GEMINI_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </Select>
            </FormField>
          )}

          <p className="text-xs text-slate-500">
            Keys are stored in the app database (same as Groww token). Env fallbacks: GEMINI_API_KEY, GROQ_API_KEY, CLAUDE_API_KEY / ANTHROPIC_FOUNDRY_API_KEY, OPENAI_API_KEY, YOUTUBE_API_KEY, SUPERINVESTING_TOKEN.
          </p>

          <Button className="mt-4" onClick={() => saveMutation.mutate(savePayload())} disabled={saveMutation.isPending}>
            Save AI Settings
          </Button>
        </Card>

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
            <h3 className="font-semibold text-white">Migrated from truebacktesting</h3>
          </div>
          <ul className="space-y-2 text-sm text-slate-400">
            <li>Command Center · Market Pulse · TA screeners · Trading Hubs · ETF STF Shop</li>
            <li>India · US · Crypto markets · Ask AI on all scan sections</li>
            <li>Run <code className="text-slate-300">python scripts/migrate_full_tb.py</code> to copy remaining engines</li>
          </ul>
        </Card>
      </div>
    </div>
  )
}
