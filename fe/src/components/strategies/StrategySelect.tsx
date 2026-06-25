import type { StrategyCategoryInfo, StrategyInfo } from '../../api/client'

const fieldClass =
  'w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 transition-colors focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20'

type Props = {
  value: string
  onChange: (id: string) => void
  categories?: StrategyCategoryInfo[]
  strategies?: StrategyInfo[]
  placeholder?: string
  className?: string
}

export function StrategySelect({
  value,
  onChange,
  categories,
  strategies,
  placeholder = 'Select strategy',
  className = fieldClass,
}: Props) {
  if (categories?.length) {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} className={className}>
        <option value="">{placeholder}</option>
        {categories.map((cat) => (
          <optgroup key={cat.id} label={`${cat.label} (${cat.timeframes.join(', ')})`}>
            {cat.strategies.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </optgroup>
        ))}
      </select>
    )
  }

  const grouped = (strategies ?? []).reduce<Record<string, StrategyInfo[]>>((acc, s) => {
    const key = s.category_label
    acc[key] = acc[key] ?? []
    acc[key].push(s)
    return acc
  }, {})

  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={className}>
      <option value="">{placeholder}</option>
      {Object.entries(grouped).map(([label, items]) => (
        <optgroup key={label} label={label}>
          {items.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}
