import {
  CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

export type SRChartBar = { time: string; open: number; high: number; low: number; close: number }
export type SRTrendlinePoint = { time: string; price: number }
export type SRTrendline = { type: 'ascending' | 'descending'; points: SRTrendlinePoint[] }
type Bar = SRChartBar
type Trendline = SRTrendline

function fmtTime(t: string) {
  // "2026-07-29 07:45:00" -> "Jul 29" (date-only ticks keep the axis readable
  // across both intraday and daily/weekly HTF bar spacing).
  const d = new Date(t.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return t
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function SupportResistanceChart({
  chartData, supportZone, resistanceZone, trendlines, lastClose,
}: {
  chartData: Bar[]
  supportZone: [number, number] | null
  resistanceZone: [number, number] | null
  trendlines: Trendline[]
  lastClose?: number | null
}) {
  if (!chartData?.length) return null

  const lows = chartData.map((b) => b.low)
  const highs = chartData.map((b) => b.high)
  const padding = (Math.max(...highs) - Math.min(...lows)) * 0.05 || 1
  const yMin = Math.min(...lows, ...(supportZone ?? []), ...(resistanceZone ?? [])) - padding
  const yMax = Math.max(...highs, ...(supportZone ?? []), ...(resistanceZone ?? [])) + padding

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="time" tickFormatter={fmtTime} tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={40} />
          <YAxis
            domain={[yMin, yMax]}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            width={64}
            tickFormatter={(v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
          />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: '#e2e8f0' }}
            labelFormatter={(t) => String(t)}
            formatter={(value, name) => [Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 }), String(name)]}
          />

          {supportZone && (
            <ReferenceArea
              y1={supportZone[0]} y2={supportZone[1]}
              fill="#10b981" fillOpacity={0.15} stroke="#10b981" strokeOpacity={0.4} strokeDasharray="3 3"
              label={{ value: 'Support', position: 'insideBottomLeft', fill: '#34d399', fontSize: 11 }}
            />
          )}
          {resistanceZone && (
            <ReferenceArea
              y1={resistanceZone[0]} y2={resistanceZone[1]}
              fill="#f43f5e" fillOpacity={0.15} stroke="#f43f5e" strokeOpacity={0.4} strokeDasharray="3 3"
              label={{ value: 'Resistance', position: 'insideTopLeft', fill: '#fb7185', fontSize: 11 }}
            />
          )}

          {trendlines.map((tl, i) => {
            const pts = tl.points
            if (pts.length < 2) return null
            const first = pts[0]
            const last = pts[pts.length - 1]
            return (
              <ReferenceLine
                key={`${tl.type}-${i}`}
                segment={[{ x: first.time, y: first.price }, { x: last.time, y: last.price }]}
                stroke={tl.type === 'ascending' ? '#38bdf8' : '#fb923c'}
                strokeDasharray="6 3"
                strokeWidth={1.5}
                ifOverflow="extendDomain"
              />
            )
          })}

          {lastClose != null && (
            <ReferenceLine
              y={lastClose}
              stroke="#e2e8f0"
              strokeDasharray="2 2"
              label={{ value: `Now ${lastClose.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`, position: 'insideTopRight', fill: '#e2e8f0', fontSize: 11 }}
            />
          )}

          <Line type="monotone" dataKey="close" stroke="#f8fafc" strokeWidth={1.5} dot={false} name="Close" />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-emerald-500/60" /> Support zone</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-rose-500/60" /> Resistance zone</span>
        {trendlines.some((t) => t.type === 'ascending') && (
          <span className="inline-flex items-center gap-1"><span className="h-0.5 w-3 bg-sky-400" /> Ascending trendline</span>
        )}
        {trendlines.some((t) => t.type === 'descending') && (
          <span className="inline-flex items-center gap-1"><span className="h-0.5 w-3 bg-orange-400" /> Descending trendline</span>
        )}
      </div>
    </div>
  )
}
