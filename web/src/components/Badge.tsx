import clsx from 'clsx'
import type { ReactNode } from 'react'
import { DECISION_TONES } from '../lib/kinds'
import type { DecisionKind } from '../types'

type BadgeTone = 'neutral' | 'good' | 'warn' | 'bad' | 'info'

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-white/[0.06] text-cream-dim border-white/12',
  good: 'bg-sage/12 text-sage border-sage/25',
  warn: 'bg-lamp/12 text-lamp-glow border-lamp/30',
  bad: 'bg-ember/12 text-ember border-ember/30',
  info: 'bg-dusk/12 text-dusk border-dusk/25',
}

interface BadgeProps {
  children: ReactNode
  /** Decision kind colours (safety, money, vetting, unmatched, concern, policy). */
  kind?: DecisionKind
  tone?: BadgeTone
  icon?: ReactNode
  className?: string
  /** Pass through a bespoke colour class set (e.g. STATUS_TONES). */
  toneClass?: string
}

export function Badge({ children, kind, tone = 'neutral', icon, className, toneClass }: BadgeProps) {
  const colours = toneClass ?? (kind ? DECISION_TONES[kind].chip : TONES[tone])
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-[0.15rem] text-[0.68rem] font-medium uppercase tracking-[0.09em]',
        colours,
        className,
      )}
    >
      {icon}
      {children}
    </span>
  )
}

/** A small round dot; the header's Live indicator and attempt dots use it. */
export function Dot({ className, pulse }: { className?: string; pulse?: boolean }) {
  return (
    <span
      className={clsx('inline-block h-1.5 w-1.5 rounded-full', pulse && 'animate-pulse-dot', className)}
    />
  )
}
