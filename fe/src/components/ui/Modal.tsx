import { type ReactNode } from 'react'
import { createPortal } from 'react-dom'

// Rendered via a portal into document.body so this overlay is never subject to
// an ancestor's backdrop-blur/transform/filter — any of those create a new CSS
// containing block for `position: fixed` descendants, which silently traps a
// non-portaled modal inside that ancestor's box instead of the full viewport.
export function Modal({ onClose, children }: { onClose?: () => void; children: ReactNode }) {
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-md overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>,
    document.body,
  )
}
