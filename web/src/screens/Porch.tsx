/**
 * Screen 1 — the Porch (docs/UI.md).
 *
 * Left: what needs the coordinator, as Decision Cards. Right: everything
 * Porchlight already did without asking, as the Quiet Log. Top: the four
 * numbers. The whole screen is built so that the common case — nothing needs
 * you — still feels like something worth opening.
 */

import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight } from 'lucide-react'
import { getPorch, listRequests, qk } from '../api'
import { Card, SectionLabel } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { Lantern } from '../components/Lantern'
import { QueryState, Screen, Skeleton } from '../components/Screen'
import { DecisionCard } from '../components/porch/DecisionCard'
import { QuietLog } from '../components/porch/QuietLog'
import { StatStrip } from '../components/porch/StatStrip'
import { pluralise } from '../lib/format'
import type { PorchSummary } from '../types'

export function Porch() {
  const query = useQuery({ queryKey: qk.porch, queryFn: getPorch })
  const porch = query.data
  const open = porch?.open_decisions.length ?? 0

  return (
    <Screen
      title="The Porch"
      lede={
        porch
          ? open === 0
            ? 'Nothing is waiting on you. Here is what Porchlight did anyway.'
            : `${pluralise(open, 'thing')} ${open === 1 ? 'needs' : 'need'} you. Everything below was handled without asking.`
          : 'Reading the porch…'
      }
    >
      <QueryState
        isPending={query.isPending}
        error={query.error}
        skeleton={
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[0, 1, 2, 3].map((index) => (
                <Skeleton key={index} className="h-[6.5rem]" />
              ))}
            </div>
            <div className="grid gap-6 xl:grid-cols-2">
              <Skeleton className="h-72" />
              <Skeleton className="h-72" />
            </div>
          </div>
        }
      >
        {porch && <PorchBody porch={porch} />}
      </QueryState>
    </Screen>
  )
}

function PorchBody({ porch }: { porch: PorchSummary }) {
  // Only used to title the Quiet Log threads; a miss just falls back to the id.
  const requests = useQuery({
    queryKey: qk.requests(),
    queryFn: () => listRequests(),
    staleTime: 15_000,
  })

  const open = porch.open_decisions
  const autonomous = porch.quiet_log.filter((event) => event.autonomous).length

  return (
    <div className="space-y-6">
      <StatStrip stats={porch.stats} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.06fr)_minmax(0,0.94fr)]">
        <section aria-labelledby="needs-you" className="min-w-0 space-y-3">
          <SectionLabel className="px-1" count={open.length}>
            <span id="needs-you">Needs you</span>
          </SectionLabel>

          {open.length === 0 ? (
            <Card className="overflow-hidden">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-[radial-gradient(24rem_8rem_at_50%_130%,rgba(143,185,150,0.12),transparent_70%)]"
              />
              <EmptyState
                title="All quiet. Nothing needs you right now."
                body="Porchlight is running the coordination — parsing what comes in, picking volunteers, chasing replies. The light comes on the moment a real decision turns up."
                illustration={<Lantern lit={false} size={76} title="" />}
              />
            </Card>
          ) : (
            <div className="stagger space-y-3">
              {open.map((decision) => (
                <DecisionCard key={decision.id} decision={decision} />
              ))}
            </div>
          )}

          {open.length > 0 && (
            <p className="px-1 text-[0.76rem] leading-relaxed text-cream-faint">
              Each card is a paused run. Answering one hands control straight back to the agents.
            </p>
          )}
        </section>

        <section aria-labelledby="quiet-log" className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2 px-1">
            <SectionLabel count={porch.quiet_log.length}>
              <span id="quiet-log">Handled quietly</span>
            </SectionLabel>
            {autonomous > 0 && (
              <span className="inline-flex items-center gap-1 text-[0.72rem] text-sage/80">
                <ArrowUpRight className="h-3 w-3" aria-hidden />
                {autonomous} never reached you
              </span>
            )}
          </div>
          <QuietLog events={porch.quiet_log} requests={requests.data ?? []} />
        </section>
      </div>
    </div>
  )
}
