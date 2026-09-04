import type { ReactNode } from 'react'
import { EventsContext } from './events-context'
import { useEventStream } from './useEvents'

/** Mounts the single EventSource and shares it with the tree. */
export function EventsProvider({ children }: { children: ReactNode }) {
  const value = useEventStream()
  return <EventsContext.Provider value={value}>{children}</EventsContext.Provider>
}
