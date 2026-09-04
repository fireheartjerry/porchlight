/**
 * Every message Porchlight sent on this request — the actual words, not a count.
 * Volunteer messages lean left in lamp light; the requester's confirmations sit
 * to the right in sage. Scheduled messages are shown before they go out.
 */

import clsx from 'clsx'
import { Clock3, Send } from 'lucide-react'
import { clockTime, dayLabel, relativeTime } from '../../lib/format'
import type { OutboundMessage, Recipient, VolunteerWithLoad } from '../../types'

const RECIPIENT_TONE: Record<Recipient, string> = {
  volunteer: 'border-lamp/20 bg-lamp/[0.055]',
  requester: 'border-sage/20 bg-sage/[0.05]',
  coordinator: 'border-white/10 bg-white/[0.035]',
}

const RECIPIENT_LABEL: Record<Recipient, string> = {
  volunteer: 'to the volunteer',
  requester: 'to the requester',
  coordinator: 'to you',
}

export function MessageThread({
  messages,
  volunteers,
}: {
  messages: OutboundMessage[]
  volunteers: Map<string, VolunteerWithLoad>
}) {
  if (messages.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-white/[0.08] px-4 py-5 text-[0.82rem] text-cream-faint">
        Nothing has gone out yet.
      </p>
    )
  }

  // Oldest first: a thread reads top to bottom.
  const ordered = [...messages].sort(
    (a, b) => stamp(a) - stamp(b),
  )

  return (
    <ol className="space-y-2.5">
      {ordered.map((message) => {
        const name =
          message.to === 'volunteer' && message.recipient_id
            ? (volunteers.get(message.recipient_id)?.name ?? null)
            : null
        const scheduled = !message.sent_at && message.scheduled_for
        return (
          <li
            key={message.id}
            className={clsx(
              'rounded-2xl border px-3.5 py-3',
              RECIPIENT_TONE[message.to] ?? RECIPIENT_TONE.coordinator,
              message.to === 'requester' && 'sm:ml-8',
              message.to === 'volunteer' && 'sm:mr-8',
            )}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-[0.75rem] font-medium uppercase tracking-[0.11em] text-cream-dim">
                {name ?? RECIPIENT_LABEL[message.to] ?? 'sent'}
              </span>
              <span className="text-[0.72rem] text-cream-faint">
                {name ? RECIPIENT_LABEL[message.to] : null} · {message.channel}
              </span>
              <span className="tabnum ml-auto inline-flex shrink-0 items-center gap-1 text-[0.72rem] text-cream-faint">
                {scheduled ? (
                  <>
                    <Clock3 className="h-3 w-3" aria-hidden />
                    {dayLabel(message.scheduled_for)} {clockTime(message.scheduled_for)}
                  </>
                ) : (
                  <>
                    <Send className="h-3 w-3" aria-hidden />
                    {relativeTime(message.sent_at)}
                  </>
                )}
              </span>
            </div>
            <p className="mt-1.5 text-pretty text-[0.86rem] leading-relaxed text-cream/95">{message.body}</p>
            {message.status !== 'sent' && message.status !== 'delivered' && (
              <p className="mt-1.5 text-[0.72rem] uppercase tracking-[0.12em] text-lamp-glow/80">
                {message.status}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}

function stamp(message: OutboundMessage): number {
  const value = message.sent_at ?? message.scheduled_for
  const time = value ? new Date(value).getTime() : Number.NaN
  return Number.isNaN(time) ? 0 : time
}
