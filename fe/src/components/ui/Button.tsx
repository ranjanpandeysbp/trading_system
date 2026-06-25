import { type ReactNode } from 'react'

const variants = {
  primary: 'bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-lg shadow-blue-500/25 hover:from-blue-500 hover:to-blue-400',
  secondary: 'border border-slate-700/80 bg-slate-800/60 text-slate-200 hover:border-slate-600 hover:bg-slate-800',
  danger: 'border border-rose-500/40 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20',
  ghost: 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200',
}

const sizes = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2.5 text-sm',
  lg: 'px-5 py-3 text-sm',
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants
  size?: keyof typeof sizes
  children: ReactNode
}

export function Button({ variant = 'primary', size = 'md', className = '', children, ...props }: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
