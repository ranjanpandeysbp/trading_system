import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Bot, Crosshair, Send, Sparkles } from 'lucide-react'
import { apiErrorMessage, askAI } from '../../api/client'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { FormField, Textarea } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'
import { Badge } from '../ui/Badge'

type AiReport = {
  report: string
  verdict?: string | null
  confidence_pct?: number | null
  provider: string
  model: string
}

type Props = {
  context: string
  section?: string
  systemPrompt?: string
  disabled?: boolean
  className?: string
  /** Panel heading — use "AI View" for scan narrative analysis */
  title?: string
  /** Prefills the question box (and is sent if the user leaves it empty) */
  defaultQuestion?: string
  buttonLabel?: string
  /** Show institutional next-move predictor (default true) */
  showPredictNextMove?: boolean
}

export function AskAIPanel({
  context,
  section,
  systemPrompt,
  disabled,
  className = '',
  title = 'Ask AI',
  defaultQuestion = '',
  buttonLabel,
  showPredictNextMove = true,
}: Props) {
  const [question, setQuestion] = useState(defaultQuestion)
  const [viewReport, setViewReport] = useState<AiReport | null>(null)
  const [moveReport, setMoveReport] = useState<AiReport | null>(null)

  const viewMut = useMutation({
    mutationFn: () =>
      askAI({
        context,
        question: (question.trim() || defaultQuestion.trim()) || undefined,
        section,
        system_prompt: systemPrompt,
        mode: 'ask',
      }),
    onSuccess: (data) => setViewReport(data),
  })

  const predictMut = useMutation({
    mutationFn: () =>
      askAI({
        context,
        question:
          'As an expert institutional pro trader, predict the next possible move with % confidence using ONLY this result data.',
        section,
        mode: 'next_move',
      }),
    onSuccess: (data) => setMoveReport(data),
  })

  const canAsk = Boolean(context?.trim()) && !disabled
  const cta = buttonLabel || (title === 'AI View' ? 'Generate AI View' : 'Ask AI')
  const busy = viewMut.isPending || predictMut.isPending

  return (
    <Card className={`mt-6 ${className}`}>
      <div className="mb-4 flex items-center gap-2">
        {title === 'AI View' ? (
          <Sparkles className="text-violet-400" size={20} />
        ) : (
          <Bot className="text-violet-400" size={20} />
        )}
        <h3 className="font-semibold text-white">{title}</h3>
        {(viewReport || moveReport) && (
          <span className="text-xs text-slate-500">
            {(moveReport || viewReport)?.provider} · {(moveReport || viewReport)?.model}
          </span>
        )}
      </div>

      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        Uses your saved AI provider from Manage → AI Settings. Reads the scan numbers below and returns a
        plain-English verdict (BUY / SELL / AVOID) with levels and risks. Use{' '}
        <span className="text-slate-400">Predict Next Move</span> for an institutional desk-style directional
        call with explicit % confidence.
      </p>

      <FormField label="Optional question (or leave the default)">
        <Textarea
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={defaultQuestion || 'e.g. Is this a high-conviction long? What invalidates the setup?'}
        />
      </FormField>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => viewMut.mutate()} disabled={!canAsk || busy}>
          <Send size={16} />
          {viewMut.isPending ? 'Analyzing…' : cta}
        </Button>
        {showPredictNextMove && (
          <Button variant="secondary" onClick={() => predictMut.mutate()} disabled={!canAsk || busy}>
            <Crosshair size={16} />
            {predictMut.isPending ? 'Predicting…' : 'Predict Next Move'}
          </Button>
        )}
      </div>

      {!canAsk && (
        <p className="mt-2 text-sm text-slate-500">Run a scan first to populate context for {title}.</p>
      )}

      {viewMut.isError && <Alert type="error">{apiErrorMessage(viewMut.error)}</Alert>}
      {predictMut.isError && <Alert type="error">{apiErrorMessage(predictMut.error)}</Alert>}

      {busy && (
        <Loading
          message={
            predictMut.isPending
              ? 'Institutional next-move prediction… (may take 1–2 min)'
              : 'Calling AI provider… (Investing Agent may take 1–2 min)'
          }
        />
      )}

      {viewReport && !viewMut.isPending && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{title} report</p>
            {viewReport.verdict && <Badge action={viewReport.verdict} />}
          </div>
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl border border-slate-700/60 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">
            {viewReport.report}
          </pre>
        </div>
      )}

      {moveReport && !predictMut.isPending && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Next move prediction</p>
            {moveReport.verdict && <Badge action={moveReport.verdict} />}
            {moveReport.confidence_pct != null && Number.isFinite(Number(moveReport.confidence_pct)) && (
              <span className="inline-flex rounded-lg bg-amber-500/15 px-2.5 py-0.5 text-xs font-semibold tabular-nums text-amber-300 ring-1 ring-amber-500/30">
                {Math.round(Number(moveReport.confidence_pct))}% confidence
              </span>
            )}
          </div>
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl border border-amber-500/20 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">
            {moveReport.report}
          </pre>
        </div>
      )}
    </Card>
  )
}

/** Build a compact JSON context string for Ask AI / AI View from scan results. */
export function buildAskContext(label: string, data: unknown, maxLen = 12000): string {
  const body = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  const text = `## ${label}\n\n${body}`
  return text.length > maxLen ? text.slice(0, maxLen) + '\n…[truncated]' : text
}
