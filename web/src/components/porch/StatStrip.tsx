/**
 * The four numbers across the top of the Porch (docs/UI.md, screen 1).
 *
 * The "Needs you" tile is the only one allowed to be loud: it carries the lamp
 * tint and the lantern glyph when the light is on, and goes flat when it isn't.
 */

import { CircleCheck, Sparkles, UsersRound } from 'lucide-react'
import { Lantern } from '../Lantern'
import { StatTile } from '../StatTile'
import type { PorchStats } from '../../types'

export function StatStrip({ stats }: { stats: PorchStats }) {
  const needsYou = stats.decisions_open
  const inFlight =
    (stats.requests_by_status.matching ?? 0) +
    (stats.requests_by_status.awaiting_reply ?? 0) +
    (stats.requests_by_status.new ?? 0) +
    (stats.requests_by_status.triaging ?? 0)

  return (
    <div className="stagger grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile
        label="Handled quietly"
        value={stats.handled_autonomously}
        hint={inFlight > 0 ? `${inFlight} more still in flight` : 'nobody was asked'}
        icon={<Sparkles className="h-4 w-4" aria-hidden />}
        accent="sage"
      />
      <StatTile
        label="Needs you"
        value={needsYou}
        hint={needsYou === 0 ? 'the light is off' : 'the porch light is on'}
        icon={<Lantern lit={needsYou > 0} size={20} halo={false} title="" />}
        accent={needsYou > 0 ? 'lamp' : 'none'}
      />
      <StatTile
        label="Confirmed"
        value={stats.confirmed_this_week}
        hint="this week, end to end"
        icon={<CircleCheck className="h-4 w-4" aria-hidden />}
      />
      <StatTile
        label="Volunteers out"
        value={stats.volunteers_active}
        hint="on a job in the last 7 days"
        icon={<UsersRound className="h-4 w-4" aria-hidden />}
      />
    </div>
  )
}
