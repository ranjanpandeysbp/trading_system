import { useCallback, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import {
  apiErrorMessage,
  runChartCommentary,
  type ChartCommentaryBar,
  type ChartCommentaryResponse,
} from '../../api/client'
import { Button } from '../ui/Button'
import { useTradeSetupAi } from '../pro-trade/UseAiCheckbox'

export type CommentaryLevel = { label?: string; price?: number }
export type CommentaryDrawing = Record<string, unknown>

type Props = {
  bars: ChartCommentaryBar[]
  ticker?: string | null
  assetClass?: string | null
  indicators?: string[]
  levels?: CommentaryLevel[] | null
  drawings?: CommentaryDrawing[] | null
  timeframe?: string | null
  className?: string
}

function fmtPct(v: number | null | undefined) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${Number(v).toFixed(1)}%`
}

function serializeDrawings(drawings: CommentaryDrawing[] | null | undefined): CommentaryDrawing[] {
  if (!drawings?.length) return []
  return drawings.map((d) => {
    const kind = String(d.kind || d.type || '')
    const out: CommentaryDrawing = { kind }
    for (const k of ['price', 'x', 'x1', 'y1', 'x2', 'y2', 'extendLeft', 'extendRight']) {
      if (d[k] != null) out[k] = d[k]
    }
    return out
  })
}

/** Compact manual chart commentary — collapses until refreshed / opened. */
export function ChartCommentaryPanel({
  bars,
  ticker,
  assetClass,
  indicators = [],
  levels = [],
  drawings = [],
  timeframe,
  className = '',
}: Props) {
  const { useAi, setUseAi } = useTradeSetupAi()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<ChartCommentaryResponse | null>(null)
  const [open, setOpen] = useState(false)

  const refresh = useCallback(async () => {
    if (!bars?.length) {
      setError('No bars on the chart yet.')
      setOpen(true)
      return
    }
    setLoading(true)
    setError(null)
    setOpen(true)
    try {
      const payload = await runChartCommentary({
        bars: bars.map((b) => ({
          time: b.time,
          open: Number(b.open),
          high: Number(b.high),
          low: Number(b.low),
          close: Number(b.close),
          volume: b.volume ?? null,
        })),
        ticker: ticker || undefined,
        asset_class: assetClass || undefined,
        indicators: indicators || [],
        levels: (levels || [])
          .filter((l) => l && l.price != null)
          .map((l) => ({ label: l.label, price: Number(l.price) })),
        drawings: serializeDrawings(drawings),
        timeframe: timeframe || undefined,
        use_ai: useAi,
      })
      setData(payload)
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [bars, ticker, assetClass, indicators, levels, drawings, timeframe, useAi])

  const setup = data?.trade_setup
  const action = String(setup?.action || setup?.direction || 'WAIT').toUpperCase()
  const actionTone =
    action === 'BUY' || action === 'LONG'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : action === 'SELL' || action === 'SHORT'
        ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
        : 'border-slate-600/60 bg-slate-800/50 text-slate-300'

  return (
    <div className={`rounded-lg border border-slate-800/70 bg-slate-950/40 ${className}`}>
      <div className="flex flex-wrap items-center gap-2 px-2.5 py-1.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-200"
        >
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Commentary
        </button>
        {data?.source ? (
          <span className="rounded border border-slate-700/70 px-1.5 py-0.5 text-[10px] text-slate-500">
            {data.source === 'ai' ? 'AI' : 'Python TA'}
          </span>
        ) : null}
        {data && !open && setup ? (
          <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${actionTone}`}>
            {action} · Conf {fmtPct(setup.confidence_pct)}
          </span>
        ) : null}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label
            className="inline-flex cursor-pointer items-center gap-1 text-[11px] text-slate-500"
            title="AI commentary vs Python TA"
          >
            <input
              type="checkbox"
              className="accent-sky-500"
              checked={useAi}
              onChange={(e) => setUseAi(e.target.checked)}
            />
            Use AI
          </label>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={loading || !bars?.length}
            onClick={() => void refresh()}
            className="!px-2 !py-1"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            {loading ? 'Reading…' : 'Refresh'}
          </Button>
        </div>
      </div>

      {open && (
        <div className="space-y-2 border-t border-slate-800/60 px-2.5 py-2">
          {!data && !error && !loading && (
            <p className="text-[11px] text-slate-500">
              Refresh to read SMC / FVG / liquidity / RSI / S/R / patterns / BB·EMA at this moment.
            </p>
          )}
          {error && <p className="text-xs text-rose-400">{error}</p>}
          {data && (
            <>
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Now</p>
                <p className="text-sm leading-snug text-slate-200">{data.now || '—'}</p>
              </div>
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Next</p>
                <p className="text-sm leading-snug text-slate-300">{data.next || '—'}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-md border px-2 py-0.5 text-xs font-semibold ${actionTone}`}>
                  {action}
                </span>
                <span className="rounded-md border border-slate-700/80 px-2 py-0.5 text-xs text-slate-300">
                  Conf {fmtPct(setup?.confidence_pct)}
                </span>
                <span className="rounded-md border border-slate-700/80 px-2 py-0.5 text-xs text-slate-300">
                  SL {fmtPct(setup?.sl_pct)}
                </span>
                <span className="rounded-md border border-slate-700/80 px-2 py-0.5 text-xs text-slate-300">
                  TP {fmtPct(setup?.tp_pct)}
                </span>
                {setup?.plain_english || setup?.reason ? (
                  <span className="text-[11px] text-slate-500">
                    {setup.plain_english || setup.reason}
                  </span>
                ) : null}
              </div>
              {!!data.factors?.length && (
                <div className="flex flex-wrap gap-1">
                  {data.factors.slice(0, 12).map((f) => (
                    <span
                      key={f}
                      className="rounded border border-slate-800 bg-slate-900/80 px-1.5 py-0.5 text-[10px] text-slate-500"
                    >
                      {f}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
