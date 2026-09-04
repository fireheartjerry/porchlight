/**
 * The pile a real group gets in a week, split by what Porchlight is expected to
 * do with it: carry it quietly, or stop and ask. Click one to load it into the
 * composer.
 */

import clsx from 'clsx'
import { useMemo } from 'react'
import { SectionLabel } from '../Card'
import { sourceMeta } from '../requests/sources'
import type { Sample } from '../../types'

export function SampleList({
  samples,
  activeId,
  onPick,
}: {
  samples: Sample[]
  activeId: string | null
  onPick: (sample: Sample) => void
}) {
  const groups = useMemo(() => {
    const quiet = samples.filter((sample) => sample.expected !== 'card')
    const cards = samples.filter((sample) => sample.expected === 'card')
    return [
      {
        id: 'quiet',
        title: 'Handled quietly',
        blurb: 'Routine asks. Porchlight matches, messages, confirms — you never hear about them.',
        rows: quiet,
      },
      {
        id: 'card',
        title: 'Wakes you up',
        blurb: 'Danger, money, vetting, a concern. The policy stops the graph and raises a card.',
        rows: cards,
      },
    ]
  }, [samples])

  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <section key={group.id}>
          <SectionLabel className="px-1" count={group.rows.length}>
            {group.title}
          </SectionLabel>
          <p className="mb-2 mt-1 px-1 text-[0.75rem] leading-snug text-cream-faint">{group.blurb}</p>
          <ul className="space-y-1.5">
            {group.rows.map((sample) => (
              <li key={sample.id}>
                <SampleRow sample={sample} active={activeId === sample.id} onPick={() => onPick(sample)} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function SampleRow({ sample, active, onPick }: { sample: Sample; active: boolean; onPick: () => void }) {
  const card = sample.expected === 'card'
  const Icon = sourceMeta(sample.source ?? 'form').icon

  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={active}
      className={clsx(
        'group flex w-full items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors duration-150',
        active
          ? 'border-lamp/40 bg-lamp/[0.08]'
          : 'border-white/[0.07] bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.05]',
      )}
    >
      <span
        aria-hidden
        className={clsx(
          'mt-0.5 shrink-0 rounded-md border p-1',
          card ? 'border-lamp/25 bg-lamp/10 text-lamp-glow' : 'border-white/[0.08] bg-white/[0.03] text-cream-faint',
        )}
      >
        <Icon className="h-3 w-3" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[0.82rem] font-medium text-cream">{sample.label}</span>
          <span
            className={clsx(
              'shrink-0 text-[0.62rem] uppercase tracking-[0.12em]',
              card ? 'text-lamp-glow' : 'text-sage',
            )}
          >
            {card ? 'card' : 'quiet'}
          </span>
        </span>
        <span className="mt-0.5 line-clamp-2 block text-[0.74rem] leading-snug text-cream-faint">
          {sample.text}
        </span>
      </span>
    </button>
  )
}
