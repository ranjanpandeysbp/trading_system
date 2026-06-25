export function Loading({ message = 'Loading...' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-blue-500" />
      <p className="text-sm">{message}</p>
    </div>
  )
}

export function Alert({ type, children }: { type: 'error' | 'success'; children: React.ReactNode }) {
  const styles = {
    error: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  }
  return (
    <div className={`mt-4 rounded-xl border px-4 py-3 text-sm ${styles[type]}`}>{children}</div>
  )
}

export function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
      <div
        className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-500"
        style={{ width: `${Math.min(100, value)}%` }}
      />
    </div>
  )
}
