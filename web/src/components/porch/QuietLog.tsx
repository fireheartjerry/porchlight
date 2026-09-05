/**
 * "Handled quietly" — the Quiet Log (docs/UI.md screen 1).
 *
 * Every autonomous side effect Porchlight took, grouped by the request it
 * belongs to so the coordinator reads a story ("Amara's ride: parsed → matched →
 * asked Maria → confirmed") rather than a flat firehose. Filter chips narrow to
 * messages, matches, or memory writes; each row expands into the detail the
 * agent actually recorded.
 */

import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'
import { useMemo, useState } from 'react'
import { clockTime, humanise, pluralise, relativeTime } from '../../lib/format'
import { CategoryGlyph } from '../CategoryGlyph'
import { agentTone, LOG_KIND_LABELS, STATUS_LABELS, STATUS_TONES } from '../../lib/kinds'
import type { AidRequest, LogEvent } from '../../types'
import { Badge } from '../Badge'
import { EmptyState } from '../EmptyState'
import { DetailTable } from './DetailTable'

type FilterId = 'all' | 'messages' | 'matches' | 'memory'

const FILTERS: { id: FilterId; label: string; match: (event: LogEvent) => boolean }[] = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'messages', label: 'Messages', match: (event) => event.kind === 'message_sent' },
  { id: 'matches', label: 'Matches', match: (event) => event.agent === 'matcher' },
  { id: 'memory', label: 'Memory', match: (event) => event.kind === 'memory' },
]

const GROUPS_PER_PAGE = 6

interface Group {
  key: string
  request: AidRequest | undefined
  events: LogEvent[]
  /** Newest timestamp in the group — groups are ordered by this, newest first. */
  latest: number
}

function timeOf(event: LogEvent): number {
  const value = new Date(event.ts).getTime()
  return Number.isNaN(value) ? 0 : value
}

function groupByRequest(events: LogEvent[], requests: Map<string, AidRequest>): Group[] {
  const groups = new Map<string, Group>()
  for (const event of events) {
    const key = event.request_id ?? '__loose__'
    const existing = groups.get(key)
    if (existing) {
      existing.events.push(event)
      existing.latest = Math.max(existing.latest, timeOf(event))
    } else {
      groups.set(key, {
        key,
        request: event.request_id ? requests.get(event.request_id) : undefined,
        events: [event],
        latest: timeOf(event),
      })
    }
  }
  const out = Array.from(groups.values())
  for (const group of out) group.events.sort((a, b) => timeOf(a) - timeOf(b))
  // Loose events (nightly brief, demo resets) sink to the bottom.
  return out.sort((a, b) => {
    if (a.key === '__loose__') return 1
    if (b.key === '__loose__') return -1
    return b.latest - a.latest
  })
}

export function QuietLog({ events, requests }: { events: LogEvent[]; requests: AidRequest[] }) {
  const [filter, setFilter] = useState<FilterId>('all')
  const [page, setPage] = useState(1)

  const byId = useMemo(() => new Map(requests.map((request) => [request.id, request])), [requests])
  const counts = useMemo(
    () =>
      FILTERS.reduce<Record<FilterId, number>>(
        (acc, entry) => {
          acc[entry.id] = events.filter(entry.match).length
          return acc
        },
        { all: 0, messages: 0, matches: 0, memory: 0 },
      ),
    [events],
  )

  const groups = useMemo(() => {
    const active = FILTERS.find((entry) => entry.id === filter) ?? FILTERS[0]!
    return groupByRequest(events.filter(active.match), byId)
  }, [events, filter, byId])

  const visible = groups.slice(0, page * GROUPS_PER_PAGE)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter the quiet log">
        {FILTERS.map((entry) => {
          const active = entry.id === filter
          return (
            <button
              key={entry.id}
              type="button"
              aria-pressed={active}
              onClick={() => {
                setFilter(entry.id)
                setPage(1)
              }}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[0.76rem] transition-colors duration-150',
                active
                  ? 'border-lamp/40 bg-lamp/[0.12] text-lamp-wash'
                  : 'border-white/[0.09] bg-white/[0.02] text-cream-faint hover:border-white/20 hover:text-cream-dim',
              )}
            >
              {entry.label}
              <span className={clsx('tabnum text-[0.68rem]', active ? 'text-lamp/80' : 'text-cream-faint')}>
                {counts[entry.id]}
              </span>
            </button>
          )
        })}
      </div>

      {visible.length === 0 ? (
        <div className="porch-card">
          <EmptyState
            compact
            title={filter === 'all' ? 'Nothing yet tonight.' : 'Nothing under that filter.'}
            body={
              filter === 'all'
                ? 'The moment a message arrives, the work Porchlight does on its own shows up here.'
                : undefined
            }
          />
        </div>
      ) : (
        <div className="space-y-2.5">
          {visible.map((group, index) => (
            <RequestThread key={group.key} group={group} defaultOpen={index < 3} />
          ))}
        </div>
      )}

      {groups.length > visible.length && (
        <button
          type="button"
          onClick={() => setPage((value) => value + 1)}
          className="w-full rounded-xl border border-white/[0.08] bg-white/[0.02] py-2 text-[0.78rem] text-cream-faint transition-colors hover:border-white/20 hover:text-cream-dim"
        >
          Show earlier activity ({groups.length - visible.length} more)
        </button>
      )}
    </div>
  )
}

