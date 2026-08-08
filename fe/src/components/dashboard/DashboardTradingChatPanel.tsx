import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Bot, BookOpen, MessageSquare, Send, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiErrorMessage, fetchAIConfig, runDashboardTradingChat } from '../../api/client'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../analysis/AnalysisBackground'
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
  'Which crypto moved a lot in 24h?',
  'Which stocks fallen most today?',
  'Which commodities / gold / silver moved sharply?',
  'Which stocks broke recent support?',
  'Which names broke resistance today?',
  'Analyze RELIANCE for swing — buy sell or wait?',
  'Should I long Bitcoin for intraday?',
]

function actionTone(action: string): string {
  const a = action.toUpperCase()
  if (a === 'BUY' || a === 'LONG') return 'text-emerald-300'
  if (a === 'SELL' || a === 'SHORT') return 'text-rose-300'
  return 'text-amber-200'
}

function assistantFromData(data: Row, q: string): ChatMsg {
  const picks = (data?.picks as Row[] | undefined) ?? []
  const ai = (data?.ai as Row | null | undefined) ?? null
  const ranking = (data?.strategy_ranking as Row[] | undefined) ?? []
  const selected = (data?.selected_strategies as Row[] | undefined) ?? []
  const enrichments = (data?.enrichments as Row[] | undefined) ?? []
  const hedgePairs = (data?.hedge_pairs as Row[] | undefined) ?? []
  const isDeep = Boolean(data?.deep_mode)
  const summary = String(data?.summary || '')
  const report = String(ai?.report || '')
  const err = data?.error ? String(data.error) : ''
  const enrichLines =
    !isDeep && enrichments.length
      ? [
          'Suitability enrichments:',
          ...enrichments.map((e) => {
            const label = String(e.label || e.id || 'desk')
            const why = e.why ? ` (${String(e.why)})` : ''
            const body = String(e.summary || e.error || '—')
            return `· ${label}${why}: ${body}`
          }),
        ].join('\n')
      : ''
  const hedgeLines =
    hedgePairs.length
      ? [
          'Intra-Hedging pairs (Trading Hub → Intraday):',
          ...hedgePairs.slice(0, 5).map((p) => {
            const longT = String(p.long_label || p.long_ticker || '—')
            const shortT = String(p.short_label || p.short_ticker || '—')
            const conf = p.confidence_pct != null ? `${p.confidence_pct}%` : '—'
            const spread = p.spread_pct != null ? `${p.spread_pct}%` : '—'
            return `· #${p.pair_rank ?? '?'} LONG ${longT} / SHORT ${shortT} · conf ${conf} · spread ${spread}`
          }),
        ].join('\n')
      : ''
  const text = err
    ? err
    : [
        isDeep && ranking.length ? 'Deep mode — strategies backtested & ranked, then live analysis.' : '',
        summary && `${isDeep ? 'Results' : 'Engine top picks'}:\n${summary}`,
        enrichLines,
        hedgeLines,
        report && `\nAI conclusion:\n${report}`,
      ]
        .filter(Boolean)
        .join('\n') || 'No picks returned.'
  return {
    role: 'assistant',
    text,
    picks,
    ai,
    ranking,
    selected,
    deepMode: isDeep,
    meta: {
      question: q,
      asset_class: data?.asset_class,
      style: data?.style,
      timeframe: data?.timeframe,
      mode: data?.mode,
      scanned: data?.scanned,
      disclaimer: data?.disclaimer,
      deep_mode: isDeep,
      backtest_period: data?.backtest_period,
      enrichments: enrichments.map((e) => e.label || e.id).filter(Boolean),
    },
  }
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
        'Ask what to buy or sell — or open questions like which stocks/crypto/commodities moved a lot in 24h, fallen most, or broke support/resistance. Standard: BB + confluence, suitability desks, and India Intra-Hedging (Trading Hub — query-adapted). Deep mode: backtest-ranked strategies + Strategies catalog how-tos. Use Run in background for long Deep scans. Conclusions use Manage → AI.',
    },
  ])

  const bg = useAnalysisBackground('trading_agent', 'trading_chat')
  const aiCfg = useQuery({ queryKey: ['ai-config'], queryFn: fetchAIConfig })
  const lastOpenedReportRef = useRef<number | null>(null)

  const chatPayload = (q: string) => ({
    message: q,
    asset_class: assetClass || undefined,
    style: style || undefined,
    deep_mode: deepMode,
  })

  const chatMut = useMutation({
    mutationFn: (q: string) => runDashboardTradingChat(chatPayload(q)),
    onSuccess: (data, q) => {
      setMessages((prev) => [...prev, { role: 'user', text: q }, assistantFromData(data as Row, q)])
      setMessage('')
      bg.setViewedReportId(null)
      lastOpenedReportRef.current = null
    },
    onError: (e, q) => {
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: q },
        { role: 'assistant', text: apiErrorMessage(e) },
      ])
    },
  })

  // When a saved background report is opened, show it in the chat transcript
  useEffect(() => {
    const payload = bg.viewedPayload as Row | undefined
    const rid = bg.viewedReportId
    if (!payload || rid == null || lastOpenedReportRef.current === rid) return
    lastOpenedReportRef.current = rid
    const q = String(
      payload.intent && (payload.intent as Row).raw_message
        ? (payload.intent as Row).raw_message
        : bg.viewedReportMeta?.name || 'Background report',
    )
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', text: `Opened saved report${bg.viewedReportMeta?.name ? `: ${bg.viewedReportMeta.name}` : ''}` },
      { role: 'user', text: q },
      assistantFromData(payload, q),
    ])
  }, [bg.viewedReportId, bg.viewedPayload, bg.viewedReportMeta?.name])

  const providerLabel = useMemo(() => {
    const c = aiCfg.data as Row | undefined
    if (!c) return 'AI: …'
    const ready = Boolean(c.ready)
    return `${ready ? 'AI ready' : 'AI not configured'} · ${String(c.provider ?? '—')} · ${String(c.model ?? '—')}`
  }, [aiCfg.data])

  const send = () => {
    const q = message.trim()
    if (!q || chatMut.isPending || bg.startPending) return
    if (bg.runInBackground) {
      if (!bg.bgReportName.trim()) {
        bg.startBackground(chatPayload(q), () => (q ? null : 'Enter a question'))
        return
      }
      const reportName = bg.bgReportName.trim()
      bg.startBackground(chatPayload(q), () => (q ? null : 'Enter a question'))
      setMessages((prev) => [
        ...prev,
        { role: 'user', text: q },
        {
          role: 'assistant',
          text: `Background run started (“${reportName}”). You can leave this page — open the saved report below when it finishes.`,
        },
      ])
      setMessage('')
      return
    }
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
            Buy/sell/wait ideas with %confidence, %SL, %TP — all eligible setups from the scan. Also
            understands open questions: biggest 24h movers, top gainers/losers, gold/silver/commodity
            moves, broken support or resistance. Standard:{' '}
            <strong className="text-white">BB Mean Reversion</strong> + confluence, then suitability desks
            as needed (Elliott Wave, Volume Spread next-candle, Advance/Decline, Comparative Strength,
            Oil·Dollar·Bond, Options Market Prediction) plus India{' '}
            <strong className="text-white">Trading Hub Intra-Hedging</strong> with params adapted from your
            question (TF, sector vs stock universe, max pairs, further-analysis). Deep mode: pick strategies →{' '}
            <strong className="text-white">backtest rank</strong> → Strategies catalog how-to → live scan →
            Manage AI (Deep also enriches mover/break screens with BB SL/TP when possible).
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
          disabled={chatMut.isPending || bg.startPending}
        />
        <span>
          <span className="font-semibold text-white">Deep mode</span>
          <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-400">
            Backtest strategies matched to your question, load Strategies catalog how-tos
            (from /strategies), live-analyze the best ones, then AI concludes. Slower (often several
            minutes).
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
            disabled={chatMut.isPending || bg.startPending}
          >
            {ex}
          </button>
        ))}
      </div>

      <AnalysisBackgroundControls
        bg={bg}
        placeholder={`Trading Agent · ${new Date().toLocaleDateString()}`}
        onStart={() => {
          const q = message.trim()
          if (!q) {
            bg.startBackground(chatPayload(''), () => 'Enter a question first')
            return
          }
          send()
        }}
      />
      <AnalysisBackgroundJobsAndReports bg={bg} />

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
                  <BookOpen size={11} /> Strategies catalog / how-to
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
                      <p className="mt-2 text-[11px] text-slate-600">No Strategies catalog excerpt for this id.</p>
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
                  ? 'Deep mode: backtesting strategies → Strategies catalog → live scan → Manage AI… (several minutes)'
                  : 'Scanning BB + confluence + suitability desks, then asking Manage AI…'
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
          disabled={chatMut.isPending || bg.startPending}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
      </FormField>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          onClick={send}
          disabled={
            !message.trim()
            || chatMut.isPending
            || bg.startPending
            || (bg.runInBackground && !bg.bgReportName.trim())
          }
        >
          <Send size={14} />{' '}
          {bg.runInBackground ? 'Start background' : deepMode ? 'Ask deep desk' : 'Ask desk'}
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
        (standard ~50 names; Deep live-scans ~20). Use <span className="text-slate-400">Run in background</span> for
        long Deep / movers scans — results auto-save under Saved reports.
      </p>
    </Card>
  )
}
