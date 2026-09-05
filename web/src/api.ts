/**
 * Typed client for the Porchlight API (docs/CONTRACTS.md §9).
 *
 * Every call goes through `request()` so error handling, JSON parsing and the
 * base URL stay in one place. In dev, Vite proxies /api → http://localhost:8000
 * (either the FastAPI app or `dev/mock-api.mjs`).
 */

import type {
  Brief,
  Decision,
  DecisionResolution,
  DecisionStatus,
  EventsPage,
  Health,
  InboxSubmission,
  LogEvent,
  AidRequest,
  PorchSummary,
  RequestDetail,
  RequestStatus,
  RunOutcome,
  Sample,
  SweepOutcome,
  VolunteerWithLoad,
} from './types'

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  readonly status: number
  readonly body: string

  constructor(status: number, body: string, url: string) {
    super(`${status} on ${url}${body ? ` — ${body.slice(0, 200)}` : ''}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

function withQuery(path: string, query?: Query): string {
  if (!query) return `${API_BASE}${path}`
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`
}

async function request<T>(
  path: string,
  init?: RequestInit & { query?: Query; json?: unknown },
): Promise<T> {
  const { query, json, ...rest } = init ?? {}
  const url = withQuery(path, query)
  const headers = new Headers(rest.headers)
  headers.set('Accept', 'application/json')
  if (json !== undefined) headers.set('Content-Type', 'application/json')

  const response = await fetch(url, {
    ...rest,
    headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })

  if (!response.ok) {
    throw new ApiError(response.status, await response.text().catch(() => ''), url)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/* ------------------------------------------------------------------ reads */

export const getHealth = () => request<Health>('/health')

export const getPorch = () => request<PorchSummary>('/porch')

export const listRequests = (status?: RequestStatus) =>
  request<AidRequest[]>('/requests', { query: { status } })

export const getRequest = (id: string) => request<RequestDetail>(`/requests/${encodeURIComponent(id)}`)

export const listDecisions = (status: DecisionStatus | 'all' = 'open') =>
  request<Decision[]>('/decisions', { query: { status: status === 'all' ? undefined : status } })

export const listVolunteers = () => request<VolunteerWithLoad[]>('/volunteers')

export const listLog = (options?: { request_id?: string; limit?: number }) =>
  request<LogEvent[]>('/log', { query: { ...options } })

export const getBrief = (day?: string) => request<Brief>('/brief', { query: { day } })

export const getSamples = () => request<Sample[]>('/demo/samples')

/* ----------------------------------------------------------------- writes */

export const postInbox = (submission: InboxSubmission) =>
  request<RunOutcome>('/inbox', { method: 'POST', json: submission })

export const resolveDecision = (id: string, resolution: DecisionResolution) =>
  request<RunOutcome>(`/decisions/${encodeURIComponent(id)}/resolve`, {
    method: 'POST',
    json: resolution,
  })

export const runSweep = () => request<SweepOutcome>('/sweep', { method: 'POST' })

/**
 * Server-driven "Run a Tuesday", kept for the local dev server and `scripts/run_day.py`.
 * The UI drives the run itself (see `useDayRun`): a FastAPI background task does not
 * survive on Lambda, where the invocation ends the moment the HTTP response is written.
 */
export const runDay = (count = 12) =>
  request<{ started: boolean; count: number }>('/demo/run_day', { method: 'POST', json: { count } })

export const resetDemo = () => request<{ ok: boolean }>('/demo/reset', { method: 'POST' })

/* -------------------------------------------------------------------- SSE */

export const eventsUrl = (): string => `${API_BASE}/events`

/**
 * The polling twin of the SSE stream, used when `EventSource` cannot stay open —
 * a buffering proxy, a corporate middlebox, a browser that dropped the connection.
 * Pass the `cursor` from the previous page back as `since`.
 */
export const pollEvents = (since = 0, limit = 200) =>
  request<EventsPage>('/events/poll', { query: { since, limit } })

/* ------------------------------------------------------------ query keys */

export const qk = {
  health: ['health'] as const,
  porch: ['porch'] as const,
  requests: (status?: RequestStatus) => ['requests', status ?? 'all'] as const,
  request: (id: string) => ['request', id] as const,
  decisions: (status: DecisionStatus | 'all') => ['decisions', status] as const,
  volunteers: ['volunteers'] as const,
  log: (requestId?: string) => ['log', requestId ?? 'all'] as const,
  samples: ['samples'] as const,
  brief: (day?: string) => ['brief', day ?? 'today'] as const,
}
