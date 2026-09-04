/**
 * Screen 2 — Requests (docs/UI.md §Screens 2).
 *
 * The board is the coordinator's whole workload in one glance: New → Matching →
 * Awaiting reply → Confirmed → Done. Clicking a card opens the case file.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Search, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { getRequest, listRequests, listVolunteers, qk } from '../api'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { QueryState, Screen, Skeleton } from '../components/Screen'
import { RequestCard } from '../components/requests/RequestCard'
import { RequestDrawer } from '../components/requests/RequestDrawer'
import {
  getOpenRequest,
  setOpenRequest,
  subscribeOpenRequest,
} from '../components/requests/openRequest'
import { pluralise } from '../lib/format'
import { BOARD_COLUMNS } from '../lib/kinds'
import type { AidRequest, VolunteerWithLoad } from '../types'

interface RequestsProps {
  /** The shell may want to know; the board opens the drawer either way. */
  onOpenRequest?: (requestId: string) => void
}

type Lens = 'all' | 'attention' | 'open' | 'new_faces'

const LENSES: { id: Lens; label: string; hint: string }[] = [
  { id: 'all', label: 'Everything', hint: 'Every request on file' },
  { id: 'open', label: 'Still moving', hint: 'Not yet finished or closed' },
  { id: 'attention', label: 'Sharp edges', hint: 'Urgent, money, or a safety flag' },
  { id: 'new_faces', label: 'New neighbours', hint: 'First time someone has asked' },
]

/** Each column gets its own hairline colour so the board reads left to right. */
const COLUMN_ACCENT: Record<string, string> = {
  new: 'from-slate/50',
  matching: 'from-dusk/50',
  awaiting: 'from-lamp/60',
  confirmed: 'from-sage/55',
  done: 'from-white/20',
}

const CLOSED: AidRequest['status'][] = ['completed', 'declined', 'cancelled']

