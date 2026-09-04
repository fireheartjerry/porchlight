/**
 * The audit trail for one request: every autonomous action with the rationale
 * Porchlight recorded at the time, and the raw detail one click away.
 */

import clsx from 'clsx'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { clockTime, humanise } from '../../lib/format'
import { agentTone, LOG_KIND_LABELS } from '../../lib/kinds'
import type { LogEvent } from '../../types'

export function LogTrail({ events, dense = false }: { events: LogEvent[]; dense?: boolean }) {
  if (events.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-white/[0.08] px-4 py-5 text-[0.82rem] text-cream-faint">
        No activity recorded yet.
      </p>
    )
  }

  // Newest last reads like a story; the API hands them back newest first.
  const ordered = [...events].reverse()

  return (
    <ol className={clsx('space-y-1', dense && 'space-y-0.5')}>
      {ordered.map((event) => (
        <LogRow key={event.id} event={event} />
      ))}
    </ol>
  )
}

function LogRow({ event }: { event: LogEvent }) {
  const [open, setOpen] = useState(false)
  const hasDetail = Object.keys(event.detail ?? {}).length > 0

  return (
    <li className="rounded-xl transition-colors duration-150 hover:bg-white/[0.03]">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((value) => !value)}
        aria-expanded={hasDetail ? open : undefined}
        className={clsx(
          'flex w-full items-baseline gap-2.5 px-2 py-1.5 text-left',
          !hasDetail && 'cursor-default',
        )}
      >
        <span className="tabnum shrink-0 text-[0.7rem] text-cream-faint">{clockTime(event.ts)}</span>
        <span
          className={clsx(
            'shrink-0 rounded-md border px-1.5 py-[0.05rem] text-[0.63rem] uppercase tracking-[0.1em]',
            agentTone(event.agent),
          )}
        >
          {event.agent}
        </span>
        <span className="min-w-0 flex-1 text-pretty text-[0.82rem] leading-snug text-cream-dim">
          {event.summary}
          {!event.autonomous && (
            <span className="ml-1.5 whitespace-nowrap text-[0.68rem] uppercase tracking-[0.1em] text-lamp-glow/80">
              needed you
            </span>
          )}
        </span>
        {hasDetail && (
          <ChevronRight
            aria-hidden
            className={clsx(
              'mt-0.5 h-3.5 w-3.5 shrink-0 text-cream-faint transition-transform duration-200',
              open && 'rotate-90',
            )}
          />
        )}
      </button>
      {open && hasDetail && (
        <div className="animate-slide-in px-2 pb-2 pl-[4.4rem]">
          <p className="mb-1 text-[0.66rem] uppercase tracking-[0.14em] text-cream-faint">
            {humanise(LOG_KIND_LABELS[event.kind] ?? event.kind)} detail
          </p>
          <pre className="porch-scroll max-h-56 overflow-auto rounded-lg border border-white/[0.07] bg-porch-950/60 px-3 py-2 font-mono text-[0.7rem] leading-relaxed text-cream-dim">
            {JSON.stringify(event.detail, null, 2)}
          </pre>
        </div>
      )}
    </li>
  )
}
