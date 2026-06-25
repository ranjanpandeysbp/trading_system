import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

export function AuthLayout({ children, title, subtitle }: { children: ReactNode; title: string; subtitle?: string }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-950 px-4 py-10">
      <div className="mb-8 text-center">
        <Link to="/" className="inline-flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-emerald-500 text-lg font-bold text-white shadow-lg shadow-blue-500/30">
            ₹
          </div>
          <div className="text-left">
            <p className="text-lg font-bold text-white">IST Paper</p>
            <p className="text-xs text-slate-500">Indian Equities Demo</p>
          </div>
        </Link>
        <h1 className="mt-6 text-2xl font-semibold text-white">{title}</h1>
        {subtitle && <p className="mt-2 text-sm text-slate-400">{subtitle}</p>}
      </div>
      <div className="w-full max-w-md">{children}</div>
    </div>
  )
}
