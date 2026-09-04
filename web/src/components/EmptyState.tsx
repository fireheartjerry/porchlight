import clsx from 'clsx'
import type { ReactNode } from 'react'
import { Lantern } from './Lantern'

interface EmptyStateProps {
  title: string
  body?: ReactNode
  /** Defaults to a dim lantern. */
  illustration?: ReactNode
  action?: ReactNode
  className?: string
  compact?: boolean
}

export function EmptyState({ title, body, illustration, action, className, compact }: EmptyStateProps) {
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 px-6 py-10' : 'gap-3.5 px-8 py-16',
        className,
      )}
    >
      <div className="opacity-70">
        {illustration ?? <Lantern lit={false} halo={false} size={compact ? 40 : 64} title="" />}
      </div>
      <h3 className={clsx('text-balance text-cream', compact ? 'text-base' : 'text-xl')}>{title}</h3>
      {body && (
        <p className="max-w-sm text-pretty text-[0.85rem] leading-relaxed text-cream-faint">{body}</p>
      )}
      {action && <div className="mt-1.5">{action}</div>}
    </div>
  )
}
