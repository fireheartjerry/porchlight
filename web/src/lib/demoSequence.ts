/**
 * The order "Run a Tuesday" pushes the sample messages in.
 *
 * Mirrors `porchlight.sim.fixtures.demo_sequence` — the run is client-driven now, so the
 * ordering has to exist on this side too. A real Tuesday is mostly routine with the
 * occasional card, so the sequence interleaves the quiet samples with the ones that need a
 * person at QUIET_PER_CARD to one. That way a short run (6) still shows both halves of the
 * product instead of six ride requests in a row. Original order is kept within each group,
 * so the sequence is stable, and a count longer than the pile cycles it.
 */

import type { Sample } from '../types'

/** Quiet samples between each one that raises a card. Matches the Python constant. */
export const QUIET_PER_CARD = 3

export function demoSequence(samples: Sample[], count?: number): Sample[] {
  const quiet = samples.filter((sample) => sample.expected !== 'card')
  const cards = samples.filter((sample) => sample.expected === 'card')
  const ordered: Sample[] = []

  while (quiet.length > 0 || cards.length > 0) {
    for (let taken = 0; taken < QUIET_PER_CARD; taken += 1) {
      const next = quiet.shift()
      if (next) ordered.push(next)
    }
    const card = cards.shift()
    if (card) ordered.push(card)
  }

  if (count === undefined) return ordered
  if (ordered.length === 0) return []
  return Array.from({ length: Math.max(1, count) }, (_, index) => ordered[index % ordered.length]!)
}
