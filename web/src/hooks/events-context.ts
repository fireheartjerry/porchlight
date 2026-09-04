import { createContext } from 'react'
import type { ConnectionState, DemoProgress, TraceEvent } from '../types'

export interface EventsApi {
  /** Newest last. Capped at 500 (RING_SIZE). */
  events: TraceEvent[]
  status: ConnectionState
  paused: boolean
  setPaused: (paused: boolean) => void
  clear: () => void
  /** Latest `demo_progress` payload, or null when no run is in flight. */
  demoProgress: DemoProgress | null
  clearDemoProgress: () => void
  /** Epoch ms of the last frame received, heartbeats included. */
  lastEventAt: number | null
}

const noop = () => {}

export const EventsContext = createContext<EventsApi>({
  events: [],
  status: 'connecting',
  paused: false,
  setPaused: noop,
  clear: noop,
  demoProgress: null,
  clearDemoProgress: noop,
  lastEventAt: null,
})
