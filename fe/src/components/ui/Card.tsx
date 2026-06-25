import { type ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  hover?: boolean
}

export function Card({ children, className = '', hover = false }: CardProps) {
  return (
    <div
      className={`rounded-2xl border border-slate-800/80 bg-slate-900/50 p-4 shadow-xl shadow-black/20 backdrop-blur-sm sm:p-5 ${
        hover ? 'transition-all duration-300 hover:border-slate-700 hover:bg-slate-900/80 hover:shadow-blue-500/5' : ''
      } ${className}`}
    >
      {children}
    </div>
  )
}
