import { useCallback, useState } from 'react'

const STORAGE_KEY = 'trading.use_ai_trade_setup'

export function readUseAiTradeSetup(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function writeUseAiTradeSetup(on: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

/** Shared preference for AI-refined Conf % / SL % / TP % on trade setups. */
export function useTradeSetupAi() {
  const [useAi, setUseAiState] = useState<boolean>(() => readUseAiTradeSetup())

  const setUseAi = useCallback((on: boolean) => {
    setUseAiState(on)
    writeUseAiTradeSetup(on)
  }, [])

  return { useAi, setUseAi }
}

/** Checkbox shown next to scan/analyze actions wherever Conf/SL/TP trade setups are produced. */
export function UseAiCheckbox({
  checked,
  onChange,
  className = '',
}: {
  checked: boolean
  onChange: (next: boolean) => void
  className?: string
}) {
  return (
    <label
      className={`inline-flex max-w-xl cursor-pointer items-start gap-2 text-sm text-slate-300 ${className}`}
      title="When checked, the configured AI provider re-scores confidence, SL%, TP%, and reverse/continue odds after the rule-based scan."
    >
      <input
        type="checkbox"
        className="mt-0.5"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="font-medium text-slate-200">Use AI</span>
        <span className="text-slate-500">
          {' '}
          — refine Conf % · SL % · TP % (and reverse/continue odds) after the scan. Falls back to
          rule-based if no API key is set.
        </span>
      </span>
    </label>
  )
}
