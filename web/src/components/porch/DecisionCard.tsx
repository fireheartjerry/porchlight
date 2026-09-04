/**
 * A Decision Card — a paused Strands interrupt, rendered as something a tired
 * coordinator can answer in one tap (docs/UI.md screen 1, docs/DESIGN.md §3).
 *
 * The card carries the kind's colour, the context the agent gathered, the
 * recommendation, and the options as full-width rows so the label and its
 * consequence are both readable before the tap. Resolving removes the card
 * optimistically and toasts "Resumed. Porchlight is back on it."
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight, Loader2, MessageSquarePlus, Sparkle } from 'lucide-react'
import { useState } from 'react'
import { qk, resolveDecision } from '../../api'
import { relativeTime } from '../../lib/format'
import { DECISION_ICONS, DECISION_TONES } from '../../lib/kinds'
import { useToast } from '../../hooks/useToast'
import type { Decision, DecisionOption, PorchSummary } from '../../types'
import { Badge } from '../Badge'
import { Card } from '../Card'
import { Markdown } from '../Markdown'

/** Options whose id reads like a refusal get the ember treatment. */
function isDeclining(option: DecisionOption): boolean {
  return /declin|close|refuse|no_/.test(option.id)
}

export function DecisionCard({ decision }: { decision: Decision }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [note, setNote] = useState('')
  const [noteOpen, setNoteOpen] = useState(false)
  const [chosen, setChosen] = useState<string | null>(null)

  const tone = DECISION_TONES[decision.kind]
  const Icon = DECISION_ICONS[decision.kind]

  const mutation = useMutation({
    mutationFn: (optionId: string) =>
      resolveDecision(decision.id, { option_id: optionId, note: note.trim() || undefined }),
    onMutate: async (optionId: string) => {
      setChosen(optionId)
      await queryClient.cancelQueries({ queryKey: qk.porch })
      const previous = queryClient.getQueryData<PorchSummary>(qk.porch)
      // Optimistic: the card leaves the porch immediately, and the light goes
      // out with it if it was the last one.
      queryClient.setQueryData<PorchSummary>(qk.porch, (current) => {
        if (!current) return current
        const open_decisions = current.open_decisions.filter((row) => row.id !== decision.id)
        return {
          ...current,
          open_decisions,
          light_on: open_decisions.length > 0,
          stats: { ...current.stats, decisions_open: open_decisions.length },
        }
      })
      return { previous }
    },
    onError: (error, _optionId, context) => {
      if (context?.previous) queryClient.setQueryData(qk.porch, context.previous)
      setChosen(null)
      toast.push({
        title: 'That didn’t go through.',
        description: error instanceof Error ? error.message : 'Try again in a moment.',
        tone: 'bad',
      })
    },
    onSuccess: (outcome) => {
      toast.push({
        title: 'Resumed. Porchlight is back on it.',
        description: outcome.summary,
        tone: 'good',
      })
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: qk.porch })
      void queryClient.invalidateQueries({ queryKey: ['decisions'] })
      void queryClient.invalidateQueries({ queryKey: ['requests'] })
      void queryClient.invalidateQueries({ queryKey: ['log'] })
    },
  })

  const busy = mutation.isPending

  return (
    <Card
      as="article"
      testId="decision-card"
      glow
      className={clsx('overflow-hidden transition-opacity duration-200', busy && 'opacity-70')}
      style={{ borderColor: `rgba(${tone.rgb},0.22)` }}
    >
      {/* The kind's colour bleeds in from the top corner — each card reads as its
          own hue before a single word is read. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-32"
        style={{
          background: `radial-gradient(28rem 9rem at 8% -30%, rgba(${tone.rgb},0.16), transparent 70%)`,
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px"
        style={{ background: `linear-gradient(90deg, transparent, rgba(${tone.rgb},0.65), transparent)` }}
      />

      <div className="relative px-5 pb-5 pt-4">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
          <Badge kind={decision.kind} icon={<Icon className="h-3 w-3" aria-hidden />}>
            {tone.label}
          </Badge>
          <span className="text-[0.72rem] text-cream-faint">
            raised {relativeTime(decision.created_at)}
          </span>
          {decision.node && (
            <span className="inline-flex items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.03] px-1.5 py-[0.05rem] font-mono text-[0.66rem] text-cream-faint">
              paused at {decision.node}
            </span>
          )}
        </div>

        <h3 className="mt-3 text-balance font-display text-[1.2rem] leading-[1.25] text-cream">
          {decision.title}
        </h3>

        <div className="mt-3">
          <Markdown>{decision.context}</Markdown>
        </div>

        <div className="mt-4 flex gap-3 rounded-xl border border-lamp/20 bg-lamp/[0.06] px-4 py-3">
          <Sparkle className="mt-[0.15rem] h-4 w-4 shrink-0 text-lamp-glow" aria-hidden />
          <div className="min-w-0">
            <p className="text-[0.66rem] font-semibold uppercase tracking-[0.15em] text-lamp-glow">
              Porchlight recommends
            </p>
            <p className="mt-1 text-pretty text-[0.875rem] leading-relaxed text-cream">
              {decision.recommendation}
            </p>
          </div>
        </div>

        <div className="mt-4">
          {noteOpen ? (
            <label className="block animate-slide-in">
              <span className="text-[0.68rem] font-semibold uppercase tracking-[0.13em] text-cream-faint">
                Note for the record
              </span>
              <textarea
                autoFocus
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={2}
                placeholder="Anything Porchlight should remember about this one…"
                className="porch-scroll mt-1.5 w-full resize-y rounded-xl border border-white/10 bg-porch-950/50 px-3 py-2 text-[0.85rem] leading-relaxed text-cream placeholder:text-cream-faint focus:border-lamp/40"
              />
            </label>
          ) : (
            <button
              type="button"
              onClick={() => setNoteOpen(true)}
              className="inline-flex items-center gap-1.5 text-[0.76rem] text-cream-faint transition-colors hover:text-cream-dim"
            >
              <MessageSquarePlus className="h-3.5 w-3.5" aria-hidden />
              Add a note
            </button>
          )}
        </div>

        <div className="mt-3 space-y-1.5" role="group" aria-label="How should Porchlight proceed?">
          {decision.options.map((option, index) => (
            <OptionRow
              key={option.id}
              option={option}
              recommended={index === 0}
              declining={isDeclining(option)}
              pending={busy && chosen === option.id}
              disabled={busy}
              onSelect={() => mutation.mutate(option.id)}
            />
          ))}
        </div>

        <p className="mt-3 text-[0.72rem] leading-relaxed text-cream-faint">
          Your answer resumes the paused run
          {decision.node ? ` at ${decision.node}` : ''}
          {decision.request_id ? (
            <>
              {' · '}
              <span className="font-mono text-cream-faint">{decision.request_id}</span>
            </>
          ) : null}
        </p>
      </div>
    </Card>
  )
}

function OptionRow({
  option,
  recommended,
  declining,
  pending,
  disabled,
  onSelect,
}: {
  option: DecisionOption
  recommended: boolean
  declining: boolean
  pending: boolean
  disabled: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      title={option.description}
      className={clsx(
        'group flex w-full items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-[background-color,border-color,transform] duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60',
        recommended
          ? 'border-lamp/45 bg-lamp/[0.1] hover:bg-lamp/[0.16]'
          : declining
            ? 'border-white/[0.09] bg-white/[0.02] hover:border-ember/35 hover:bg-ember/[0.07]'
            : 'border-white/[0.09] bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.06]',
      )}
    >
      <span className="min-w-0 flex-1">
        <span
          className={clsx(
            'block text-[0.9rem] font-medium leading-snug',
            recommended ? 'text-lamp-wash' : declining ? 'text-cream group-hover:text-ember' : 'text-cream',
          )}
        >
          {option.label}
        </span>
        <span className="mt-0.5 block text-pretty text-[0.76rem] leading-snug text-cream-faint">
          {option.description}
        </span>
      </span>
      {recommended && !pending && (
        <span className="hidden shrink-0 rounded-full border border-lamp/30 px-2 py-[0.1rem] text-[0.6rem] uppercase tracking-[0.12em] text-lamp-glow sm:inline">
          recommended
        </span>
      )}
      {pending ? (
        <Loader2 aria-hidden className="h-4 w-4 shrink-0 animate-spin text-lamp-glow" />
      ) : (
        <ArrowRight
          aria-hidden
          className={clsx(
            'h-4 w-4 shrink-0 transition-transform duration-150 group-hover:translate-x-0.5',
            recommended ? 'text-lamp-glow' : 'text-cream-faint',
          )}
        />
      )}
    </button>
  )
}
