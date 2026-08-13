import { useState } from 'react'
import { Chip } from '../ui/Chip'

/** Toggle visibility of automatically computed support / resistance overlays. */
export function useAutoSrVisible(defaultOn = true) {
  const [showSr, setShowSr] = useState(defaultOn)
  return {
    showSr,
    setShowSr,
    toggleSr: () => setShowSr((v) => !v),
  }
}

export function ChartSrToggle({
  showSr,
  onToggle,
  disabled,
}: {
  showSr: boolean
  onToggle: () => void
  disabled?: boolean
}) {
  return (
    <Chip
      selected={showSr}
      onClick={onToggle}
      title={
        showSr
          ? 'Hide automatic support & resistance lines'
          : 'Show automatic support & resistance lines'
      }
    >
      <span className={disabled ? 'opacity-40' : undefined}>
        {showSr ? 'S/R on' : 'S/R off'}
      </span>
    </Chip>
  )
}
