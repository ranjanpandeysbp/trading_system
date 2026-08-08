import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Bot, BookOpen, MessageSquare, Send, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiErrorMessage, fetchAIConfig, runDashboardTradingChat } from '../../api/client'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { FormField, Select, Textarea } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'

type Row = Record<string, unknown>

type ChatMsg = {
  role: 'user' | 'assistant'
  text: string
  picks?: Row[]
  ai?: Row | null
  meta?: Row | null
  ranking?: Row[]
  selected?: Row[]
  deepMode?: boolean
}

const ASSET_OPTIONS = [
  { value: '', label: 'Auto-detect' },
  { value: 'india', label: 'India stocks' },
  { value: 'us', label: 'US stocks' },
  { value: 'crypto', label: 'Crypto' },
  { value: 'commodity', label: 'Commodities' },
]

const STYLE_OPTIONS = [
  { value: '', label: 'Auto-detect' },
  { value: 'scalping', label: 'Scalping' },
  { value: 'intraday', label: 'Intraday' },
  { value: 'swing', label: 'Swing' },
  { value: 'investing', label: 'Investing' },
]

const EXAMPLES = [
  'Which Indian stocks to buy now for intraday?',
  'Top crypto to scalp today',
  'What US stocks for swing trade?',
  'Which commodities can I buy for investing?',
  'Analyze RELIANCE for swing — buy sell or wait?',
  'Should I long Bitcoin for intraday?',
]

function actionTone(action: string): string {
  const a = action.toUpperCase()
  if (a === 'BUY' || a === 'LONG') return 'text-emerald-300'
  if (a === 'SELL' || a === 'SHORT') return 'text-rose-300'
  return 'text-amber-200'
}

