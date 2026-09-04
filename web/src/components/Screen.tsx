import clsx from 'clsx'
import type { ReactNode } from 'react'

/** Consistent editorial header for every screen: big serif title, quiet lede. */
export function Screen({
  title,
  lede,
  actions,
  children,
  className,
}: {
  title: string
  lede?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('mx-auto w-full max-w-[88rem] px-4 pb-24 pt-6 sm:px-6 lg:px-8 lg:pb-10', className)}>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="display-xl text-[1.75rem] leading-none text-cream sm:text-[2.05rem]">{title}</h1>
          {lede && <p className="mt-2 max-w-2xl text-pretty text-[0.9rem] text-cream-faint">{lede}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      {children}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded-lg bg-white/[0.05]', className)} />
}

/** Uniform loading / error handling for the query-backed screens. */
export function QueryState({
  isPending,
  error,
  children,
  skeleton,
}: {
  isPending: boolean
  error: unknown
  children: ReactNode
  skeleton?: ReactNode
}) {
  if (isPending) {
    return (
      <>
        {skeleton ?? (
          <div className="space-y-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        )}
      </>
    )
  }
  if (error) {
    const message = error instanceof Error ? error.message : String(error)
    return (
      <div className="porch-card border-ember/25 bg-ember/[0.05] px-5 py-4">
        <p className="text-[0.9rem] text-cream">The porch can’t reach the API.</p>
        <p className="mt-1 font-mono text-[0.75rem] leading-relaxed text-ember/90">{message}</p>
        <p className="mt-2 text-[0.8rem] text-cream-faint">
          Start the backend on :8000, or run <code className="text-lamp-wash">npm run dev:mock</code>.
        </p>
      </div>
    )
  }
  return <>{children}</>
}
