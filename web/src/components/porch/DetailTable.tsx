/**
 * The expandable "what actually happened" panel used by the Quiet Log rows and
 * the Trace drawer.
 *
 * Agent detail payloads are small, flat-ish JSON dicts (`{tool, confidence,
 * recipient_id, …}`). A raw `JSON.stringify` dump reads like a stack trace, so
 * scalars are laid out as a key/value table and only nested values fall back to
 * compact JSON. A "raw" toggle keeps the full payload one click away, because
 * during a demo somebody always asks.
 */

import clsx from 'clsx'
import { useState } from 'react'
import { humanise } from '../../lib/format'

function isScalar(value: unknown): value is string | number | boolean | null {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value)
}

function renderScalar(value: string | number | boolean | null): string {
  if (value === null) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

/** ISO timestamps, ids and long strings all want different treatment. */
function scalarTone(key: string, value: string | number | boolean | null): string {
  if (value === null) return 'text-cream-faint'
  if (typeof value === 'boolean') return value ? 'text-sage' : 'text-cream-faint'
  if (typeof value === 'number') return 'text-lamp-wash tabnum'
  if (/_id$/.test(key) || /^(id|tool|rule|model|node|action)$/.test(key)) return 'text-dusk'
  return 'text-cream-dim'
}

export function DetailTable({
  detail,
  className,
  dense,
}: {
  detail: Record<string, unknown>
  className?: string
  dense?: boolean
}) {
  const [raw, setRaw] = useState(false)
  const entries = Object.entries(detail)
  if (entries.length === 0) return null

  return (
    <div
      className={clsx(
        'rounded-xl border border-white/[0.07] bg-porch-950/60 px-3 py-2.5',
        dense ? 'text-[0.7rem]' : 'text-[0.74rem]',
        className,
      )}
    >
      {raw ? (
        <pre className="porch-scroll max-h-60 overflow-auto whitespace-pre-wrap break-words font-mono leading-relaxed text-cream-faint">
          {JSON.stringify(detail, null, 2)}
        </pre>
      ) : (
        <dl className="grid grid-cols-[minmax(5.5rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1">
          {entries.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="truncate text-cream-faint" title={key}>
                {humanise(key)}
              </dt>
              <dd
                className={clsx(
                  'min-w-0 break-words font-mono',
                  isScalar(value) ? scalarTone(key, value) : 'text-lilac/80',
                )}
              >
                {isScalar(value) ? renderScalar(value) : JSON.stringify(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <button
        type="button"
        onClick={() => setRaw((value) => !value)}
        className="mt-2 text-[0.66rem] uppercase tracking-[0.12em] text-cream-faint transition-colors hover:text-cream-dim"
      >
        {raw ? 'table' : 'raw json'}
      </button>
    </div>
  )
}