function RequestThread({ group, defaultOpen }: { group: Group; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const { request } = group
  const needsYou = group.events.some((event) => !event.autonomous)
  // Never the raw id: a coordinator reads summaries, and the roster may still be loading.
  const title =
    request?.summary?.trim() ||
    (group.key === '__loose__' ? 'Housekeeping' : 'A request Porchlight handled')

  return (
    <section className="porch-card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-150 hover:bg-white/[0.03]"
      >
        <span
          className={clsx(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border',
            needsYou
              ? 'border-lamp/30 bg-lamp/[0.1] text-lamp-glow'
              : 'border-white/[0.08] bg-white/[0.03] text-cream-faint',
          )}
        >
          <CategoryGlyph category={request?.category} fallback="layers" className="h-4 w-4" />
        </span>

        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 block text-pretty text-[0.88rem] font-medium leading-snug text-cream">
            {title}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.72rem] text-cream-faint">
            <span className="tabnum">{pluralise(group.events.length, 'step')}</span>
            <span aria-hidden>·</span>
            <span>{relativeTime(group.events[group.events.length - 1]!.ts)}</span>
            {request?.location_zone && (
              <>
                <span aria-hidden>·</span>
                <span>{request.location_zone}</span>
              </>
            )}
          </span>
        </span>

        {request && (
          <Badge className="hidden sm:inline-flex" toneClass={STATUS_TONES[request.status]}>
            {STATUS_LABELS[request.status]}
          </Badge>
        )}
        <ChevronDown
          aria-hidden
          className={clsx(
            'h-4 w-4 shrink-0 text-cream-faint transition-transform duration-200',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <ol className="relative border-t border-white/[0.05] px-4 pb-3 pt-2">
          {/* the thread the events hang from */}
          <span
            aria-hidden
            className="pointer-events-none absolute bottom-5 left-[4.55rem] top-4 w-px bg-gradient-to-b from-white/[0.14] via-white/[0.08] to-transparent"
          />
          {group.events.map((event) => (
            <QuietRow key={event.id} event={event} />
          ))}
        </ol>
      )}
    </section>
  )
}

function QuietRow({ event }: { event: LogEvent }) {
  const [open, setOpen] = useState(false)
  const hasDetail = Object.keys(event.detail).length > 0

  return (
    <li data-testid="quiet-row" className="relative flex animate-slide-in items-start gap-3 py-1.5">
      <span className="tabnum mt-[0.15rem] w-[3.1rem] shrink-0 text-right text-[0.72rem] text-cream-faint">
        {clockTime(event.ts)}
      </span>
      <span className="relative mt-[0.42rem] flex h-2 w-2 shrink-0 items-center justify-center">
        <span
          className={clsx(
            'h-[0.42rem] w-[0.42rem] rounded-full ring-4 ring-porch-900',
            event.autonomous ? 'bg-sage/70' : 'bg-lamp',
          )}
        />
      </span>
      <div className="min-w-0 flex-1 pl-1">
        <p className="text-pretty text-[0.85rem] leading-snug text-cream-dim">{event.summary}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className={clsx(
              'rounded-full border px-1.5 py-[0.02rem] text-[0.6rem] font-semibold uppercase tracking-[0.1em]',
              agentTone(event.agent),
            )}
          >
            {event.agent}
          </span>
          <span className="text-[0.68rem] uppercase tracking-[0.1em] text-cream-faint">
            {LOG_KIND_LABELS[event.kind] ?? humanise(event.kind)}
          </span>
          {!event.autonomous && (
            <span className="text-[0.68rem] uppercase tracking-[0.1em] text-lamp/80">needed you</span>
          )}
          {hasDetail && (
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              aria-expanded={open}
              className="inline-flex items-center gap-0.5 text-[0.68rem] text-cream-faint transition-colors hover:text-cream-dim"
            >
              detail
              <ChevronDown
                aria-hidden
                className={clsx('h-3 w-3 transition-transform duration-150', open && 'rotate-180')}
              />
            </button>
          )}
        </div>
        {open && hasDetail && <DetailTable dense detail={event.detail} className="mt-2 animate-slide-in" />}
      </div>
    </li>
  )
}
