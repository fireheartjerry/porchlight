import clsx from 'clsx'
import { Check, Info, TriangleAlert, X } from 'lucide-react'
import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { ToastContext, type Toast, type ToastApi, type ToastTone } from './toast-context'

const TONE_STYLES: Record<ToastTone, string> = {
  quiet: 'border-white/12 bg-porch-800/95 text-cream',
  good: 'border-sage/30 bg-porch-800/95 text-cream',
  warn: 'border-lamp/35 bg-porch-800/95 text-cream',
  bad: 'border-ember/35 bg-porch-800/95 text-cream',
}

const TONE_ICONS: Record<ToastTone, ReactNode> = {
  quiet: <Info className="h-4 w-4 text-cream-faint" aria-hidden />,
  good: <Check className="h-4 w-4 text-sage" aria-hidden />,
  warn: <TriangleAlert className="h-4 w-4 text-lamp-glow" aria-hidden />,
  bad: <TriangleAlert className="h-4 w-4 text-ember" aria-hidden />,
}

const LIFETIME_MS = 5200

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const push = useCallback<ToastApi['push']>(
    ({ title, description, tone = 'quiet' }) => {
      const id = nextId.current
      nextId.current += 1
      setToasts((current) => [...current.slice(-3), { id, title, description, tone }])
      window.setTimeout(() => dismiss(id), LIFETIME_MS)
      return id
    },
    [dismiss],
  )

  const value = useMemo<ToastApi>(() => ({ toasts, push, dismiss }), [toasts, push, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Top right, under the sticky header: the Inbox composer's send button owns the
          bottom-right corner, and a toast landing on it hid the thing you just clicked. */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="false"
        aria-label="Notifications"
        className="pointer-events-none fixed inset-x-0 top-0 z-50 flex flex-col items-center gap-2 px-4 pt-[5.25rem] sm:items-end sm:px-6"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={clsx(
              'pointer-events-auto flex w-full max-w-sm animate-slide-in items-start gap-3 rounded-xl border px-3.5 py-3 shadow-[0_20px_50px_-24px_rgba(0,0,0,1)] backdrop-blur-md',
              TONE_STYLES[toast.tone],
            )}
          >
            <span className="mt-0.5">{TONE_ICONS[toast.tone]}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[0.85rem] font-medium leading-snug">{toast.title}</p>
              {toast.description && (
                <p className="mt-0.5 text-[0.78rem] leading-snug text-cream-faint">{toast.description}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss notification"
              className="-mr-1 -mt-0.5 rounded p-1 text-cream-faint transition-colors hover:text-cream"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
