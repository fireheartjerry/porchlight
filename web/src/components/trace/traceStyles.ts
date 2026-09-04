/**
 * Colour and label tables for the Trace drawer. Pure data — kept out of the
 * component files so react-refresh stays happy and the palette lives in one
 * place.
 */

import type { TraceEvent, TraceEventType } from '../../types'

export interface TypeMeta {
  /** Short fixed-width tag shown in the stream. */
  tag: string
  /** Foreground colour class for the tag. */
  className: string
  /** rgb triple, for the row's left rail. */
  rgb: string
}

export const TYPE_META: Record<TraceEventType, TypeMeta> = {
  node_start: { tag: 'node ▸', className: 'text-lamp-glow', rgb: '255,179,71' },
  node_end: { tag: 'node ◂', className: 'text-lamp/60', rgb: '245,158,11' },
  tool_call: { tag: 'tool →', className: 'text-dusk', rgb: '127,169,216' },
  tool_result: { tag: 'tool ←', className: 'text-sage', rgb: '143,185,150' },
  model_call: { tag: 'model', className: 'text-lilac', rgb: '179,157,219' },
  message: { tag: 'msg', className: 'text-cream', rgb: '244,239,230' },
  decision: { tag: 'card', className: 'text-ember', rgb: '255,107,107' },
  log: { tag: 'log', className: 'text-cream-faint', rgb: '141,149,171' },
  demo_progress: { tag: 'demo', className: 'text-rust', rgb: '240,137,74' },
  heartbeat: { tag: 'beat', className: 'text-slate', rgb: '141,149,171' },
}

export function typeMeta(type: TraceEventType): TypeMeta {
  return TYPE_META[type] ?? TYPE_META.log
}

export interface TraceFilter {
  id: string
  label: string
  types: TraceEventType[] | null
}

/** The segmented filter above the stream. `null` types = everything. */
export const TRACE_FILTERS: TraceFilter[] = [
  { id: 'all', label: 'All', types: null },
  { id: 'graph', label: 'Graph', types: ['node_start', 'node_end'] },
  { id: 'tools', label: 'Tools', types: ['tool_call', 'tool_result'] },
  { id: 'model', label: 'Model', types: ['model_call'] },
  { id: 'messages', label: 'Messages', types: ['message'] },
  { id: 'cards', label: 'Cards', types: ['decision'] },
  { id: 'log', label: 'Log', types: ['log', 'demo_progress'] },
]

export function matchesFilter(event: TraceEvent, filter: TraceFilter): boolean {
  return filter.types === null || filter.types.includes(event.type)
}

/**
 * A stable colour per request id, so two runs interleaved by "Run a Tuesday"
 * are still readable as two threads.
 */
const RAIL_HUES = ['255,179,71', '127,169,216', '143,185,150', '179,157,219', '240,137,74', '141,149,171']

export function railColour(requestId: string | null): string | null {
  if (!requestId) return null
  let hash = 0
  for (let index = 0; index < requestId.length; index += 1) {
    hash = (hash * 31 + requestId.charCodeAt(index)) >>> 0
  }
  return RAIL_HUES[hash % RAIL_HUES.length] ?? RAIL_HUES[0]!
}

/** "req_44dd55ee66" → "44dd55" — enough to tell threads apart at a glance. */
export function shortRequestId(requestId: string): string {
  const tail = requestId.replace(/^[a-z]+_/, '')
  return tail.slice(0, 6) || requestId.slice(-6)
}
