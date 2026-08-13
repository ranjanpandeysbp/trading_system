import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type LayoutChromeContextValue = {
  /** When true, hide app sidebar + top ticker / header chrome (Chart Analyzer focus mode). */
  immersive: boolean
  setImmersive: (v: boolean) => void
  toggleImmersive: () => void
}

const LayoutChromeContext = createContext<LayoutChromeContextValue | null>(null)

export function LayoutChromeProvider({ children }: { children: ReactNode }) {
  const [immersive, setImmersiveState] = useState(false)

  const setImmersive = useCallback((v: boolean) => {
    setImmersiveState(v)
  }, [])

  const toggleImmersive = useCallback(() => {
    setImmersiveState((v) => !v)
  }, [])

  useEffect(() => {
    if (!immersive) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setImmersiveState(false)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [immersive])

  const value = useMemo(
    () => ({ immersive, setImmersive, toggleImmersive }),
    [immersive, setImmersive, toggleImmersive],
  )

  return <LayoutChromeContext.Provider value={value}>{children}</LayoutChromeContext.Provider>
}

export function useLayoutChrome() {
  const ctx = useContext(LayoutChromeContext)
  if (!ctx) {
    return {
      immersive: false,
      setImmersive: (_v: boolean) => {},
      toggleImmersive: () => {},
    }
  }
  return ctx
}
