import clsx from 'clsx'
import type { ReactNode } from 'react'

interface StatTileProps {
  label: string
  value: number | string
  hint?: string
  icon?: ReactNode
  /** Warm tint for the tile that matters most (open decisions). */
  accent?: 'lamp' | 'sage' | 'none'
  className?: string
}

export function StatTile({ label, value, hint, icon, accent = 'none', className }: StatTileProps) {
  return (
    <div
      className={clsx(
        'porch-card overflow-hidden px-4 py-3.5',
        accent === 'lamp' && 'border-lamp/25 bg-lamp/[0.06]',
        accent === 'sage' && 'border-sage/20 bg-sage/[0.05]',
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-cream-faint">
          {label}
        </span>
        {icon && (
          <span
            className={clsx(
              'shrink-0',
              accent === 'lamp' ? 'text-lamp-glow' : accent === 'sage' ? 'text-sage' : 'text-cream-faint',
            )}
          >
            {icon}
          </span>
        )}
      </div>
      <div
        className={clsx(
          'display-xl tabnum mt-1.5 text-[2rem] leading-none',
          accent === 'lamp' ? 'text-lamp-glow' : accent === 'sage' ? 'text-sage' : 'text-cream',
        )}
      >
        {value}
      </div>
      {hint && <p className="mt-1.5 text-[0.75rem] leading-snug text-cream-faint">{hint}</p>}
    </div>
  )
}
