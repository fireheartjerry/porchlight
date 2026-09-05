/**
 * One EventSource for the whole app.
 *
 * `/api/events` streams the trace-event dicts described in docs/CONTRACTS.md §7.
 * This hook owns the single connection, keeps a 500-event ring buffer for the
 * Trace drawer, invalidates the react-query caches that each event type
 * invalidates, and exposes the connection state for the header's "Live" dot.
 *
 * SSE is the fast path and works through CloudFront, but a buffering proxy or a
 * dropped connection must not leave the Trace drawer blank for the rest of the
 * session. So the moment the stream errors the hook falls back to polling
 * `/api/events/poll` from the last cursor it saw, and keeps retrying SSE in the
 * background; whichever is working is reported as `transport`.
 *
 * Mounted once, in `<EventsProvider>` (see src/hooks/events-context.ts for the
 * context object itself, kept separate so this module only exports hooks).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { eventsUrl, pollEvents, qk } from '../api'
import type {
  ConnectionState,
  DemoProgress,
  EventTransport,
  TraceEvent,
  TraceEventType,
} from '../types'
import { EventsContext, type EventsApi } from './events-context'
import { useContext } from 'react'

export const RING_SIZE = 500

const KNOWN_TYPES: TraceEventType[] = [
  'node_start',
  'node_end',
  'tool_call',
  'tool_result',
  'model_call',
  'message',
  'decision',
  'log',
  'demo_progress',
  'heartbeat',
]

/** Publish at most ~8 times a second; a run_day burst can emit far faster than that. */
const FLUSH_MS = 120
const RECONNECT_MS = [1000, 2000, 4000, 8000, 15000]

/** How often the fallback asks `/api/events/poll` for whatever it has missed. */
const POLL_MS = 1500

/** Events per poll. The endpoint caps at 1000; this is one comfortable screenful of burst. */
const POLL_LIMIT = 200

function coerce(raw: unknown, fallbackType: TraceEventType | null): TraceEvent | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  const type = (typeof record.type === 'string' ? record.type : fallbackType) as
    | TraceEventType
    | undefined
  if (!type) return null
  return {
    type,
    ts: typeof record.ts === 'string' ? record.ts : new Date().toISOString(),
    request_id: typeof record.request_id === 'string' ? record.request_id : null,
    agent: typeof record.agent === 'string' ? record.agent : null,
    summary: typeof record.summary === 'string' ? record.summary : type.replace(/_/g, ' '),
    detail:
      typeof record.detail === 'object' && record.detail !== null
        ? (record.detail as Record<string, unknown>)
        : {},
    cursor: typeof record.cursor === 'number' ? record.cursor : null,
  }
}

function readProgress(detail: Record<string, unknown>): DemoProgress | null {
  const done = Number(detail.done ?? detail.completed ?? NaN)
  const total = Number(detail.total ?? detail.count ?? NaN)
  if (!Number.isFinite(done) || !Number.isFinite(total)) return null
  return {
    done,
    total,
    quiet: Number(detail.quiet ?? 0) || 0,
    cards: Number(detail.cards ?? 0) || 0,
  }
}

/**
 * Owns the connection. Call once (EventsProvider does); everywhere else use
 * `useEvents()` to read the shared value.
 */
