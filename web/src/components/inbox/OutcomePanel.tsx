/**
 * What came back from `POST /api/inbox`. The whole product argument fits in this
 * one panel: either the lantern stayed dark and the job is already moving, or it
 * lit up and here is exactly why.
 */

import clsx from 'clsx'
import { ArrowUpRight, ExternalLink } from 'lucide-react'
import { Badge } from '../Badge'
import { Button } from '../Button'
import { Lantern } from '../Lantern'
import { relativeTime } from '../../lib/format'
import { DECISION_TONES, STATUS_LABELS, STATUS_TONES } from '../../lib/kinds'
import type { SendRecord } from './sendLog'

export function OutcomePanel({
  record,
  onOpenRequest,
  onGoToPorch,
}: {
  record: SendRecord
  onOpenRequest: (requestId: string) => void
  onGoToPorch: () => void
}) {
  const { outcome } = record
  const lit = outcome.interrupted

  return (
    <div
      className={clsx(
        'porch-card animate-fade-up overflow-hidden px-5 py-4',
        lit ? 'border-lamp/30 bg-lamp/[0.05] shadow-halo' : 'border-sage/25 bg-sage/[0.04]',
      )}
    >
      <div className="flex items-start gap-3.5">
        <Lantern lit={lit} size={40} title="" />
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-[1.05rem] leading-tight text-cream">
            {lit ? 'The porch light is on.' : 'Handled quietly.'}
          </h3>
          <p className="mt-1 text-pretty text-[0.85rem] leading-snug text-cream-dim">{outcome.summary}</p>

          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <Badge toneClass={STATUS_TONES[outcome.status]}>
              {STATUS_LABELS[outcome.status] ?? outcome.status}
            </Badge>
            <span className="tabnum text-[0.73rem] text-cream-faint">
              {outcome.log_events} log {outcome.log_events === 1 ? 'entry' : 'entries'}
            </span>
            <span className="text-[0.73rem] text-cream-faint">· {relativeTime(record.at)}</span>
          </div>

          {outcome.decisions_created.length > 0 && (
            <ul className="mt-3 space-y-1.5 border-t border-white/[0.07] pt-3">
              {outcome.decisions_created.map((decision) => (
                <li key={decision.id} className="flex items-start gap-2.5">
                  <span
                    className={clsx(
                      'mt-0.5 shrink-0 rounded-md border px-1.5 py-[0.05rem] text-[0.62rem] uppercase tracking-[0.11em]',
                      DECISION_TONES[decision.kind]?.chip,
                    )}
                  >
                    {DECISION_TONES[decision.kind]?.label ?? decision.kind}
                  </span>
                  <span className="text-pretty text-[0.82rem] leading-snug text-cream-dim">
                    {decision.title}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-3.5 flex flex-wrap gap-2">
            {outcome.request_id && (
              <Button
                size="sm"
                icon={<ExternalLink className="h-3.5 w-3.5" aria-hidden />}
                onClick={() => onOpenRequest(outcome.request_id)}
              >
                Open the request
              </Button>
            )}
            {lit && (
              <Button
                size="sm"
                variant="primary"
                icon={<ArrowUpRight className="h-3.5 w-3.5" aria-hidden />}
                onClick={onGoToPorch}
              >
                Go to the Porch
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/** One line per earlier send this session — enough to retrace a demo run. */
export function OutcomeRow({
  record,
  onOpenRequest,
}: {
  record: SendRecord
  onOpenRequest: (requestId: string) => void
}) {
  const lit = record.outcome.interrupted
  return (
    <button
      type="button"
      onClick={() => record.outcome.request_id && onOpenRequest(record.outcome.request_id)}
      className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors duration-150 hover:bg-white/[0.04]"
    >
      <span
        aria-hidden
        className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', lit ? 'bg-lamp' : 'bg-sage')}
      />
      <span className="min-w-0 flex-1 truncate text-[0.78rem] text-cream-dim">{record.label}</span>
      <span
        className={clsx(
          'shrink-0 text-[0.66rem] uppercase tracking-[0.11em]',
          lit ? 'text-lamp-glow' : 'text-sage',
        )}
      >
        {lit ? 'card' : 'quiet'}
      </span>
      <span className="tabnum shrink-0 text-[0.7rem] text-cream-faint">{relativeTime(record.at)}</span>
    </button>
  )
}
