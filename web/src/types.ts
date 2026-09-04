/**
 * Porchlight domain types — mirrored from `porchlight/models.py` (docs/DESIGN.md §5,
 * docs/CONTRACTS.md §3). Field names match the Pydantic models exactly; the API
 * serialises them as-is.
 *
 * Two additions beyond the Python `Store.stats()` dict are marked below; the API is
 * expected to supply them for the Porch stat tiles (docs/UI.md, screen 1).
 */

/* ------------------------------------------------------------------ enums */

export type Category =
  | 'ride'
  | 'groceries'
  | 'meal'
  | 'errand'
  | 'chore'
  | 'tech'
  | 'companionship'
  | 'childcare'
  | 'translate'
  | 'other'

export type Urgency = 'low' | 'normal' | 'high' | 'emergency'

export type RequestStatus =
  | 'new'
  | 'triaging'
  | 'matching'
  | 'awaiting_reply'
  | 'confirmed'
  | 'in_progress'
  | 'completed'
  | 'escalated'
  | 'declined'
  | 'cancelled'

export type Source = 'form' | 'email' | 'sms' | 'voicemail' | 'paper' | 'api'

export type ReplyIntent = 'accept' | 'decline' | 'counter' | 'concern' | 'unclear'

export type DecisionKind = 'safety' | 'money' | 'vetting' | 'unmatched' | 'concern' | 'policy'

export type DecisionStatus = 'open' | 'resolved'

export type LogKind = 'tool_call' | 'message_sent' | 'decision' | 'memory' | 'policy' | 'model'

export type MessageStatus = 'queued' | 'scheduled' | 'sent' | 'delivered' | 'failed'

export type Recipient = 'volunteer' | 'requester' | 'coordinator'

export type AttemptOutcome = 'pending' | 'accepted' | 'declined' | 'counter' | 'concern' | 'timeout'

export type AgentName = 'intake' | 'matcher' | 'outreach' | 'steward' | 'brief' | 'policy' | 'system'

/* --------------------------------------------------------------- entities */

export interface AvailabilityWindow {
  /** 0 = Monday … 6 = Sunday, matching Python's `date.weekday()`. */
  weekday: number
  /** Local "HH:MM". */
  start: string
  end: string
}

export interface VolunteerStats {
  accepted: number
  declined: number
  completed: number
  no_show: number
  last_active: string | null
}

export interface Volunteer {
  id: string
  name: string
  phone: string | null
  email: string | null
  zones: string[]
  skills: string[]
  availability: AvailabilityWindow[]
  max_per_week: number
  vetted: boolean
  notes: string[]
  stats: VolunteerStats
}

export interface VolunteerLoad {
  this_week: number
  max_per_week: number
  last_active: string | null
}

/** `GET /api/volunteers` returns the roster with the derived weekly load attached. */
export interface VolunteerWithLoad extends Volunteer {
  load: VolunteerLoad
}

export interface Requester {
  id: string
  name: string
  contact: string
  zone: string | null
  address: string | null
  first_seen: string
  notes: string[]
  history_count: number
}

export interface Attempt {
  volunteer_id: string
  sent_at: string
  outcome: AttemptOutcome
  note: string | null
}

export interface AidRequest {
  id: string
  source: Source
  raw_text: string
  requester_id: string | null
  category: Category
  summary: string
  window_start: string | null
  window_end: string | null
  flexible: boolean
  location_zone: string | null
  constraints: string[]
  urgency: Urgency
  money_involved: boolean
  safety_flags: string[]
  first_time_requester: boolean
  status: RequestStatus
  assigned_volunteer_id: string | null
  attempts: Attempt[]
  created_at: string
  updated_at: string
}

export interface MatchCandidate {
  volunteer_id: string
  score: number
  rationale: string
}

export interface MatchPlan {
  request_id: string
  candidates: MatchCandidate[]
  confidence: number
  notes: string | null
}

