import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Bot, Loader2, Search, Send, Sparkles } from 'lucide-react'
import {
  apiErrorMessage,
  fetchInvestingAgentStatus,
  fetchInvestingAgentStockCard,
  streamInvestingAgentChat,
  type InvestingAgentStreamEvent,
} from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { FormField, Textarea } from '../components/ui/Form'
import { TickerAutosuggest } from '../components/ui/TickerAutosuggest'
import { Alert, Loading } from '../components/ui/Feedback'

const QUICK_PROMPTS = [
  'nifty analysis',
  'What is the market outlook for next week?',
  'Analyze RELIANCE for long-term investing',
  'Sector rotation in Indian markets right now',
]

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inlineFormat(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em class="text-slate-200">$1</em>')
    .replace(/`([^`]+)`/g, '<code class="rounded bg-slate-800 px-1 text-emerald-300">$1</code>')
}

type ParsedBlock =
  | { type: 'si-card'; title: string; description: string; symbols: string[] }
  | { type: 'heading'; level: number; text: string }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; items: string[] }
  | { type: 'p'; text: string }
  | { type: 'hr' }

/** Parse SuperInvesting + markdown answer into structured blocks. */
function parseAgentAnswer(raw: string): ParsedBlock[] {
  let text = raw.replace(/\r\n/g, '\n').trim()

  // Normalize ```list ... ``` fences that wrap <m>/<d>/<s>
  text = text.replace(/```list\s*([\s\S]*?)```/gi, (_m, inner: string) => {
    const title = (inner.match(/<m>([\s\S]*?)<\/m>/i)?.[1] || '').trim()
    const desc = (inner.match(/<d>([\s\S]*?)<\/d>/i)?.[1] || '').trim()
    const syms = (inner.match(/<s>([\s\S]*?)<\/s>/i)?.[1] || '').trim()
    return `\n\n@@SICARD@@${JSON.stringify({ title, desc, syms})}@@END@@\n\n`
  })

  // Also catch bare <m>/<d>/<s> clusters outside fences
  text = text.replace(
    /<m>([\s\S]*?)<\/m>\s*<d>([\s\S]*?)<\/d>\s*<s>([\s\S]*?)<\/s>/gi,
    (_m, title: string, desc: string, syms: string) =>
      `\n\n@@SICARD@@${JSON.stringify({ title: title.trim(), desc: desc.trim(), syms: syms.trim() })}@@END@@\n\n`,
  )

  // Strip leftover tags if any
  text = text.replace(/<\/?[mds]>/gi, '')

  const lines = text.split('\n')
  const blocks: ParsedBlock[] = []
  let i = 0

  const isTableSep = (line: string) => /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line.trim())
  const isTableRow = (line: string) => line.trim().startsWith('|') && line.includes('|')
  const splitRow = (line: string) =>
    line
      .trim()
      .replace(/^\|/, '')
      .replace(/\|$/, '')
      .split('|')
      .map((c) => c.trim())

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i++
      continue
    }

    if (trimmed.startsWith('@@SICARD@@') && trimmed.endsWith('@@END@@')) {
      try {
        const json = trimmed.slice('@@SICARD@@'.length, -'@@END@@'.length)
        const { title, desc, syms } = JSON.parse(json) as { title: string; desc: string; syms: string }
        blocks.push({
          type: 'si-card',
          title: title || 'Analysis',
          description: desc || '',
          symbols: (syms || '')
            .split(/[,;\s]+/)
            .map((s) => s.trim())
            .filter(Boolean),
        })
      } catch {
        /* skip */
      }
      i++
      continue
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] })
      i++
      continue
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push({ type: 'hr' })
      i++
      continue
    }

    // Plain title lines (SuperInvesting often omits #)
    const nextNonEmpty = (() => {
      for (let j = i + 1; j < lines.length; j++) {
        if (lines[j].trim()) return lines[j].trim()
      }
      return ''
    })()
    const looksLikeTitle =
      trimmed.length < 100 &&
      !/[.!?]$/.test(trimmed) &&
      !trimmed.includes('|') &&
      !/^[-*•]\s+/.test(trimmed) &&
      !/^\d+[.)]\s+/.test(trimmed) &&
      Boolean(nextNonEmpty) &&
      (isTableRow(nextNonEmpty) ||
        /^[-*•]\s+/.test(nextNonEmpty) ||
        /^\d+[.)]\s+/.test(nextNonEmpty) ||
        nextNonEmpty.length > trimmed.length ||
        /^#{1,3}\s+/.test(nextNonEmpty) ||
        lines[i + 1]?.trim() === '')
    if (
      looksLikeTitle &&
      (lines[i + 1]?.trim() === '' || nextNonEmpty.length > trimmed.length + 20)
    ) {
      blocks.push({ type: 'heading', level: 2, text: trimmed })
      i++
      continue
    }

    if (isTableRow(trimmed) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const headers = splitRow(trimmed)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && isTableRow(lines[i].trim())) {
        rows.push(splitRow(lines[i]))
        i++
      }
      blocks.push({ type: 'table', headers, rows })
      continue
    }

    if (/^[-*•]\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ''))
        i++
      }
      blocks.push({ type: 'ul', items })
      continue
    }

    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^\d+[.)]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+[.)]\s+/, ''))
        i++
      }
      blocks.push({ type: 'ol', items })
      continue
    }

    // Paragraph: gather consecutive non-empty non-special lines
    const para: string[] = [trimmed]
    i++
    while (i < lines.length) {
      const n = lines[i].trim()
      if (!n) break
      if (n.startsWith('@@SICARD@@')) break
      if (/^#{1,3}\s+/.test(n)) break
      if (isTableRow(n)) break
      if (/^[-*•]\s+/.test(n)) break
      if (/^\d+[.)]\s+/.test(n)) break
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(n)) break
      para.push(n)
      i++
    }
    blocks.push({ type: 'p', text: para.join(' ') })
  }

  return blocks
}

function AgentAnswerView({ markdown }: { markdown: string }) {
  const blocks = parseAgentAnswer(markdown)

  return (
    <div className="space-y-4 text-sm leading-relaxed">
      {blocks.map((b, idx) => {
        if (b.type === 'si-card') {
          return (
            <div
              key={idx}
              className="overflow-hidden rounded-xl border border-sky-500/25 bg-gradient-to-br from-sky-500/10 to-slate-900/40"
            >
              <div className="border-b border-sky-500/20 px-4 py-3">
                <h3 className="text-base font-semibold text-white">{b.title}</h3>
                {b.description && <p className="mt-1 text-sm text-slate-400">{b.description}</p>}
              </div>
              {b.symbols.length > 0 && (
                <div className="flex flex-wrap gap-1.5 px-4 py-3">
                  {b.symbols.map((sym) => (
                    <span
                      key={sym}
                      className="rounded-md border border-slate-600/60 bg-slate-800/70 px-2 py-0.5 font-mono text-xs text-sky-300"
                    >
                      {sym}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        }
        if (b.type === 'heading') {
          const cls =
            b.level === 1
              ? 'text-lg font-bold text-white'
              : b.level === 2
                ? 'text-base font-semibold text-white'
                : 'text-sm font-semibold text-slate-200'
          return (
            <h3 key={idx} className={`${cls} mt-2`} dangerouslySetInnerHTML={{ __html: inlineFormat(b.text) }} />
          )
        }
        if (b.type === 'table') {
          return (
            <div key={idx} className="overflow-x-auto rounded-xl border border-slate-700/60">
              <table className="min-w-full border-collapse text-left text-xs sm:text-sm">
                <thead>
                  <tr className="border-b border-slate-700/80 bg-slate-800/60">
                    {b.headers.map((h, hi) => (
                      <th
                        key={hi}
                        className="whitespace-nowrap px-3 py-2.5 font-semibold text-slate-300"
                        dangerouslySetInnerHTML={{ __html: inlineFormat(h) }}
                      />
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, ri) => (
                    <tr key={ri} className="border-b border-slate-800/80 odd:bg-slate-900/40 even:bg-slate-950/30">
                      {row.map((cell, ci) => (
                        <td
                          key={ci}
                          className="px-3 py-2 align-top text-slate-300"
                          dangerouslySetInnerHTML={{ __html: inlineFormat(cell) }}
                        />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        if (b.type === 'ul') {
          return (
            <ul key={idx} className="list-disc space-y-1.5 pl-5 text-slate-300">
              {b.items.map((item, ii) => (
                <li key={ii} dangerouslySetInnerHTML={{ __html: inlineFormat(item) }} />
              ))}
            </ul>
          )
        }
        if (b.type === 'ol') {
          return (
            <ol key={idx} className="list-decimal space-y-1.5 pl-5 text-slate-300">
              {b.items.map((item, ii) => (
                <li key={ii} dangerouslySetInnerHTML={{ __html: inlineFormat(item) }} />
              ))}
            </ol>
          )
        }
        if (b.type === 'hr') {
          return <hr key={idx} className="border-slate-800" />
        }
        return (
          <p key={idx} className="text-slate-300" dangerouslySetInnerHTML={{ __html: inlineFormat(b.text) }} />
        )
      })}
    </div>
  )
}

type StockCardData = {
  name?: string
  currentPrice?: number
  marketCapitalization?: number
  industry?: string
  priceToEarning?: number
  returnOver3years?: number
  currentChangePercent?: number
  score?: string | number
  labels?: {
    labels?: {
      Negative?: string | null
      Positive?: string | null
      sectorRanking?: string | number | null
      personaRanking?: string | number | null
    }
  }
}

function fmtNum(n: number | undefined | null, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—'
  return n.toLocaleString('en-IN', { maximumFractionDigits: digits })
}

function fmtPct(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function scoreTone(score: number): string {
  if (score >= 70) return 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
  if (score >= 45) return 'border-amber-500/40 bg-amber-500/15 text-amber-300'
  return 'border-rose-500/40 bg-rose-500/15 text-rose-300'
}

function StockScorecardView({ data, symbol }: { data: StockCardData; symbol: string }) {
  const scoreNum = Number(data.score)
  const hasScore = !Number.isNaN(scoreNum)
  const change = data.currentChangePercent
  const changeUp = change != null && change >= 0
  const labels = data.labels?.labels

  const metrics: { label: string; value: string; tone?: string }[] = [
    { label: 'P/E', value: fmtNum(data.priceToEarning) },
    { label: 'MCap (Cr)', value: fmtNum(data.marketCapitalization, 0) },
    {
      label: '3Y return',
      value: fmtPct(data.returnOver3years),
      tone:
        data.returnOver3years == null
          ? undefined
          : data.returnOver3years >= 0
            ? 'text-emerald-400'
            : 'text-rose-400',
    },
  ]

  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900/60">
      <div className="flex items-start justify-between gap-3 border-b border-slate-800/80 px-4 py-3">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wider text-slate-500">{symbol}</p>
          <h4 className="truncate text-base font-semibold text-white">{data.name || symbol}</h4>
          {data.industry && <p className="mt-0.5 truncate text-xs text-slate-500">{data.industry}</p>}
        </div>
        {hasScore && (
          <div
            className={`flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-xl border ${scoreTone(scoreNum)}`}
            title="Score"
          >
            <span className="text-[9px] uppercase tracking-wide opacity-70">Score</span>
            <span className="text-lg font-bold leading-none tabular-nums">{scoreNum}</span>
          </div>
        )}
      </div>

      <div className="px-4 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums text-white">₹{fmtNum(data.currentPrice, 2)}</span>
          {change != null && (
            <span className={`text-sm font-medium tabular-nums ${changeUp ? 'text-emerald-400' : 'text-rose-400'}`}>
              {fmtPct(change)}
            </span>
          )}
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          {metrics.map((m) => (
            <div key={m.label} className="rounded-lg bg-slate-950/50 px-2 py-2">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">{m.label}</p>
              <p className={`mt-0.5 text-sm font-semibold tabular-nums ${m.tone ?? 'text-slate-200'}`}>{m.value}</p>
            </div>
          ))}
        </div>

        {(labels?.Positive || labels?.Negative) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {labels.Positive && (
              <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">
                + {labels.Positive}
              </span>
            )}
            {labels.Negative && (
              <span className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-300">
                − {labels.Negative}
              </span>
            )}
          </div>
        )}

        {(labels?.sectorRanking != null || labels?.personaRanking != null) && (
          <div className="mt-3 flex gap-4 text-xs text-slate-500">
            {labels.sectorRanking != null && <span>Sector rank: {String(labels.sectorRanking)}</span>}
            {labels.personaRanking != null && <span>Persona rank: {String(labels.personaRanking)}</span>}
          </div>
        )}
      </div>
    </div>
  )
}

export default function InvestingAgent() {
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['investing-agent-status'],
    queryFn: fetchInvestingAgentStatus,
  })

  const [prompt, setPrompt] = useState('nifty analysis')
  const [statusLine, setStatusLine] = useState('')
  const [liveText, setLiveText] = useState('')
  const [reasoning, setReasoning] = useState('')
  const [tools, setTools] = useState<string[]>([])
  const [answer, setAnswer] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [showReasoning, setShowReasoning] = useState(false)
  const [stockSymbol, setStockSymbol] = useState('')
  const [stockCard, setStockCard] = useState<StockCardData | null>(null)
  const [stockError, setStockError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const answerRef = useRef<HTMLDivElement>(null)

  const tokenSet = Boolean(status?.token_set)

  useEffect(() => {
    if (answer || liveText) {
      answerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [answer, liveText])

  const stockMut = useMutation({
    mutationFn: (symbol: string) => fetchInvestingAgentStockCard(symbol),
    onSuccess: (data) => {
      setStockCard(data as StockCardData)
      setStockError('')
    },
    onError: (e) => {
      setStockCard(null)
      setStockError(apiErrorMessage(e))
    },
  })

  const handleStreamEvent = (event: InvestingAgentStreamEvent) => {
    if (event.kind === 'status') {
      setStatusLine(event.message || event.type || 'Working…')
      return
    }
    if (event.kind === 'conversation') {
      setConversationId(event.id)
      setStatusLine(`Conversation ${event.id.slice(0, 8)}…`)
      return
    }
    if (event.kind === 'reasoning') {
      setReasoning((prev) => prev + event.text)
      return
    }
    if (event.kind === 'tool') {
      const name = event.tool?.trim()
      if (name) setTools((prev) => (prev.includes(name) ? prev : [...prev, name]))
      setStatusLine(name ? `Tool: ${name}` : 'Running tools…')
      return
    }
    if (event.kind === 'text') {
      setLiveText((prev) => prev + event.text)
      return
    }
    if (event.kind === 'done') {
      setAnswer(event.answer || '')
      setConversationId(event.conversation_id)
      if (event.reasoning) setReasoning(event.reasoning)
      if (event.tools?.length) setTools(event.tools)
      setStatusLine('Done')
      setLiveText('')
      return
    }
    if (event.kind === 'error') {
      setError(event.message)
      setStatusLine('')
    }
  }

  const runChat = async () => {
    const message = prompt.trim()
    if (!message || !tokenSet || streaming) return
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setStreaming(true)
    setError('')
    setAnswer('')
    setLiveText('')
    setReasoning('')
    setTools([])
    setConversationId(null)
    setStatusLine('Starting…')
    try {
      await streamInvestingAgentChat(message, handleStreamEvent, ac.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError(e instanceof Error ? e.message : 'Chat failed')
      }
    } finally {
      setStreaming(false)
    }
  }

  const stopChat = () => {
    abortRef.current?.abort()
    setStreaming(false)
    setStatusLine('Stopped')
  }

  const displayMd = answer || liveText

  return (
    <div>
      <PageHeader
        title="Investing Agent"
        description="Chat with SuperInvesting for index narratives (e.g. nifty analysis) and stock scorecards. Token is configured under Manage."
      />

      {!tokenSet && !statusLoading && (
        <div className="mb-4">
          <Alert type="error">
            Investing Agent token is not set. Add it under Manage → AI Settings.
          </Alert>
        </div>
      )}
      {statusLoading && (
        <div className="mb-4">
          <Loading message="Checking token status…" />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <Card>
            <div className="mb-4 flex items-center gap-2">
              <Bot className="text-sky-400" size={20} />
              <h3 className="font-semibold text-white">Chat analysis</h3>
              <span className="text-xs text-slate-500">Index questions use chat — not stock card</span>
            </div>

            <div className="mb-3 flex flex-wrap gap-2">
              {QUICK_PROMPTS.map((q) => (
                <button
                  key={q}
                  type="button"
                  disabled={streaming}
                  onClick={() => setPrompt(q)}
                  className="rounded-lg border border-slate-700/70 bg-slate-800/40 px-2.5 py-1 text-xs text-slate-300 transition hover:border-sky-500/40 hover:text-sky-300 disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>

            <FormField label="Prompt">
              <Textarea
                rows={3}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="nifty analysis"
                disabled={streaming}
              />
            </FormField>

            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void runChat()} disabled={!tokenSet || !prompt.trim() || streaming}>
                {streaming ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                {streaming ? 'Analyzing…' : 'Ask Investing Agent'}
              </Button>
              {streaming && (
                <Button variant="secondary" onClick={stopChat}>
                  Stop
                </Button>
              )}
            </div>

            {(statusLine || tools.length > 0) && (
              <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-slate-400">
                {streaming && <Loader2 size={14} className="animate-spin text-sky-400" />}
                {statusLine && <span>{statusLine}</span>}
                {tools.map((t) => (
                  <span
                    key={t}
                    className="rounded-md border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-xs text-violet-300"
                  >
                    {t}
                  </span>
                ))}
                {conversationId && (
                  <span className="font-mono text-xs text-slate-600">id {conversationId}</span>
                )}
              </div>
            )}

            {error && <Alert type="error">{error}</Alert>}

            {reasoning && (
              <div className="mt-4">
                <button
                  type="button"
                  className="text-xs text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
                  onClick={() => setShowReasoning((v) => !v)}
                >
                  {showReasoning ? 'Hide reasoning' : 'Show reasoning'}
                </button>
                {showReasoning && (
                  <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-500">
                    {reasoning}
                  </pre>
                )}
              </div>
            )}

            {displayMd && (
              <div
                ref={answerRef}
                className="mt-4 max-h-[640px] overflow-auto rounded-xl border border-slate-700/60 bg-slate-900/60 p-4"
              >
                <div className="mb-3 flex items-center gap-1.5 text-xs text-slate-500">
                  <Sparkles size={12} />
                  {answer ? 'Final answer' : 'Streaming…'}
                </div>
                <AgentAnswerView markdown={displayMd} />
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <div className="mb-3 flex items-center gap-2">
              <Search className="text-emerald-400" size={18} />
              <h3 className="font-semibold text-white">Stock scorecard</h3>
            </div>
            <p className="mb-3 text-xs text-slate-500">
              Use stock symbols only (e.g. RELIANCE). <strong className="text-slate-400">NIFTY is not a stock</strong> —
              ask via chat instead.
            </p>
            <FormField label="Symbol">
              <TickerAutosuggest
                value={stockSymbol}
                onChange={setStockSymbol}
                assetClass="india"
                placeholder="e.g. RELIANCE"
                className={!tokenSet || stockMut.isPending ? 'pointer-events-none opacity-50' : ''}
              />
            </FormField>
            <Button
              variant="secondary"
              size="sm"
              disabled={!tokenSet || !stockSymbol.trim() || stockMut.isPending}
              onClick={() => stockMut.mutate(stockSymbol.trim())}
            >
              {stockMut.isPending ? 'Loading…' : 'Fetch card'}
            </Button>
            {stockError && <Alert type="error">{stockError}</Alert>}
            {stockCard && <StockScorecardView data={stockCard} symbol={stockSymbol.trim() || '—'} />}
          </Card>
        </div>
      </div>
    </div>
  )
}
