/**
 * Kind → colour/label/icon tables. One place, so a safety card is the same red
 * everywhere it appears.
 */

import {
  Baby,
  Banknote,
  Car,
  HeartHandshake,
  Languages,
  Laptop,
  Package,
  ScrollText,
  ShieldAlert,
  ShoppingBasket,
  UserCheck,
  UsersRound,
  UtensilsCrossed,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import type { AttemptOutcome, Category, DecisionKind, LogKind, RequestStatus } from '../types'

export interface Tone {
  /** Tailwind classes for a filled-ish badge on the night background. */
  chip: string
  /** Bare foreground colour, for dots and icons. */
  text: string
  /** rgb triple for inline glows. */
  rgb: string
  label: string
}

export const DECISION_TONES: Record<DecisionKind, Tone> = {
  safety: {
    chip: 'bg-ember/15 text-ember border-ember/35',
    text: 'text-ember',
    rgb: '255,107,107',
    label: 'Safety',
  },
  money: {
    chip: 'bg-lamp/15 text-lamp-glow border-lamp/35',
    text: 'text-lamp-glow',
    rgb: '245,158,11',
    label: 'Money',
  },
  vetting: {
    chip: 'bg-lilac/15 text-lilac border-lilac/35',
    text: 'text-lilac',
    rgb: '179,157,219',
    label: 'Vetting',
  },
  unmatched: {
    chip: 'bg-dusk/15 text-dusk border-dusk/35',
    text: 'text-dusk',
    rgb: '127,169,216',
    label: 'Unmatched',
  },
  concern: {
    chip: 'bg-rust/15 text-rust border-rust/35',
    text: 'text-rust',
    rgb: '240,137,74',
    label: 'Concern',
  },
  policy: {
    chip: 'bg-slate/15 text-slate border-slate/35',
    text: 'text-slate',
    rgb: '141,149,171',
    label: 'Policy',
  },
}

export const DECISION_ICONS: Record<DecisionKind, LucideIcon> = {
  safety: ShieldAlert,
  money: Banknote,
  vetting: UserCheck,
  unmatched: UsersRound,
  concern: ShieldAlert,
  policy: ScrollText,
}

export const CATEGORY_ICONS: Record<Category, LucideIcon> = {
  ride: Car,
  groceries: ShoppingBasket,
  meal: UtensilsCrossed,
  errand: Package,
  chore: Wrench,
  tech: Laptop,
  companionship: HeartHandshake,
  childcare: Baby,
  translate: Languages,
  other: Package,
}

/** Agent chips in the Quiet Log — each agent gets its own hue. */
export const AGENT_TONES: Record<string, string> = {
  intake: 'bg-dusk/12 text-dusk border-dusk/25',
  matcher: 'bg-lilac/12 text-lilac border-lilac/25',
  outreach: 'bg-lamp/12 text-lamp-glow border-lamp/25',
  steward: 'bg-sage/12 text-sage border-sage/25',
  brief: 'bg-cream/10 text-cream-dim border-white/15',
  policy: 'bg-ember/12 text-ember border-ember/25',
  system: 'bg-slate/12 text-slate border-slate/25',
}

export function agentTone(agent: string): string {
  return AGENT_TONES[agent] ?? AGENT_TONES.system!
}

export const LOG_KIND_LABELS: Record<LogKind, string> = {
  tool_call: 'action',
  message_sent: 'message',
  decision: 'decision',
  memory: 'memory',
  policy: 'policy',
  model: 'thinking',
}

export const STATUS_LABELS: Record<RequestStatus, string> = {
  new: 'New',
  triaging: 'Triaging',
  matching: 'Matching',
  awaiting_reply: 'Awaiting reply',
  confirmed: 'Confirmed',
  in_progress: 'In progress',
  completed: 'Done',
  escalated: 'Escalated',
  declined: 'Declined',
  cancelled: 'Cancelled',
}

export const STATUS_TONES: Record<RequestStatus, string> = {
  new: 'bg-white/[0.06] text-cream-dim border-white/15',
  triaging: 'bg-lilac/12 text-lilac border-lilac/25',
  matching: 'bg-dusk/12 text-dusk border-dusk/25',
  awaiting_reply: 'bg-lamp/12 text-lamp-glow border-lamp/25',
  confirmed: 'bg-sage/12 text-sage border-sage/25',
  in_progress: 'bg-sage/12 text-sage border-sage/25',
  completed: 'bg-white/[0.05] text-cream-dim border-white/12',
  escalated: 'bg-ember/12 text-ember border-ember/25',
  declined: 'bg-white/[0.04] text-cream-faint border-white/10',
  cancelled: 'bg-white/[0.04] text-cream-faint border-white/10',
}

export const ATTEMPT_TONES: Record<AttemptOutcome, string> = {
  accepted: 'bg-sage',
  declined: 'bg-white/25',
  pending: 'bg-lamp',
  counter: 'bg-dusk',
  concern: 'bg-rust',
  timeout: 'bg-white/15',
}

/** Board columns for the Requests screen (docs/UI.md screen 2). */
export const BOARD_COLUMNS: { id: string; label: string; statuses: RequestStatus[] }[] = [
  { id: 'new', label: 'New', statuses: ['new', 'triaging'] },
  { id: 'matching', label: 'Matching', statuses: ['matching'] },
  { id: 'awaiting', label: 'Awaiting reply', statuses: ['awaiting_reply'] },
  { id: 'confirmed', label: 'Confirmed', statuses: ['confirmed', 'in_progress'] },
  { id: 'done', label: 'Done / Escalated', statuses: ['completed', 'escalated', 'declined', 'cancelled'] },
]
