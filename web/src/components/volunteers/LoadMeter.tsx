/**
 * How much of someone's week is already spoken for — one pip per slot they said
 * they could take, lit up as Porchlight uses them. Fairness is the point: the
 * matcher spreads load, and this is where you can see it working.
 */

import clsx from 'clsx'

interface LoadMeterProps {
  thisWeek: number
  max: number
  /** Compact variant for the roster summary strip. */
  size?: 'md' | 'sm'
}

export function LoadMeter({ thisWeek, max, size = 'md' }: LoadMeterProps) {
  const capped = Math.max(0, max)
  const used = Math.max(0, Math.min(thisWeek, capped))
  const full = capped > 0 && used >= capped
  const free = used === 0
  const pips = capped > 0 && capped <= 8

  const state = full
    ? 'Full for this week'
    : free
      ? 'Free this week'
      : `Room for ${capped - used} more`

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[0.68rem] uppercase tracking-[0.13em] text-cream-faint">This week</span>
        <span
          className={clsx(
            'tabnum text-[0.72rem]',
            full ? 'text-lamp-glow' : free ? 'text-cream-faint' : 'text-sage',
          )}
        >
          {used} / {capped}
        </span>
      </div>

      {pips ? (
        <div
          className={clsx('mt-1.5 flex gap-1', size === 'sm' && 'gap-[3px]')}
          role="img"
          aria-label={`${used} of ${capped} slots used this week`}
        >
          {Array.from({ length: capped }, (_, index) => (
            <span
              key={index}
              className={clsx(
                'flex-1 rounded-full transition-colors duration-500',
                size === 'sm' ? 'h-1' : 'h-1.5',
                index < used
                  ? full
                    ? 'bg-lamp shadow-[0_0_8px_-1px_rgba(245,158,11,0.7)]'
                    : 'bg-sage'
                  : 'bg-white/[0.09]',
              )}
            />
          ))}
        </div>
      ) : (
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.09]">
          <div
            className={clsx('h-full rounded-full transition-[width] duration-500', full ? 'bg-lamp' : 'bg-sage')}
            style={{ width: `${capped > 0 ? Math.min(100, (used / capped) * 100) : 0}%` }}
          />
        </div>
      )}

      <p
        className={clsx(
          'mt-1.5 text-[0.72rem]',
          full ? 'text-lamp-glow/85' : free ? 'text-cream-faint' : 'text-cream-faint',
        )}
      >
        {state}
      </p>
    </div>
  )
}
