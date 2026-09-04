/**
 * The roster at a glance. The number that matters is spare capacity: how many
 * more asks this group can absorb this week before Porchlight starts running
 * out of people to ask.
 */

import clsx from 'clsx'
import type { VolunteerWithLoad } from '../../types'

export function RosterSummary({ roster }: { roster: VolunteerWithLoad[] }) {
  const used = roster.reduce((sum, volunteer) => sum + Math.min(volunteer.load.this_week, volunteer.load.max_per_week), 0)
  const capacity = roster.reduce((sum, volunteer) => sum + volunteer.load.max_per_week, 0)
  const spare = Math.max(0, capacity - used)
  const vetted = roster.filter((volunteer) => volunteer.vetted).length
  const zones = new Set(roster.flatMap((volunteer) => volunteer.zones)).size
  const resting = roster.filter((volunteer) => volunteer.load.this_week === 0).length
  const pct = capacity > 0 ? Math.round((used / capacity) * 100) : 0

  return (
    <div className="porch-card mb-5 overflow-hidden px-5 py-4">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <p className="text-[0.68rem] uppercase tracking-[0.15em] text-cream-faint">Spare capacity</p>
          <p className="display-xl tabnum mt-1 text-[2.1rem] leading-none text-cream">
            {spare}
            <span className="ml-2 font-sans text-[0.8rem] tracking-normal text-cream-faint">
              more asks this week
            </span>
          </p>
        </div>

        <dl className="flex flex-wrap items-end gap-x-7 gap-y-3">
          <Cell label="People" value={roster.length} />
          <Cell label="Resting" value={resting} tone="sage" />
          <Cell label="Vetted" value={vetted} />
          <Cell label="Zones" value={zones} />
        </dl>
      </div>

      <div className="mt-3.5">
        <div
          className="flex h-1.5 gap-0.5 overflow-hidden rounded-full"
          role="img"
          aria-label={`${used} of ${capacity} weekly slots taken`}
        >
          <span
            className="rounded-full bg-gradient-to-r from-sage/80 to-sage transition-[width] duration-700"
            style={{ width: `${pct}%` }}
          />
          <span className="flex-1 rounded-full bg-white/[0.07]" />
        </div>
        <p className="mt-1.5 text-[0.73rem] text-cream-faint">
          <span className="tabnum text-cream-dim">{used}</span> of{' '}
          <span className="tabnum text-cream-dim">{capacity}</span> weekly slots taken — the matcher spreads
          them on purpose, so nobody gets asked twice while somebody sits idle.
        </p>
      </div>
    </div>
  )
}

function Cell({ label, value, tone = 'quiet' }: { label: string; value: number; tone?: 'quiet' | 'sage' }) {
  return (
    <div>
      <dd
        className={clsx('tabnum font-display text-[1.35rem] leading-none', tone === 'sage' ? 'text-sage' : 'text-cream-dim')}
      >
        {value}
      </dd>
      <dt className="mt-1 text-[0.64rem] uppercase tracking-[0.14em] text-cream-faint">{label}</dt>
    </div>
  )
}
