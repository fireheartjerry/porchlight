/**
 * Screen 3 — Volunteers (docs/UI.md §Screens 3).
 *
 * The roster, ordered by default the way the matcher thinks: whoever has the
 * most room left this week comes first.
 */

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { listVolunteers, qk } from '../api'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { QueryState, Screen, Skeleton } from '../components/Screen'
import { RosterSummary } from '../components/volunteers/RosterSummary'
import { VolunteerCard } from '../components/volunteers/VolunteerCard'
import { skillLabel } from '../components/volunteers/skills'
import { pluralise } from '../lib/format'
import type { VolunteerWithLoad } from '../types'

type Sort = 'room' | 'name' | 'recent' | 'busiest'

const SORTS: { id: Sort; label: string }[] = [
  { id: 'room', label: 'Most room left' },
  { id: 'busiest', label: 'Busiest first' },
  { id: 'recent', label: 'Recently out' },
  { id: 'name', label: 'Name' },
]

function room(volunteer: VolunteerWithLoad): number {
  return volunteer.load.max_per_week - volunteer.load.this_week
}

function lastActive(volunteer: VolunteerWithLoad): number {
  const value = volunteer.load.last_active ?? volunteer.stats.last_active
  const time = value ? new Date(value).getTime() : 0
  return Number.isNaN(time) ? 0 : time
}

export function Volunteers() {
  const query = useQuery({ queryKey: qk.volunteers, queryFn: listVolunteers })
  const roster = useMemo(() => query.data ?? [], [query.data])

  const [needle, setNeedle] = useState('')
  const [zone, setZone] = useState<string | null>(null)
  const [sort, setSort] = useState<Sort>('room')
  const [freeOnly, setFreeOnly] = useState(false)

  const zones = useMemo(() => {
    const set = new Set<string>()
    for (const volunteer of roster) for (const item of volunteer.zones) set.add(item)
    return [...set].sort((a, b) => a.localeCompare(b))
  }, [roster])

  const shown = useMemo(() => {
    const text = needle.trim().toLowerCase()
    const rows = roster.filter((volunteer) => {
      if (zone && !volunteer.zones.includes(zone)) return false
      if (freeOnly && room(volunteer) <= 0) return false
      if (!text) return true
      const haystack = [
        volunteer.name,
        ...volunteer.zones,
        ...volunteer.skills.map(skillLabel),
        ...volunteer.notes,
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(text)
    })

    return rows.sort((a, b) => {
      switch (sort) {
        case 'room':
          return room(b) - room(a) || a.name.localeCompare(b.name)
        case 'busiest':
          return b.load.this_week - a.load.this_week || a.name.localeCompare(b.name)
        case 'recent':
          return lastActive(b) - lastActive(a)
        case 'name':
          return a.name.localeCompare(b.name)
        default:
          return 0
      }
    })
  }, [roster, needle, zone, freeOnly, sort])

  const active = roster.filter((volunteer) => volunteer.load.this_week > 0).length

  return (
    <Screen
      title="Volunteers"
      lede={
        query.data
          ? `${pluralise(roster.length, 'person', 'people')}. ${active} carrying something this week. Nobody here is a row in a spreadsheet — Porchlight keeps notes and asks accordingly.`
          : 'The roster the matcher reads before it asks anyone.'
      }
      actions={
        <>
          <label className="relative">
            <span className="sr-only">Search volunteers</span>
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-cream-faint"
            />
            <input
              value={needle}
              onChange={(event) => setNeedle(event.target.value)}
              placeholder="Name, skill, note…"
              className="h-9 w-full min-w-[13rem] rounded-xl border border-white/10 bg-porch-950/50 pl-9 pr-8 text-[0.82rem] text-cream placeholder:text-cream-faint focus:border-lamp/40 sm:w-64"
            />
            {needle && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => setNeedle('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-cream-faint hover:text-cream"
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            )}
          </label>
          <label className="flex items-center gap-2 text-[0.72rem] uppercase tracking-[0.12em] text-cream-faint">
            Sort
            <span className="relative inline-flex items-center">
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as Sort)}
                className="h-9 appearance-none rounded-xl border border-white/10 bg-porch-950/50 py-0 pl-3 pr-8 text-[0.8rem] normal-case tracking-normal text-cream transition-colors hover:border-white/20 focus:border-lamp/40"
              >
                {SORTS.map((option) => (
                  <option key={option.id} value={option.id} className="bg-porch-800">
                    {option.label}
                  </option>
                ))}
              </select>
              <ChevronDown
                aria-hidden
                className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-cream-faint"
              />
            </span>
          </label>
        </>
      }
    >
      <QueryState
        isPending={query.isPending}
        error={query.error}
        skeleton={
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((index) => (
              <Skeleton key={index} className="h-60" />
            ))}
          </div>
        }
      >
        <RosterSummary roster={roster} />

        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          <Chip active={zone === null} onClick={() => setZone(null)}>
            All zones
          </Chip>
          {zones.map((item) => (
            <Chip key={item} active={zone === item} onClick={() => setZone(zone === item ? null : item)}>
              {item}
            </Chip>
          ))}
          <span aria-hidden className="mx-1 hidden h-4 w-px bg-white/10 sm:block" />
          <Chip active={freeOnly} onClick={() => setFreeOnly((value) => !value)}>
            Has room this week
          </Chip>
          {(zone || freeOnly || needle) && (
            <span className="tabnum ml-1 text-[0.75rem] text-cream-faint">
              {pluralise(shown.length, 'person', 'people')}
            </span>
          )}
        </div>

        {shown.length === 0 ? (
          <Card>
            <EmptyState
              compact
              title="No one matches that."
              body="Clear a filter, or try another zone."
            />
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {shown.map((volunteer) => (
              <VolunteerCard key={volunteer.id} volunteer={volunteer} />
            ))}
          </div>
        )}
      </QueryState>
    </Screen>
  )
}

function Chip({
  children,
  active,
  onClick,
}: {
  children: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        'rounded-full border px-3 py-1 text-[0.75rem] transition-colors duration-150',
        active
          ? 'border-lamp/40 bg-lamp/12 text-lamp-glow'
          : 'border-white/[0.09] bg-white/[0.02] text-cream-faint hover:border-white/20 hover:text-cream',
      )}
    >
      {children}
    </button>
  )
}
