import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { apiErrorMessage, runWorkflowEvaluate } from '../../api/client'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { FormField } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'
import { Badge } from '../ui/Badge'
import { TickerAutosuggest } from '../ui/TickerAutosuggest'

export type PlaybookMarketId = 'india' | 'us' | 'crypto' | 'commodities'

const DEFAULT_TICKERS: Record<PlaybookMarketId, { index: string; stock: string }> = {
  india: { index: 'NIFTY', stock: 'RELIANCE' },
  us: { index: 'SPY', stock: 'AAPL' },
  crypto: { index: 'BTC', stock: 'ETH' },
  commodities: { index: 'GC=F', stock: 'CL=F' },
}

function marketAssetClass(market: PlaybookMarketId): 'india' | 'us' | 'crypto' | 'commodity' {
  return market === 'commodities' ? 'commodity' : market
}

function tone(bias: string): 'BUY' | 'SELL' | 'HOLD' {
  const b = (bias || '').toUpperCase()
  if (b.includes('BUY') || b === 'LONG') return 'BUY'
  if (b.includes('SELL') || b === 'SHORT') return 'SELL'
  return 'HOLD'
}

type EvalStep = {
  id?: string
  title?: string
  status?: string
  bias?: string
  summary?: string
  score?: number | null
}

type EvalResult = {
  error?: string
  market?: string
  mode?: string
  tickers?: string[]
  steps?: EvalStep[]
  overall?: {
    action?: string
    confidence_pct?: number
    plain_english?: string
    buy_votes?: number
    sell_votes?: number
    error_steps?: number
  }
  disclaimer?: string
}

type Props = {
  market: PlaybookMarketId
  title?: string
  description?: string
  loadingMessage?: string
  className?: string
}

/** Index / Stock evaluate with ticker autosuggest — shared by Workflow, Best Strategies, Institutional Accuracy. */
export function PlaybookEvaluatePanel({
  market,
  title = 'Evaluate full workflow',
  description = 'Runs every desk in this playbook for Index or Stock and returns a confluence stance.',
  loadingMessage = 'Running playbook desks in parallel…',
  className = 'mt-4',
}: Props) {
  const defaults = DEFAULT_TICKERS[market]
  const assetClass = marketAssetClass(market)
  const [indexTicker, setIndexTicker] = useState(defaults.index)
  const [stockTicker, setStockTicker] = useState(defaults.stock)
  const [activeMode, setActiveMode] = useState<'index' | 'stock' | null>(null)

  const mut = useMutation({
    mutationFn: (mode: 'index' | 'stock') => {
      const raw = mode === 'index' ? indexTicker : stockTicker
      const tickers = raw
        .split(/[,\s]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean)
      return runWorkflowEvaluate({ market, mode, tickers })
    },
  })

  const data = mut.data as EvalResult | undefined
  const overall = data?.overall
  const steps = useMemo(() => data?.steps ?? [], [data])

  const run = (mode: 'index' | 'stock') => {
    setActiveMode(mode)
    mut.mutate(mode)
  }

  return (
    <Card className={className}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <p className="mt-1 text-xs text-slate-400">{description}</p>
        </div>
        <Play size={16} className="text-sky-300" />
      </div>

      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <FormField label="Index symbol(s)">
          <TickerAutosuggest
            value={indexTicker}
            onChange={setIndexTicker}
            assetClass={assetClass}
            placeholder={defaults.index}
            multi
          />
        </FormField>
        <FormField label="Stock / alt symbol(s)">
          <TickerAutosuggest
            value={stockTicker}
            onChange={setStockTicker}
            assetClass={assetClass}
            placeholder={defaults.stock}
            multi
          />
        </FormField>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={() => run('index')} disabled={mut.isPending || !indexTicker.trim()}>
          {mut.isPending && activeMode === 'index' ? 'Evaluating index…' : 'Evaluate Index'}
        </Button>
        <Button
          variant="secondary"
          onClick={() => run('stock')}
          disabled={mut.isPending || !stockTicker.trim()}
        >
          {mut.isPending && activeMode === 'stock' ? 'Evaluating stock…' : 'Evaluate Stock'}
        </Button>
      </div>

      {mut.isPending && (
        <div className="mt-3">
          <Loading message={loadingMessage} />
        </div>
      )}
      {mut.isError && (
        <div className="mt-3">
          <Alert type="error">{apiErrorMessage(mut.error)}</Alert>
        </div>
      )}

      {data && !mut.isPending && (
        <div className="mt-4 space-y-3">
          {data.error ? (
            <Alert type="error">{data.error}</Alert>
          ) : (
            <>
              <div className="rounded-xl border border-sky-500/20 bg-sky-500/5 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-slate-400">
                    {String(data.mode).toUpperCase()} · {(data.tickers || []).join(', ')}
                  </span>
                  <Badge action={tone(String(overall?.action || 'WAIT'))} />
                  {overall?.confidence_pct != null && (
                    <span className="text-xs text-slate-400">{String(overall.confidence_pct)}% conf</span>
                  )}
                </div>
                <p className="mt-2 text-sm text-slate-200">{overall?.plain_english || '—'}</p>
                <p className="mt-1 text-[11px] text-slate-500">
                  Votes BUY {overall?.buy_votes ?? 0} · SELL {overall?.sell_votes ?? 0} · errors{' '}
                  {overall?.error_steps ?? 0}
                </p>
              </div>

              <div className="space-y-2">
                {steps.map((s) => (
                  <div
                    key={String(s.id || s.title)}
                    className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-medium text-slate-200">{String(s.title)}</span>
                      <Badge action={tone(String(s.bias || 'WAIT'))} />
                      {s.status === 'error' && (
                        <span className="text-[10px] text-rose-300">error</span>
                      )}
                      {s.score != null && (
                        <span className="text-[10px] text-slate-500">{String(s.score)}%</span>
                      )}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-slate-400">{String(s.summary || '—')}</p>
                  </div>
                ))}
              </div>
              {data.disclaimer ? (
                <p className="text-[11px] text-slate-600">{String(data.disclaimer)}</p>
              ) : null}
            </>
          )}
        </div>
      )}
    </Card>
  )
}
