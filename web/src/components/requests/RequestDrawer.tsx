/**
 * The case file for one request, as a slide-over: the message exactly as it
 * arrived, what Porchlight understood, who it asked and what they said, every
 * word it sent, and the audit trail underneath.
 */

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { CircleCheck, Hand, MapPin, UserRound, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { getRequest, listVolunteers, qk } from '../../api'
import { formatWindow, humanise, relativeTime } from '../../lib/format'
import { CATEGORY_ICONS, STATUS_LABELS, STATUS_TONES } from '../../lib/kinds'
import type { VolunteerWithLoad } from '../../types'
import { Badge } from '../Badge'
import { IconButton } from '../Button'
import { SectionLabel } from '../Card'
import { Skeleton } from '../Screen'
import { AttemptTimeline } from './AttemptTimeline'
import { LogTrail } from './LogTrail'
import { MessageThread } from './MessageThread'
import { sourceMeta } from './sources'

const EXIT_MS = 220

export function RequestDrawer({ requestId, onClose }: { requestId: string; onClose: () => void }) {
  const [shown, setShown] = useState(false)
  const panel = useRef<HTMLDivElement>(null)
  const closing = useRef(false)
  const restoreFocus = useRef<HTMLElement | null>(null)

  const detail = useQuery({
    queryKey: qk.request(requestId),
    queryFn: () => getRequest(requestId),
    refetchInterval: 8_000,
  })
  const volunteersQuery = useQuery({ queryKey: qk.volunteers, queryFn: listVolunteers })

  const volunteers = useMemo(() => {
    const map = new Map<string, VolunteerWithLoad>()
    for (const volunteer of volunteersQuery.data ?? []) map.set(volunteer.id, volunteer)
    return map
  }, [volunteersQuery.data])

  useEffect(() => {
    restoreFocus.current = document.activeElement as HTMLElement | null
    const frame = requestAnimationFrame(() => setShown(true))
    panel.current?.focus({ preventScroll: true })
    return () => {
      cancelAnimationFrame(frame)
      restoreFocus.current?.focus?.({ preventScroll: true })
    }
  }, [])

  // Re-open the slide on a different request without a jarring remount.
  useEffect(() => {
    panel.current?.scrollTo({ top: 0 })
  }, [requestId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      close()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  })

  function close() {
    if (closing.current) return
    closing.current = true
    setShown(false)
    window.setTimeout(onClose, EXIT_MS)
  }

  const data = detail.data
  const request = data?.request
  const Icon = request ? (CATEGORY_ICONS[request.category] ?? CATEGORY_ICONS.other) : CATEGORY_ICONS.other
  const source = request ? sourceMeta(request.source) : null
  const volunteer = request?.assigned_volunteer_id ? volunteers.get(request.assigned_volunteer_id) : undefined
  const neededYou = (data?.log ?? []).some((event) => !event.autonomous)
  const settled = request?.status === 'completed' || request?.status === 'in_progress'

  return (
    <div className="fixed inset-0 z-40" role="presentation">
      <div
        aria-hidden
        onClick={close}
        className={clsx(
          'absolute inset-0 bg-porch-950/70 backdrop-blur-[3px] transition-opacity duration-200',
          shown ? 'opacity-100' : 'opacity-0',
        )}
      />

      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={request ? `Request — ${request.summary}` : 'Request'}
        tabIndex={-1}
        className={clsx(
          'porch-scroll absolute inset-y-0 right-0 flex w-full max-w-[38rem] flex-col overflow-y-auto',
          'border-l border-white/[0.09] bg-porch-900 shadow-[-30px_0_80px_-40px_rgba(0,0,0,0.95)] outline-none',
          'transition-transform duration-[220ms] ease-[cubic-bezier(0.22,1,0.36,1)]',
          shown ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        {/* a thin warm edge, as if the door were ajar */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 w-px bg-gradient-to-b from-transparent via-lamp/45 to-transparent"
        />

        <header className="sticky top-0 z-10 border-b border-white/[0.07] bg-porch-900/95 px-5 py-4 backdrop-blur-xl">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 shrink-0 rounded-xl border border-white/[0.09] bg-white/[0.04] p-2 text-lamp-glow">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-pretty font-display text-[1.15rem] leading-tight text-cream">
                {request?.summary ?? 'Loading…'}
              </h2>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {request && (
                  <>
                    <Badge toneClass={STATUS_TONES[request.status]}>{STATUS_LABELS[request.status]}</Badge>
                    <Badge className="normal-case tracking-normal">{request.category}</Badge>
                    <span className="tabnum font-mono text-[0.68rem] text-cream-faint">{request.id}</span>
                  </>
                )}
              </div>
            </div>
            <IconButton
              label="Close"
              onClick={close}
              icon={<X className="h-4 w-4" aria-hidden />}
              variant="ghost"
            />
          </div>
        </header>

        {detail.isPending ? (
          <div className="space-y-3 px-5 py-5">
            <Skeleton className="h-28" />
            <Skeleton className="h-24" />
            <Skeleton className="h-40" />
          </div>
        ) : detail.error || !data || !request || !source ? (
          <div className="px-5 py-8">
            <p className="text-[0.9rem] text-cream">That request could not be loaded.</p>
            <p className="mt-1 font-mono text-[0.75rem] text-ember/90">
              {detail.error instanceof Error ? detail.error.message : 'Not found.'}
            </p>
          </div>
        ) : (
          <div className="space-y-7 px-5 py-6">
            {/* 1 — the message itself */}
            <section>
              <SectionLabel className="mb-2">As it arrived</SectionLabel>
              <blockquote className="relative rounded-2xl border border-white/[0.08] bg-porch-950/45 px-4 py-3.5">
                <span
                  aria-hidden
                  className="absolute -left-px top-4 h-[calc(100%-2rem)] w-[2px] rounded-full bg-gradient-to-b from-lamp/60 to-lamp/0"
                />
                <p className="text-pretty font-display text-[0.95rem] italic leading-relaxed text-cream/95">
                  {request.raw_text}
                </p>
                <p className="mt-2.5 flex items-center gap-1.5 text-[0.72rem] text-cream-faint">
                  <source.icon className="h-3 w-3" aria-hidden />
                  Came in {source.arrival} · {relativeTime(request.created_at)}
                </p>
              </blockquote>
              <p className="mt-2 flex items-center gap-1.5 text-[0.76rem] text-cream-faint">
                {neededYou ? (
                  <>
                    <Hand className="h-3.5 w-3.5 text-lamp-glow" aria-hidden />
                    Porchlight stopped and asked you about this one.
                  </>
                ) : settled ? (
                  <>
                    <CircleCheck className="h-3.5 w-3.5 text-sage" aria-hidden />
                    Carried end to end without waking you.
                  </>
                ) : (
                  <>
                    <CircleCheck className="h-3.5 w-3.5 text-sage/70" aria-hidden />
                    Running on its own so far — nothing here has needed you.
                  </>
                )}
              </p>
            </section>

            {/* 2 — what it understood */}
            <section>
              <SectionLabel className="mb-2">What Porchlight understood</SectionLabel>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-0 rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-1 sm:grid-cols-2">
                <Fact label="When">{formatWindow(request.window_start, request.window_end)}</Fact>
                <Fact label="Flexible">{request.flexible ? 'Yes — can move' : 'Fixed'}</Fact>
                <Fact label="Where" icon={<MapPin className="h-3 w-3" aria-hidden />}>
                  {request.location_zone ?? 'Not stated'}
                </Fact>
                <Fact label="Urgency">{humanise(request.urgency)}</Fact>
                <Fact label="Requester" icon={<UserRound className="h-3 w-3" aria-hidden />}>
                  {request.first_time_requester ? 'First time asking' : 'Known to the group'}
                  {request.requester_id && (
                    <span className="ml-1.5 font-mono text-[0.68rem] text-cream-faint">
                      {request.requester_id}
                    </span>
                  )}
                </Fact>
                <Fact label="Assigned">
                  {volunteer ? (
                    volunteer.name
                  ) : (
                    <span className="text-cream-faint">Nobody yet</span>
                  )}
                </Fact>
              </dl>

              {(request.constraints.length > 0 ||
                request.safety_flags.length > 0 ||
                request.money_involved) && (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {request.safety_flags.map((flag) => (
                    <Badge key={flag} tone="bad" className="normal-case tracking-normal">
                      {humanise(flag)}
                    </Badge>
                  ))}
                  {request.money_involved && <Badge tone="warn">money involved</Badge>}
                  {request.constraints.map((constraint) => (
                    <Badge key={constraint} className="normal-case tracking-normal">
                      {constraint}
                    </Badge>
                  ))}
                </div>
              )}
            </section>

            {/* 3 — the asking */}
            <section>
              <SectionLabel className="mb-2.5" count={data.attempts.length}>
                Who it asked
              </SectionLabel>
              <AttemptTimeline attempts={data.attempts} volunteers={volunteers} />
            </section>

            {/* 4 — the words */}
            <section>
              <SectionLabel className="mb-2.5" count={data.messages.length}>
                Messages sent
              </SectionLabel>
              <MessageThread messages={data.messages} volunteers={volunteers} />
            </section>

            {/* 5 — the trail */}
            <section>
              <SectionLabel className="mb-2" count={data.log.length}>
                Activity
              </SectionLabel>
              <LogTrail events={data.log} />
            </section>

            <p className="pb-2 text-center text-[0.72rem] text-cream-faint">
              Last change {relativeTime(request.updated_at)}.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function Fact({ label, children, icon }: { label: string; children: ReactNode; icon?: ReactNode }) {
  return (
    <div className="border-b border-white/[0.05] py-2.5 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
      <dt className="flex items-center gap-1.5 text-[0.66rem] uppercase tracking-[0.14em] text-cream-faint">
        {icon}
        {label}
      </dt>
      <dd className="mt-0.5 text-[0.85rem] leading-snug text-cream-dim">{children}</dd>
    </div>
  )
}