export function useEventStream(): EventsApi {
  const queryClient = useQueryClient()

  const [events, setEvents] = useState<TraceEvent[]>([])
  const [status, setStatus] = useState<ConnectionState>('connecting')
  const [paused, setPaused] = useState(false)
  const [demoProgress, setDemoProgress] = useState<DemoProgress | null>(null)
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)
  const [transport, setTransport] = useState<EventTransport>('sse')

  /** Highest persisted-trace cursor seen, so the fallback resumes instead of replaying. */
  const cursor = useRef(0)

  const ring = useRef<TraceEvent[]>([])
  const pending = useRef(false)
  const flushTimer = useRef<number | null>(null)
  const seq = useRef(0)
  const pausedRef = useRef(paused)

  // react-query invalidation is debounced too: a burst of 40 log events should
  // cost one refetch, not forty.
  const dirty = useRef<Set<string>>(new Set())
  const invalidateTimer = useRef<number | null>(null)

  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  const flush = useCallback(() => {
    flushTimer.current = null
    if (!pending.current) return
    pending.current = false
    if (pausedRef.current) return
    setEvents(ring.current.slice())
  }, [])

  const scheduleFlush = useCallback(() => {
    pending.current = true
    if (flushTimer.current !== null) return
    flushTimer.current = window.setTimeout(flush, FLUSH_MS)
  }, [flush])

  const scheduleInvalidate = useCallback(
    (keys: string[]) => {
      for (const key of keys) dirty.current.add(key)
      if (invalidateTimer.current !== null) return
      invalidateTimer.current = window.setTimeout(() => {
        invalidateTimer.current = null
        const keys2 = Array.from(dirty.current)
        dirty.current.clear()
        for (const key of keys2) {
          if (key === 'porch') void queryClient.invalidateQueries({ queryKey: qk.porch })
          if (key === 'decisions') void queryClient.invalidateQueries({ queryKey: ['decisions'] })
          if (key === 'requests') void queryClient.invalidateQueries({ queryKey: ['requests'] })
          if (key === 'request') void queryClient.invalidateQueries({ queryKey: ['request'] })
          if (key === 'log') void queryClient.invalidateQueries({ queryKey: ['log'] })
          if (key === 'volunteers') void queryClient.invalidateQueries({ queryKey: qk.volunteers })
        }
      }, 250)
    },
    [queryClient],
  )

  const ingest = useCallback(
    (event: TraceEvent) => {
      seq.current += 1
      const stamped: TraceEvent = { ...event, seq: seq.current }
      if (typeof stamped.cursor === 'number' && stamped.cursor > cursor.current) {
        cursor.current = stamped.cursor
      }

      if (stamped.type !== 'heartbeat') {
        ring.current.push(stamped)
        if (ring.current.length > RING_SIZE) {
          ring.current.splice(0, ring.current.length - RING_SIZE)
        }
        scheduleFlush()
      }
      setLastEventAt(Date.now())

      switch (stamped.type) {
        case 'decision':
          scheduleInvalidate(['porch', 'decisions', 'requests', 'request'])
          break
        case 'log':
          scheduleInvalidate(['porch', 'log', 'request'])
          break
        case 'message':
          scheduleInvalidate(['request', 'log'])
          break
        case 'node_end':
          scheduleInvalidate(['requests', 'request', 'porch'])
          break
        case 'demo_progress': {
          const progress = readProgress(stamped.detail)
          if (progress) setDemoProgress(progress)
          scheduleInvalidate(['porch', 'requests', 'decisions', 'log', 'volunteers'])
          break
        }
        default:
          break
      }
    },
    [scheduleFlush, scheduleInvalidate],
  )

  useEffect(() => {
    let source: EventSource | null = null
    let retry = 0
    let retryTimer: number | null = null
    let closed = false

    const handle = (fallbackType: TraceEventType | null) => (message: MessageEvent<string>) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(message.data) as unknown
      } catch {
        return
      }
      const event = coerce(parsed, fallbackType)
      if (event) ingest(event)
    }

    const connect = () => {
      if (closed) return
      const next = new EventSource(eventsUrl())
      source = next

      next.onopen = () => {
        retry = 0
        setStatus('open')
        setTransport('sse')
      }
      // Frames with no `event:` field arrive as DOM "message" events, which is
      // also the DOM type for `event: message` — so onmessage covers both and
      // must not be double-registered via addEventListener.
      next.onmessage = handle(null)
      for (const type of KNOWN_TYPES) {
        if (type === 'message') continue
        next.addEventListener(type, handle(type))
      }

      next.onerror = () => {
        next.close()
        if (closed) return
        // Hand the trace to the polling fallback and keep trying to get the stream back.
        setTransport('poll')
        setStatus('connecting')
        const delay = RECONNECT_MS[Math.min(retry, RECONNECT_MS.length - 1)] ?? 15000
        retry += 1
        retryTimer = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closed = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      source?.close()
    }
  }, [ingest])

  // The fallback: only alive while the stream is not.
  useEffect(() => {
    if (transport !== 'poll') return
    let stopped = false
    let timer: number | null = null

    const tick = async () => {
      try {
        const page = await pollEvents(cursor.current, POLL_LIMIT)
        if (stopped) return
        for (const raw of page.events) {
          const event = coerce(raw, null)
          if (event) ingest(event)
        }
        if (page.cursor > cursor.current) cursor.current = page.cursor
        setStatus('open')
      } catch {
        if (!stopped) setStatus('closed')
      }
      if (!stopped) timer = window.setTimeout(() => void tick(), POLL_MS)
    }

    void tick()
    return () => {
      stopped = true
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [transport, ingest])

  // Publish whatever accumulated while paused, the moment we resume.
  useEffect(() => {
    if (!paused) setEvents(ring.current.slice())
  }, [paused])

  useEffect(
    () => () => {
      if (flushTimer.current !== null) window.clearTimeout(flushTimer.current)
      if (invalidateTimer.current !== null) window.clearTimeout(invalidateTimer.current)
    },
    [],
  )

  const clear = useCallback(() => {
    ring.current = []
    setEvents([])
  }, [])

  const clearDemoProgress = useCallback(() => setDemoProgress(null), [])

  return useMemo<EventsApi>(
    () => ({
      events,
      status,
      transport,
      paused,
      setPaused,
      clear,
      demoProgress,
      clearDemoProgress,
      lastEventAt,
    }),
    [events, status, transport, paused, clear, demoProgress, clearDemoProgress, lastEventAt],
  )
}

/** Read the shared stream. */
export function useEvents(): EventsApi {
  return useContext(EventsContext)
}
