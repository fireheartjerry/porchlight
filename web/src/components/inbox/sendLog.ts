/**
 * What has been sent to Porchlight in this browser session, kept outside React
 * so the result panel survives a trip to the Requests board and back — during a
 * demo you want to walk into a request and come back to where you were.
 *
 * Read with `useSyncExternalStore(subscribeSends, getSends)`.
 */

import type { RunOutcome } from '../../types'

export interface SendRecord {
  /** Client-side id: two identical messages still key uniquely. */
  key: number
  at: string
  label: string
  outcome: RunOutcome
}

const LIMIT = 6

let records: SendRecord[] = []
let key = 0
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

export function pushSend(label: string, outcome: RunOutcome): void {
  key += 1
  records = [{ key, at: new Date().toISOString(), label, outcome }, ...records].slice(0, LIMIT)
  emit()
}

export function clearSends(): void {
  if (records.length === 0) return
  records = []
  emit()
}

export function getSends(): SendRecord[] {
  return records
}

export function subscribeSends(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
