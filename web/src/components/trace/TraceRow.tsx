/**
 * One line of the trace. Monospace, colour-coded by event type, railed by
 * request id, and expandable into the raw payload the agent emitted.
 */

import clsx from 'clsx'
import { useState } from 'react'
import { preciseTime } from '../../lib/format'
import type { TraceEvent } from '../../types'
import { DetailTable } from '../porch/DetailTable'
import { railColour, shortRequestId, typeMeta } from './traceStyles'

export function TraceRow({ event }: { event: TraceEvent }) {
  const [open, setOpen] = useState(false)
  const meta = typeMeta(event.type)
  const rail = railColour(event.request_id)
  const hasDetail = Object.keys(event.detail).length > 0

  return (
    <li
      data-testid="trace-row"
      className="animate-trace-in border-l-2 pl-2"
      style={{ borderColor: rail ? `rgba(${rail},0.42)` : 'transparent' }}
    >
      <button
        type="button"
        onClick={() => hasDetail && setOpen((value) => !value)}
        aria-expanded={hasDetail ? open : undefined}
        disabled={!hasDetail}
        className={clsx(
          'flex w-full items-baseline gap-2 rounded px-1.5 py-[0.15rem] text-left font-mono text-[0.72rem] leading-relaxed transition-colors duration-100',
          hasDetail ? 'hover:bg-white/[0.05]' : 'cursor-default',
          open && 'bg-white/[0.05]',
        )}
      >
        <span className="tabnum shrink-0 text-cream-faint">{preciseTime(event.ts)}</span>
        <span className={clsx('w-[3.6rem] shrink-0', meta.className)}>{meta.tag}</span>
        {event.agent && (
          <span className="w-[4.2rem] shrink-0 truncate text-cream-faint">{event.agent}</span>
        )}
        <span
          className={clsx(
            'min-w-0 flex-1 text-cream-dim',
            open ? 'whitespace-pre-wrap break-words' : 'truncate',
          )}
        >
          {event.summary}
        </span>
        {event.request_id && (
          <span
            className="shrink-0 rounded px-1 text-[0.66rem]"
            style={{
              color: rail ? `rgba(${rail},0.85)` : undefined,
              background: rail ? `rgba(${rail},0.1)` : undefined,
            }}
            title={event.request_id}
          >
            {shortRequestId(event.request_id)}
          </span>
        )}
      </button>
      {open && hasDetail && <DetailTable dense detail={event.detail} className="my-1 ml-1" />}
    </li>
  )
}
