import clsx from 'clsx'
import type { CSSProperties, ElementType, ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  style?: CSSProperties
  /** Adds a warm rim — used by open Decision Cards. */
  glow?: boolean
  /** Slight lift on hover; for cards that are clickable. */
  interactive?: boolean
  /** Semantic element to render — `article` for standalone cards. */
  as?: ElementType
  /** Stable hook for the screenshot/regression harness. */
  testId?: string
}

export function Card({ children, className, style, glow, interactive, as, testId }: CardProps) {
  const Tag = as ?? 'div'
  return (
    <Tag
      data-testid={testId}
      className={clsx(
        'porch-card',
        glow && 'shadow-halo',
        interactive &&
          'cursor-pointer transition-[transform,border-color,background-color] duration-200 hover:-translate-y-0.5 hover:border-white/15 hover:bg-white/[0.05]',
        className,
      )}
      style={style}
    >
      {children}
    </Tag>
  )
}

interface CardHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  className?: string
}

export function CardHeader({ title, subtitle, icon, actions, className }: CardHeaderProps) {
  return (
    <div className={clsx('flex items-start justify-between gap-4 px-5 pt-4', className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && <span className="mt-0.5 text-cream-dim">{icon}</span>}
        <div className="min-w-0">
          <h3 className="truncate text-[0.95rem] font-medium text-cream">{title}</h3>
          {subtitle && <p className="mt-0.5 text-[0.8rem] text-cream-faint">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  )
}

/** Section label used above lists and columns — small, tracked, quiet. */
export function SectionLabel({
  children,
  count,
  className,
}: {
  children: ReactNode
  count?: number
  className?: string
}) {
  return (
    <div className={clsx('flex items-baseline gap-2', className)}>
      <h2 className="text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-cream-faint">
        {children}
      </h2>
      {count !== undefined && (
        <span className="tabnum text-[0.7rem] text-cream-faint">{count}</span>
      )}
    </div>
  )
}
