/**
 * Who Porchlight asked, in order, and what came back. This is the part a
 * coordinator would otherwise be reconstructing from their own sent-messages
 * folder at eleven at night.
 */

import clsx from 'clsx'
import { initials, relativeTime } from '../../lib/format'
import type { Attempt, AttemptOutcome, VolunteerWithLoad } from '../../types'

interface OutcomeMeta {
  label: string
  dot: string
  text: string
  rail: string
}

const OUTCOMES: Record<AttemptOutcome, OutcomeMeta> = {
  accepted: { label: 'accepted', dot: 'bg-sage', text: 'text-sage', rail: 'border-sage/45' },
  declined: { label: 'declined', dot: 'bg-white/30', text: 'text-cream-faint', rail: 'border-white/15' },
  pending: { label: 'waiting', dot: 'bg-lamp', text: 'text-lamp-glow', rail: 'border-lamp/45' },
  counter: { label: 'offered another time', dot: 'bg-dusk', text: 'text-dusk', rail: 'border-dusk/45' },
  concern: { label: 'raised a concern', dot: 'bg-rust', text: 'text-rust', rail: 'border-rust/45' },
  timeout: { label: 'no answer', dot: 'bg-white/20', text: 'text-cream-faint', rail: 'border-white/12' },
}

function attemptMeta(outcome: AttemptOutcome): OutcomeMeta {
  return OUTCOMES[outcome] ?? OUTCOMES.pending
}

export function AttemptTimeline({
  attempts,
  volunteers,
}: {
  attempts: Attempt[]
  volunteers: Map<string, VolunteerWithLoad>
}) {
  if (attempts.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-white/[0.08] px-4 py-5 text-[0.82rem] text-cream-faint">
        Nobody has been asked yet. Porchlight withholds the address until someone accepts.
      </p>
    )
  }

  return (
    <ol className="relative space-y-3 pl-1">
      {attempts.map((attempt, index) => {
        const volunteer = volunteers.get(attempt.volunteer_id)
        const meta = attemptMeta(attempt.outcome)
        const last = index === attempts.length - 1
        return (
          <li key={`${attempt.volunteer_id}-${attempt.sent_at}-${index}`} className="relative flex gap-3.5">
            {/* the rail: a thread from one ask to the next */}
            {!last && (
              <span
                aria-hidden
                className="absolute left-[1.1rem] top-9 h-[calc(100%-1rem)] w-px bg-gradient-to-b from-white/12 to-transparent"
              />
            )}
            <span
              className={clsx(
                'relative z-[1] grid h-9 w-9 shrink-0 place-items-center rounded-full border bg-porch-900/80 font-display text-[0.7rem] text-cream-dim',
                meta.rail,
              )}
            >
              {volunteer ? initials(volunteer.name) : '··'}
              <span
                aria-hidden
                className={clsx(
                  'absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-porch-900',
                  meta.dot,
                )}
              />
            </span>

            <div className="min-w-0 flex-1 pb-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-[0.85rem] font-medium text-cream">
                  {volunteer?.name ?? attempt.volunteer_id}
                </span>
                <span className={clsx('text-[0.76rem]', meta.text)}>{meta.label}</span>
                <span className="tabnum ml-auto shrink-0 text-[0.72rem] text-cream-faint">
                  {relativeTime(attempt.sent_at)}
                </span>
              </div>
              {attempt.note ? (
                <p className="mt-1 text-pretty font-display text-[0.85rem] italic leading-snug text-cream-dim">
                  “{attempt.note}”
                </p>
              ) : (
                <p className="mt-1 text-[0.78rem] text-cream-faint">
                  {attempt.outcome === 'pending' ? 'Asked — no reply yet.' : 'No note.'}
                </p>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
