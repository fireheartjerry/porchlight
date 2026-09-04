/**
 * One job on the board. Small enough to scan forty of them, honest enough that
 * you rarely need to open it: what it is, when, who has it, and how the asking
 * went — the attempt dots are a little string of porch lights.
 */

import clsx from 'clsx'
import { initials, firstName, formatWindow, formatWindowShort, relativeTime } from '../../lib/format'
import { CategoryGlyph } from '../CategoryGlyph'
import { ATTEMPT_TONES } from '../../lib/kinds'
import type { AidRequest, VolunteerWithLoad } from '../../types'
import { sourceMeta } from './sources'

interface RequestCardProps {
  request: AidRequest
  volunteer?: VolunteerWithLoad | undefined
  selected?: boolean
  onOpen: (requestId: string) => void
  onPrefetch?: (requestId: string) => void
}

export function RequestCard({ request, volunteer, selected, onOpen, onPrefetch }: RequestCardProps) {
  const SourceIcon = sourceMeta(request.source).icon
  const urgent = request.urgency === 'high' || request.urgency === 'emergency'
  const flagged = request.safety_flags.length > 0

  return (
    <button
      type="button"
      data-testid="request-card"
      onClick={() => onOpen(request.id)}
      onMouseEnter={() => onPrefetch?.(request.id)}
      onFocus={() => onPrefetch?.(request.id)}
      aria-label={`Open ${request.summary}`}
      className={clsx(
        'porch-card group block w-full px-3.5 py-3 text-left transition-[transform,border-color,background-color,box-shadow] duration-200',
        'hover:-translate-y-0.5 hover:border-white/15 hover:bg-white/[0.05]',
        selected
          ? 'border-lamp/45 bg-lamp/[0.06] shadow-halo'
          : flagged
            ? 'border-ember/25'
            : undefined,
      )}
    >
      <div className="flex items-start gap-2.5">
        <span
          className={clsx(
            'mt-0.5 shrink-0 rounded-lg border p-1.5 transition-colors duration-200',
            flagged
              ? 'border-ember/30 bg-ember/10 text-ember'
              : urgent
                ? 'border-lamp/25 bg-lamp/[0.09] text-lamp-glow'
                : 'border-white/[0.08] bg-white/[0.04] text-cream-dim group-hover:text-cream',
          )}
        >
          <CategoryGlyph category={request.category} className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-pretty font-display text-[0.9rem] leading-snug text-cream">{request.summary}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[0.72rem] leading-relaxed text-cream-faint">
            <SourceIcon className="h-3 w-3 shrink-0 opacity-70" aria-hidden />
            <span className="min-w-0 max-w-full truncate">{request.location_zone ?? 'zone unknown'}</span>
            {/* The separator travels with the window so a wrap never leaves a dangling dot. */}
            <span title={formatWindow(request.window_start, request.window_end)}>
              <span aria-hidden className="mr-1 opacity-50">
                ·
              </span>
              {formatWindowShort(request.window_start, request.window_end)}
            </span>
          </p>
        </div>
      </div>

      {(urgent || request.money_involved || flagged || request.first_time_requester) && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          {flagged && <Flag tone="ember">safety</Flag>}
          {urgent && <Flag tone="lamp">{request.urgency}</Flag>}
          {request.money_involved && <Flag tone="lamp">money</Flag>}
          {request.first_time_requester && <Flag tone="lilac">new neighbour</Flag>}
        </div>
      )}

      <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-white/[0.05] pt-2.5">
        {volunteer ? (
          <span className="flex min-w-0 items-center gap-1.5">
            <span
              aria-hidden
              className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-sage/30 bg-sage/10 font-display text-[0.55rem] text-sage"
            >
              {initials(volunteer.name)}
            </span>
            <span className="truncate text-[0.74rem] text-cream-dim">{firstName(volunteer.name)}</span>
          </span>
        ) : (
          <span className="truncate text-[0.72rem] text-cream-faint">
            {request.attempts.length > 0 ? 'asking around' : 'not yet asked'}
          </span>
        )}

        <span className="flex shrink-0 items-center gap-2">
          <AttemptDots request={request} />
          <span className="tabnum text-[0.7rem] text-cream-faint">{relativeTime(request.updated_at)}</span>
        </span>
      </div>
    </button>
  )
}

/** A string of lights: one bead per person asked, newest on the right. */
function AttemptDots({ request }: { request: AidRequest }) {
  if (request.attempts.length === 0) return null
  const shown = request.attempts.slice(-4)
  return (
    <span
      className="relative flex items-center gap-1 px-1"
      aria-label={`${request.attempts.length} volunteer${request.attempts.length === 1 ? '' : 's'} asked`}
    >
      <span aria-hidden className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-white/10" />
      {shown.map((attempt, index) => (
        <span
          key={`${attempt.volunteer_id}-${index}`}
          title={`${attempt.outcome}${attempt.note ? ` — ${attempt.note}` : ''}`}
          className={clsx(
            'relative h-1.5 w-1.5 rounded-full ring-2 ring-porch-900/90',
            ATTEMPT_TONES[attempt.outcome],
            attempt.outcome === 'pending' && 'shadow-[0_0_7px_1px_rgba(245,158,11,0.55)]',
          )}
        />
      ))}
    </span>
  )
}

function Flag({ children, tone }: { children: string; tone: 'ember' | 'lamp' | 'lilac' }) {
  return (
    <span
      className={clsx(
        'rounded-md border px-1.5 py-[0.05rem] text-[0.62rem] uppercase tracking-[0.11em]',
        tone === 'ember' && 'border-ember/30 bg-ember/10 text-ember',
        tone === 'lamp' && 'border-lamp/25 bg-lamp/10 text-lamp-glow',
        tone === 'lilac' && 'border-lilac/25 bg-lilac/10 text-lilac',
      )}
    >
      {children}
    </span>
  )
}
