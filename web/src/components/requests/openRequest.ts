/**
 * Which request has its case file open, kept just outside React so a different
 * screen can set it. The Inbox writes the id of a request it has just created,
 * flips the hash to #/requests, and the board opens the drawer on arrival.
 *
 * Read with `useSyncExternalStore(subscribeOpenRequest, getOpenRequest)`.
 */

type Listener = () => void

let current: string | null = null
const listeners = new Set<Listener>()

export function setOpenRequest(requestId: string | null): void {
  if (current === requestId) return
  current = requestId
  for (const listener of listeners) listener()
}

export function getOpenRequest(): string | null {
  return current
}

export function subscribeOpenRequest(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
