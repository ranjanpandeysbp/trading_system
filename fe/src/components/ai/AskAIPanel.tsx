import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Bot, Send, Sparkles } from 'lucide-react'
import { apiErrorMessage, askAI } from '../../api/client'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { FormField, Textarea } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'
import { Badge } from '../ui/Badge'

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
}: Props) {
  const [question, setQuestion] = useState(defaultQuestion)
  const [report, setReport] = useState<{ report: string; verdict?: string | null; provider: string; model: string } | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      askAI({
        context,
        question: (question.trim() || defaultQuestion.trim()) || undefined,
        section,
        system_prompt: systemPrompt,
      }),
    onSuccess: (data: { report: string; verdict?: string | null; provider: string; model: string }) =>
      setReport(data),
  })

  const canAsk = Boolean(context?.trim()) && !disabled
  const cta = buttonLabel || (title === 'AI View' ? 'Generate AI View' : 'Ask AI')

  return (
    <Card className={`mt-6 ${className}`}>
      <div className="mb-4 flex items-center gap-2">
        {title === 'AI View' ? (
          <Sparkles className="text-violet-400" size={20} />
        ) : (
          <Bot className="text-violet-400" size={20} />
        )}
        <h3 className="font-semibold text-white">{title}</h3>
        {report && (
          <span className="text-xs text-slate-500">
            {report.provider} · {report.model}
          </span>
        )}
      </div>

      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        Uses your saved AI provider from Manage → AI Settings. Reads the scan numbers below and returns a
        plain-English verdict (BUY / SELL / AVOID) with levels and risks.
      </p>

      <FormField label="Optional question (or leave the default)">
        <Textarea
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={defaultQuestion || 'e.g. Is this a high-conviction long? What invalidates the setup?'}
        />
      </FormField>

      <Button
        onClick={() => mutation.mutate()}
        disabled={!canAsk || mutation.isPending}
        className="mt-3"
      >
        <Send size={16} />
        {mutation.isPending ? 'Analyzing…' : cta}
      </Button>

      {!canAsk && (
        <p className="mt-2 text-sm text-slate-500">Run a scan first to populate context for {title}.</p>
      )}

      {mutation.isError && <Alert type="error">{apiErrorMessage(mutation.error)}</Alert>}

      {mutation.isPending && <Loading message="Calling AI provider… (Investing Agent may take 1–2 min)" />}

      {report && !mutation.isPending && (
        <div className="mt-4 space-y-3">
          {report.verdict && <Badge action={report.verdict} />}
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-xl border border-slate-700/60 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">
            {report.report}
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