export function Requests({ onOpenRequest }: RequestsProps) {
  const queryClient = useQueryClient()
  const requests = useQuery({ queryKey: qk.requests(), queryFn: () => listRequests() })
  const volunteers = useQuery({ queryKey: qk.volunteers, queryFn: listVolunteers })

  /** Lives outside React so the Inbox can hand us a request to open. */
  const openId = useSyncExternalStore(subscribeOpenRequest, getOpenRequest)
  const [query, setQuery] = useState('')
  const [lens, setLens] = useState<Lens>('all')

  const open = useCallback(
    (requestId: string) => {
      setOpenRequest(requestId)
      onOpenRequest?.(requestId)
    },
    [onOpenRequest],
  )

  // Walking off the board closes the case file behind you.
  useEffect(() => {
    const onHashChange = () => {
      if (!window.location.hash.startsWith('#/requests')) setOpenRequest(null)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const prefetch = useCallback(
    (requestId: string) =>
      void queryClient.prefetchQuery({
        queryKey: qk.request(requestId),
        queryFn: () => getRequest(requestId),
        staleTime: 15_000,
      }),
    [queryClient],
  )

  const byId = useMemo(() => {
    const map = new Map<string, VolunteerWithLoad>()
    for (const volunteer of volunteers.data ?? []) map.set(volunteer.id, volunteer)
    return map
  }, [volunteers.data])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (requests.data ?? []).filter((request) => {
      if (lens === 'open' && CLOSED.includes(request.status)) return false
      if (
        lens === 'attention' &&
        !(
          request.urgency === 'high' ||
          request.urgency === 'emergency' ||
          request.money_involved ||
          request.safety_flags.length > 0 ||
          request.status === 'escalated'
        )
      ) {
        return false
      }
      if (lens === 'new_faces' && !request.first_time_requester) return false
      if (!needle) return true
      const assigned = request.assigned_volunteer_id
        ? (byId.get(request.assigned_volunteer_id)?.name ?? '')
        : ''
      return `${request.summary} ${request.raw_text} ${request.location_zone ?? ''} ${request.category} ${assigned}`
        .toLowerCase()
        .includes(needle)
    })
  }, [requests.data, query, lens, byId])

  const columns = useMemo(
    () =>
      BOARD_COLUMNS.map((column) => ({
        ...column,
        rows: filtered.filter((request) => column.statuses.includes(request.status)),
      })),
    [filtered],
  )

  const total = requests.data?.length ?? 0
  const live = (requests.data ?? []).filter((request) => !CLOSED.includes(request.status)).length

  return (
    <>
      <Screen
        title="Requests"
        lede={
          requests.data
            ? `${pluralise(live, 'job')} in motion, ${total - live} closed out. Porchlight moves them along; you only read the ones you want to.`
            : 'Every job Porchlight is carrying, from the moment it arrives to the moment it closes.'
        }
        actions={
          <label className="relative">
            <span className="sr-only">Search requests</span>
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-cream-faint"
            />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search summaries, zones, names…"
              className="h-9 w-full min-w-[15rem] rounded-xl border border-white/10 bg-porch-950/50 pl-9 pr-8 text-[0.82rem] text-cream placeholder:text-cream-faint focus:border-lamp/40 sm:w-72"
            />
            {query && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => setQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-cream-faint hover:text-cream"
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            )}
          </label>
        }
      >
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          {LENSES.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setLens(item.id)}
              title={item.hint}
              aria-pressed={lens === item.id}
              className={clsx(
                'rounded-full border px-3 py-1 text-[0.75rem] transition-colors duration-150',
                lens === item.id
                  ? 'border-lamp/40 bg-lamp/12 text-lamp-glow'
                  : 'border-white/[0.09] bg-white/[0.02] text-cream-faint hover:border-white/20 hover:text-cream',
              )}
            >
              {item.label}
            </button>
          ))}
          {(query || lens !== 'all') && (
            <span className="tabnum ml-1 text-[0.75rem] text-cream-faint">
              {pluralise(filtered.length, 'match', 'matches')}
            </span>
          )}
        </div>

        <QueryState
          isPending={requests.isPending}
          error={requests.error}
          skeleton={
            <div className="grid gap-4 lg:grid-cols-5">
              {BOARD_COLUMNS.map((column) => (
                <Skeleton key={column.id} className="h-64" />
              ))}
            </div>
          }
        >
          <div className="porch-scroll -mx-4 overflow-x-auto px-4 pb-3 sm:-mx-6 sm:px-6 lg:mx-0 lg:overflow-visible lg:px-0">
            <div className="grid min-w-[64rem] grid-cols-5 items-start gap-4 lg:min-w-0">
              {columns.map((column) => (
                <section key={column.id} className="flex min-w-0 flex-col gap-2.5">
                  <div className="sticky top-[4.5rem] z-[1] -mx-1 bg-porch-900/95 px-1 pb-2 pt-2 backdrop-blur-md">
                    <div className="flex items-baseline justify-between gap-2">
                      <h2 className="text-[0.72rem] font-semibold uppercase tracking-[0.16em] text-cream-dim">
                        {column.label}
                      </h2>
                      <span className="tabnum text-[0.72rem] text-cream-faint">{column.rows.length}</span>
                    </div>
                    <span
                      aria-hidden
                      className={clsx(
                        'mt-1.5 block h-px w-full bg-gradient-to-r to-transparent',
                        COLUMN_ACCENT[column.id] ?? 'from-white/20',
                      )}
                    />
                  </div>

                  {column.rows.length === 0 ? (
                    <p className="rounded-xl border border-dashed border-white/[0.07] px-3 py-6 text-center text-[0.73rem] text-cream-faint">
                      nothing here
                    </p>
                  ) : (
                    column.rows.map((request) => (
                      <RequestCard
                        key={request.id}
                        request={request}
                        volunteer={
                          request.assigned_volunteer_id ? byId.get(request.assigned_volunteer_id) : undefined
                        }
                        selected={openId === request.id}
                        onOpen={open}
                        onPrefetch={prefetch}
                      />
                    ))
                  )}
                </section>
              ))}
            </div>
          </div>

          {total === 0 && (
            <Card className="mt-4">
              <EmptyState
                title="No requests yet."
                body="Paste a message in the Inbox, or run a Tuesday, and they will appear here."
              />
            </Card>
          )}
          {total > 0 && filtered.length === 0 && (
            <Card className="mt-4">
              <EmptyState
                compact
                title="Nothing matches that."
                body="Try a different word, or widen the filter."
              />
            </Card>
          )}
        </QueryState>
      </Screen>

      {openId && (
        <RequestDrawer key={openId} requestId={openId} onClose={() => setOpenRequest(null)} />
      )}
    </>
  )
}