export function DashboardTradingChatPanel() {
  const [message, setMessage] = useState('')
  const [assetClass, setAssetClass] = useState('')
  const [style, setStyle] = useState('')
  const [deepMode, setDeepMode] = useState(false)
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      role: 'assistant',
      text:
        'Ask what to buy or sell now — India / US / crypto / commodities — for scalping, intraday, swing, or investing. Name a ticker for a single read. Standard mode: BB Mean Reversion + confluence. Enable Deep mode to backtest-rank strategies for your question, pull encyclopedia how-tos, live-scan the winners, then conclude with Manage → AI.',
    },
  ])

  const aiCfg = useQuery({ queryKey: ['ai-config'], queryFn: fetchAIConfig })

  const chatMut = useMutation({
    mutationFn: (q: string) =>
      runDashboardTradingChat({
        message: q,
        asset_class: assetClass || undefined,
        style: style || undefined,
        deep_mode: deepMode,
      }),
    onSuccess: (data, q) => {
      const picks = (data?.picks as Row[] | undefined) ?? []
      const ai = (data?.ai as Row | null | undefined) ?? null
      const ranking = (data?.strategy_ranking as Row[] | undefined) ?? []
      const selected = (data?.selected_strategies as Row[] | undefined) ?? []
      const isDeep = Boolean(data?.deep_mode)
      const summary = String(data?.summary || '')
      const report = String(ai?.report || '')
      const err = data?.error ? String(data.error) : ''
      const text = err
        ? err
        : [
            isDeep && ranking.length ? 'Deep mode — strategies backtested & ranked, then live analysis.' : '',
            summary && `${isDeep ? 'Results' : 'Engine top picks'}:\n${summary}`,
            report && `\nAI conclusion:\n${report}`,
          ]
            .filter(Boolean)
            .join('\n') || 'No picks returned.'
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: q },
        {
          role: 'assistant',
          text,
          picks,
          ai,
          ranking,
          selected,
          deepMode: isDeep,
          meta: {
            asset_class: data?.asset_class,
            style: data?.style,
            timeframe: data?.timeframe,
            mode: data?.mode,
            scanned: data?.scanned,
            disclaimer: data?.disclaimer,
            deep_mode: isDeep,
            backtest_period: data?.backtest_period,
          },
        },
      ])
      setMessage('')
    },
    onError: (e, q) => {
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: q },
        { role: 'assistant', text: apiErrorMessage(e) },
      ])
    },
  })

  const providerLabel = useMemo(() => {
    const c = aiCfg.data as Row | undefined
    if (!c) return 'AI: …'
    const ready = Boolean(c.ready)
    return `${ready ? 'AI ready' : 'AI not configured'} · ${String(c.provider ?? '—')} · ${String(c.model ?? '—')}`
  }, [aiCfg.data])

  const send = () => {
    const q = message.trim()
    if (!q || chatMut.isPending) return
    chatMut.mutate(q)
  }

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-sm font-semibold text-white">
            <MessageSquare size={16} className="text-violet-400" />
            Trading Chat
          </p>
          <p className="mt-1 text-sm leading-relaxed text-slate-300">
            Buy/sell/wait ideas with %confidence, %SL, %TP — all eligible setups from the scan (not capped at
            10). Standard: <strong className="text-white">BB Mean Reversion</strong> + confluence. Deep mode:
            pick strategies for the question → <strong className="text-white">backtest rank</strong> →
            encyclopedia how-to → live scan → Manage AI conclusion.
          </p>
          <p className="mt-1 text-[11px] text-slate-500">{providerLabel}</p>
        </div>
        <Bot size={18} className="shrink-0 text-violet-400/80" />
      </div>

      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <FormField label="Asset class (optional)">
          <Select value={assetClass} onChange={(e) => setAssetClass(e.target.value)}>
            {ASSET_OPTIONS.map((o) => (
              <option key={o.value || 'auto'} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Style (optional)">
          <Select value={style} onChange={(e) => setStyle(e.target.value)}>
            {STYLE_OPTIONS.map((o) => (
              <option key={o.value || 'auto-s'} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <label className="mb-3 flex cursor-pointer items-start gap-2 rounded-lg border border-slate-700/70 bg-slate-900/40 px-3 py-2.5 text-sm text-slate-200">
        <input
          type="checkbox"
          className="mt-0.5 rounded border-slate-600"
          checked={deepMode}
          onChange={(e) => setDeepMode(e.target.checked)}
          disabled={chatMut.isPending}
        />
        <span>
          <span className="font-semibold text-white">Deep mode</span>
          <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-400">
            Backtest strategies matched to your question, load encyclopedia guides, live-analyze the best ones,
            then AI concludes. Slower (often several minutes).
          </span>
        </span>
      </label>

      <div className="mb-3 flex flex-wrap gap-1.5">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            className="rounded-lg border border-slate-700/70 bg-slate-900/50 px-2 py-1 text-[10px] text-slate-400 hover:border-violet-500/40 hover:text-violet-200"
            onClick={() => setMessage(ex)}
            disabled={chatMut.isPending}
          >
            {ex}
          </button>
        ))}
      </div>

      <div className="mb-3 max-h-[520px] space-y-3 overflow-y-auto rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
        {messages.map((m, i) => (
          <div
            key={`${m.role}-${i}`}
            className={`rounded-lg px-3 py-2 text-sm ${
              m.role === 'user'
                ? 'ml-6 bg-blue-600/20 text-blue-50'
                : 'mr-4 border border-slate-800/80 bg-slate-900/50 text-slate-200'
            }`}
          >
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              {m.role === 'user' ? 'You' : m.deepMode ? 'Desk · Deep' : 'Desk'}
            </p>
            <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed">{m.text}</pre>

            {m.ranking && m.ranking.length > 0 && (
              <div className="mt-3 overflow-x-auto">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-violet-300/90">
                  Strategy ranking (backtest)
                </p>
                <table className="w-full min-w-[560px] text-left text-[11px]">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="py-1 pr-2">#</th>
                      <th className="py-1 pr-2">Strategy</th>
                      <th className="py-1 pr-2">Score</th>
                      <th className="py-1 pr-2">Ret%</th>
                      <th className="py-1 pr-2">Win%</th>
                      <th className="py-1 pr-2">Sharpe</th>
                      <th className="py-1">Trades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.ranking.map((r) => (
                      <tr key={`${r.rank}-${r.strategy_id}`} className="border-t border-slate-800/60">
                        <td className="py-1.5 pr-2 tabular-nums text-slate-500">{String(r.rank ?? '')}</td>
                        <td className="py-1.5 pr-2 font-medium text-white">{String(r.strategy_label ?? r.strategy_id)}</td>
                        <td className="py-1.5 pr-2 tabular-nums">{r.avg_rank_score != null ? Number(r.avg_rank_score).toFixed(2) : '—'}</td>
                        <td className="py-1.5 pr-2 tabular-nums">{r.avg_return_pct != null ? `${r.avg_return_pct}%` : '—'}</td>
                        <td className="py-1.5 pr-2 tabular-nums">{r.avg_win_rate_pct != null ? `${r.avg_win_rate_pct}%` : '—'}</td>
                        <td className="py-1.5 pr-2 tabular-nums">{r.avg_sharpe != null ? String(r.avg_sharpe) : '—'}</td>
                        <td className="py-1.5 tabular-nums">{String(r.num_trades ?? '—')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {m.selected && m.selected.length > 0 && (
              <div className="mt-3 space-y-2">
                <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-sky-300/90">
                  <BookOpen size={11} /> Encyclopedia / how-to
                </p>
                {m.selected.map((s) => (
                  <details
                    key={String(s.strategy_id)}
                    className="rounded-lg border border-slate-800/80 bg-slate-950/50 px-2.5 py-2"
                  >
                    <summary className="cursor-pointer text-[12px] font-medium text-white">
                      {String(s.strategy_label ?? s.strategy_id)}
                      {s.summary ? (
                        <span className="ml-2 font-normal text-slate-500">— {String(s.summary).slice(0, 80)}</span>
                      ) : null}
                    </summary>
                    {Array.isArray(s.entry_rules) && s.entry_rules.length > 0 && (
                      <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[11px] text-slate-400">
                        {(s.entry_rules as unknown[]).slice(0, 4).map((rule, idx) => (
                          <li key={idx}>{String(rule)}</li>
                        ))}
                      </ul>
                    )}
                    {s.guide_excerpt ? (
                      <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap font-sans text-[11px] leading-relaxed text-slate-400">
                        {String(s.guide_excerpt)}
                      </pre>
                    ) : (
                      <p className="mt-2 text-[11px] text-slate-600">No encyclopedia excerpt for this id.</p>
                    )}
                  </details>
                ))}
              </div>
            )}

            {m.picks && m.picks.length > 0 && (
              <div className="mt-3 overflow-x-auto">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-300/80">
                  Live picks
                </p>
                <table className="w-full min-w-[720px] text-left text-[11px]">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="py-1 pr-2">#</th>
                      <th className="py-1 pr-2">Ticker</th>
                      <th className="py-1 pr-2">Action</th>
                      <th className="py-1 pr-2">Side</th>
                      <th className="py-1 pr-2">Conf%</th>
                      <th className="py-1 pr-2">SL%</th>
                      <th className="py-1 pr-2">TP%</th>
                      <th className="py-1 pr-2">Strategy</th>
                      <th className="py-1">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.picks.map((p) => (
                      <tr key={`${p.rank}-${p.ticker}-${p.strategy_id ?? ''}`} className="border-t border-slate-800/60">
                        <td className="py-1.5 pr-2 tabular-nums text-slate-500">{String(p.rank ?? '')}</td>
                        <td className="py-1.5 pr-2 font-semibold text-white">{String(p.ticker ?? '')}</td>
                        <td className="py-1.5 pr-2">
                          <Badge action={String(p.action ?? 'WAIT')} />
                        </td>
                        <td className={`py-1.5 pr-2 font-medium ${actionTone(String(p.side ?? ''))}`}>
                          {String(p.side ?? 'WAIT')}
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums">
                          {p.confidence_pct != null ? `${Math.round(Number(p.confidence_pct))}%` : '—'}
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums">
                          {p.sl_pct != null ? `${Number(p.sl_pct)}%` : '—'}
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums">
                          {p.tp_pct != null ? `${Number(p.tp_pct)}%` : '—'}
                        </td>
                        <td className="py-1.5 pr-2 text-slate-400">
                          {String(p.strategy_label ?? p.strategy_id ?? 'BB')}
                        </td>
                        <td className="py-1.5 text-slate-400">{String(p.reason ?? '').slice(0, 120)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {m.ai && (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
                <Sparkles size={12} className="text-violet-400" />
                {m.ai.verdict != null && <Badge action={String(m.ai.verdict)} />}
                {m.ai.confidence_pct != null && (
                  <span>~{Math.round(Number(m.ai.confidence_pct))}% AI confidence</span>
                )}
                <span>
                  {String(m.ai.provider ?? '')} · {String(m.ai.model ?? '')}
                </span>
              </div>
            )}

            {m.meta && (
              <p className="mt-2 text-[10px] text-slate-600">
                {m.deepMode ? 'deep · ' : ''}
                {String(m.meta.mode ?? '')} · {String(m.meta.asset_class ?? '')} ·{' '}
                {String(m.meta.style ?? '')} · TF {String(m.meta.timeframe ?? '')}
                {m.meta.backtest_period ? ` · BT ${String(m.meta.backtest_period)}` : ''} · scanned{' '}
                {String(m.meta.scanned ?? '')}
              </p>
            )}
          </div>
        ))}
        {chatMut.isPending && (
          <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 px-3 py-3">
            <Loading
              message={
                deepMode
                  ? 'Deep mode: backtesting strategies → encyclopedia → live scan → Manage AI… (several minutes)'
                  : 'Scanning BB + confluence for all eligible setups, then asking Manage AI…'
              }
            />
          </div>
        )}
      </div>

      <FormField label="Your question">
        <Textarea
          rows={3}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="e.g. Which crypto to buy for scalping? or Analyze NVDA swing"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
      </FormField>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" onClick={send} disabled={!message.trim() || chatMut.isPending}>
          <Send size={14} /> {deepMode ? 'Ask deep desk' : 'Ask desk'}
        </Button>
        {aiCfg.data && !(aiCfg.data as Row).ready && (
          <Alert type="error">
            Set an AI provider in{' '}
            <Link to="/settings" className="underline">
              Manage → AI Settings
            </Link>{' '}
            for the written conclusion (engine picks still run).
          </Alert>
        )}
      </div>

      <p className="mt-3 text-[10px] leading-relaxed text-slate-600">
        Research / education only — not financial advice. Returns every eligible BUY/SELL from the scan universe
        (standard ~50 names; Deep live-scans ~20). No artificial top-10 cut.
      </p>
    </Card>
  )
}
