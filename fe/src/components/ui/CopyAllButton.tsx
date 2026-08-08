import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Copy } from 'lucide-react'

/** Clipboard helper with textarea fallback for older browsers / insecure contexts. */
export async function copyTextToClipboard(text: string): Promise<void> {
  const value = (text ?? '').trim()
  if (!value) return
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const ta = document.createElement('textarea')
  ta.value = value
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
}

type CopyAllButtonProps = {
  text: string
  label?: string
  className?: string
  size?: 'sm' | 'md'
}

/** Compact "Copy all" control for guides, encyclopedia blocks, and how-to panels. */
export function CopyAllButton({
  text,
  label = 'Copy all',
  className = '',
  size = 'sm',
}: CopyAllButtonProps) {
  const [copied, setCopied] = useState(false)
  const disabled = !(text ?? '').trim()

  const onCopy = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (disabled) return
    try {
      await copyTextToClipboard(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  const pad = size === 'md' ? 'px-2.5 py-1.5 text-xs' : 'px-2 py-1 text-[11px]'

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onCopy}
      className={`inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-700/80 bg-slate-900/80 font-medium text-slate-300 transition-colors hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40 ${pad} ${className}`}
      title={disabled ? 'Nothing to copy' : 'Copy full text'}
    >
      {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
      {copied ? 'Copied' : label}
    </button>
  )
}

type CollapsibleGuideProps = {
  title: string
  defaultOpen?: boolean
  /** Plain text copied by Copy all (defaults to string children). */
  copyText?: string
  children: React.ReactNode
  className?: string
  bodyClassName?: string
}

/** Expandable strategy / how-to block with a Copy all button when open. */
export function CollapsibleGuide({
  title,
  defaultOpen = false,
  copyText,
  children,
  className = '',
  bodyClassName = 'border-t border-slate-800/60 px-3 py-3 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap',
}: CollapsibleGuideProps) {
  const [open, setOpen] = useState(defaultOpen)
  const resolvedCopy =
    copyText ?? (typeof children === 'string' || typeof children === 'number' ? String(children) : '')

  return (
    <div className={`rounded-lg border border-slate-800/60 bg-slate-900/40 ${className}`}>
      <div className="flex items-stretch gap-1">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2.5 text-left text-sm font-medium text-slate-200 hover:bg-slate-800/30"
        >
          <span className="shrink-0 text-slate-500">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
          <span className="min-w-0">{title}</span>
        </button>
        {resolvedCopy.trim() ? (
          <div className="flex items-center pr-2">
            <CopyAllButton text={resolvedCopy} />
          </div>
        ) : null}
      </div>
      {open && <div className={bodyClassName}>{children}</div>}
    </div>
  )
}

type CopyableDetailsProps = {
  summary: string
  text: string
  children?: React.ReactNode
  className?: string
}

/** `<details>` block used by the Strategy Lab encyclopedia, with Copy all. */
export function CopyableDetails({ summary, text, children, className = '' }: CopyableDetailsProps) {
  return (
    <details className={`rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2 ${className}`}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-medium text-slate-200 [&::-webkit-details-marker]:hidden">
        <span>{summary}</span>
        <CopyAllButton text={text} />
      </summary>
      {children ?? (
        <pre className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{text}</pre>
      )}
    </details>
  )
}

type HowToBoxProps = {
  copyText: string
  children: React.ReactNode
  className?: string
}

/** Wrapper for inline How-to panels (Oil-Dollar-Bond, A/D, etc.). */
export function HowToBox({ copyText, children, className = '' }: HowToBoxProps) {
  return (
    <div
      className={`mb-4 space-y-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs leading-relaxed text-slate-400 ${className}`}
    >
      <div className="mb-1 flex justify-end">
        <CopyAllButton text={copyText} />
      </div>
      {children}
    </div>
  )
}