export interface VolunteerReply {
  intent: ReplyIntent
  proposed_time: string | null
  concern_text: string | null
  confidence: number
}

export interface DecisionOption {
  id: string
  label: string
  description: string
}

export interface Decision {
  id: string
  request_id: string | null
  kind: DecisionKind
  title: string
  /** Markdown; rendered by `<Markdown>`. */
  context: string
  recommendation: string
  options: DecisionOption[]
  interrupt_id: string | null
  session_id: string | null
  node: string | null
  status: DecisionStatus
  resolved_option: string | null
  resolved_note: string | null
  created_at: string
  resolved_at: string | null
}

export interface LogEvent {
  id: string
  ts: string
  request_id: string | null
  agent: string
  kind: LogKind
  summary: string
  detail: Record<string, unknown>
  autonomous: boolean
}

export interface OutboundMessage {
  id: string
  request_id: string | null
  to: Recipient
  recipient_id: string | null
  channel: string
  body: string
  scheduled_for: string | null
  sent_at: string | null
  status: MessageStatus
}

export interface InboundReply {
  id: string
  request_id: string
  from_volunteer_id: string
  text: string
  received_at: string
}

export interface GroupSettings {
  name: string
  timezone: string
  /** [start_hour, end_hour] — quiet hours, local. */
  quiet_hours: [number, number]
  petty_cash_limit: number
  max_candidates: number
  escalate_hours_before_window: number
  confidence_threshold: number
  zones: string[]
}

/* ----------------------------------------------------------- API payloads */

export interface RunOutcome {
  request_id: string
  status: RequestStatus
  decisions_created: Decision[]
  log_events: number
  interrupted: boolean
  summary: string
}

export interface SweepOutcome {
  messages_sent: number
  escalated: string[]
  timed_out: string[]
  summary: string
}

export interface PorchStats {
  handled_autonomously: number
  decisions_open: number
  decisions_resolved: number
  requests_by_status: Partial<Record<RequestStatus, number>>
  /** Beyond `Store.stats()`; supplied by the API for the Porch stat tiles. */
  confirmed_this_week: number
  /** Beyond `Store.stats()`; volunteers with activity in the last 7 days. */
  volunteers_active: number
}

/** `GET /api/porch` */
export interface PorchSummary {
  status_line: string
  light_on: boolean
  open_decisions: Decision[]
  quiet_log: LogEvent[]
  stats: PorchStats
  group: GroupSettings
}

/** `GET /api/requests/{id}` */
export interface RequestDetail {
  request: AidRequest
  attempts: Attempt[]
  messages: OutboundMessage[]
  log: LogEvent[]
}

/** `POST /api/inbox` */
export interface InboxSubmission {
  text: string
  source: Source
  contact?: string
  image_base64?: string
}

/** `POST /api/decisions/{id}/resolve` */
export interface DecisionResolution {
  option_id: string
  note?: string
}

/** `GET /api/demo/samples` */
export interface Sample {
  id: string
  label: string
  text: string
  expected: 'quiet' | 'card'
  source?: Source
}

export interface Health {
  status: string
  mode: string
  version?: string
}

export interface Brief {
  markdown: string
}

/* ------------------------------------------------------------ SSE / trace */

export type TraceEventType =
  | 'node_start'
  | 'node_end'
  | 'tool_call'
  | 'tool_result'
  | 'model_call'
  | 'message'
  | 'decision'
  | 'log'
  | 'demo_progress'
  | 'heartbeat'

/** docs/CONTRACTS.md §7 — the shape pushed through `ctx.emit` and `/api/events`. */
export interface TraceEvent {
  type: TraceEventType
  ts: string
  request_id: string | null
  agent: string | null
  summary: string
  detail: Record<string, unknown>
  /** Assigned client-side on receipt so React lists have a stable key. */
  seq?: number
}

export interface DemoProgress {
  done: number
  total: number
  quiet: number
  cards: number
}

export type ConnectionState = 'connecting' | 'open' | 'closed'
