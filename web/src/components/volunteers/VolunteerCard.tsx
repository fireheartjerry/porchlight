/**
 * One volunteer, the way the matcher sees them: where they go, what they can
 * do, how much of their week is already gone, and the notes Porchlight has
 * remembered about them over time.
 */

import clsx from 'clsx'
import { ShieldCheck } from 'lucide-react'
import { initials, relativeTime } from '../../lib/format'
import type { VolunteerWithLoad } from '../../types'
import { LoadMeter } from './LoadMeter'
import { orderSkills, skillIcon, skillLabel } from './skills'

export function VolunteerCard({ volunteer }: { volunteer: VolunteerWithLoad }) {
  const { this_week: thisWeek, max_per_week: max } = volunteer.load
  const full = max > 0 && thisWeek >= max
  const free = thisWeek === 0
  const { completed, no_show: noShow, accepted, declined } = volunteer.stats

  return (
    <article
      data-testid="volunteer-card"
      className={clsx(
        'porch-card flex h-full flex-col gap-3.5 px-4 py-4 transition-[border-color,background-color] duration-200',
        'hover:border-white/12 hover:bg-white/[0.04]',
        full && 'border-lamp/20',
      )}
    >
      <header className="flex items-start gap-3">
        <span
          aria-hidden
          className={clsx(
            'relative grid h-11 w-11 shrink-0 place-items-center rounded-full border font-display text-[0.9rem]',
            full
              ? 'border-lamp/35 bg-lamp/[0.09] text-lamp-wash'
              : free
                ? 'border-white/12 bg-white/[0.04] text-cream-dim'
                : 'border-sage/30 bg-sage/[0.08] text-sage',
          )}
        >
          {initials(volunteer.name)}
        </span>

        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-1.5 text-[0.98rem] font-medium leading-tight text-cream">
            <span className="truncate">{volunteer.name}</span>
            {volunteer.vetted && (
              <ShieldCheck
                className="h-3.5 w-3.5 shrink-0 text-sage"
                aria-label="Vetted for in-home work"
              />
            )}
          </h3>
          <p className="mt-0.5 truncate text-[0.75rem] text-cream-faint">
            {volunteer.zones.join(' · ') || 'no zones set'}
          </p>
          <p className="mt-0.5 truncate text-[0.72rem] text-cream-faint">
            Last out {relativeTime(volunteer.load.last_active ?? volunteer.stats.last_active)}
          </p>
        </div>
      </header>

      <LoadMeter thisWeek={thisWeek} max={max} />

      <ul className="flex flex-wrap gap-1.5">
        {orderSkills(volunteer.skills).map((skill) => {
          const Icon = skillIcon(skill)
          return (
            <li
              key={skill}
              className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.09] bg-white/[0.035] py-1 pl-2 pr-2.5 text-[0.72rem] text-cream-dim"
            >
              <Icon className="h-3 w-3 shrink-0 text-cream-faint" aria-hidden />
              {skillLabel(skill)}
            </li>
          )
        })}
      </ul>

      {volunteer.notes.length > 0 && (
        <div className="mt-auto rounded-xl border border-lilac/15 bg-lilac/[0.04] px-3 py-2.5">
          <p className="text-[0.62rem] uppercase tracking-[0.15em] text-lilac/80">Porchlight remembers</p>
          <ul className="mt-1.5 space-y-1">
            {volunteer.notes.map((note) => (
              <li
                key={note}
                className="text-pretty font-display text-[0.82rem] italic leading-snug text-cream-dim"
              >
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}

      <dl
        className={clsx(
          'grid grid-cols-4 gap-2 border-t border-white/[0.06] pt-2.5 text-center',
          volunteer.notes.length === 0 && 'mt-auto',
        )}
      >
        <Stat label="done" value={completed} />
        <Stat label="yes" value={accepted} />
        <Stat label="no" value={declined} />
        <Stat label="missed" value={noShow} tone={noShow > 0 ? 'warn' : 'quiet'} />
      </dl>
    </article>
  )
}

function Stat({ label, value, tone = 'quiet' }: { label: string; value: number; tone?: 'quiet' | 'warn' }) {
  return (
    <div>
      <dd
        className={clsx(
          'tabnum text-[0.95rem] leading-none',
          tone === 'warn' ? 'text-rust' : 'text-cream-dim',
        )}
      >
        {value}
      </dd>
      <dt className="mt-1 text-[0.62rem] uppercase tracking-[0.12em] text-cream-faint">{label}</dt>
    </div>
  )
}
