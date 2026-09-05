/**
 * Screen 5 — the Trace drawer (docs/UI.md).
 *
 * The live SSE feed as a compact monospace stream: node starts, tool calls,
 * model calls, messages, cards. This is the "watch the agents think" panel for
 * the demo video, so it has to stay readable while forty events a second land
 * during "Run a Tuesday" — hence the type filters, the per-request rails, the
 * pause, and an auto-scroll that gets out of your way the moment you scroll up.
 */

import clsx from 'clsx'
import { ArrowDownToLine, Eraser, Pause, Play, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Dot } from '../components/Badge'
import { Button, IconButton } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { TraceRow } from '../components/trace/TraceRow'
import { matchesFilter, TRACE_FILTERS } from '../components/trace/traceStyles'
import { RING_SIZE, useEvents } from '../hooks/useEvents'

export function TraceDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { events, status, transport, paused, setPaused, clear } = useEvents()
  const [filterId, setFilterId] = useState<string>('all')
  const [pinned, setPinned] = useState(true)
  const scroller = useRef<HTMLDivElement>(null)

  const filter = TRACE_FILTERS.find((entry) => entry.id === filterId) ?? TRACE_FILTERS[0]!
  const shown = useMemo(
    () => (filter.types === null ? events : events.filter((event) => matchesFilter(event, filter))),
    [events, filter],
  )

  const counts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const entry of TRACE_FILTERS) {
      out[entry.id] = entry.types === null ? events.length : events.filter((event) => matchesFilter(event, entry)).length
    }
    return out
  }, [events])

  const toBottom = () => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
    setPinned(true)
  }

  useEffect(() => {
    const node = scroller.current
    if (!node || !open || paused || !pinned) return
    node.scrollTop = node.scrollHeight
  }, [shown, open, paused, pinned])

  // Opening the drawer should always land you on the newest line.
  useEffect(() => {
    if (!open) return
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
    setPinned(true)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className={clsx(
          'fixed inset-0 z-40 bg-porch-950/60 backdrop-blur-[2px] transition-opacity duration-300 lg:hidden',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />
      <aside
        aria-label="Trace"
        aria-hidden={!open}
        inert={!open}
        className={clsx(
          'fixed inset-y-0 right-0 z-40 flex w-full max-w-[34rem] flex-col border-l border-white/[0.08] bg-porch-950/94 shadow-[-30px_0_80px_-40px_rgba(0,0,0,0.9)] backdrop-blur-xl transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]',
          open ? 'translate-x-0' : 'pointer-events-none translate-x-full',
        )}
      >
        <header className="border-b border-white/[0.07] px-4 pb-2.5 pt-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-baseline gap-2.5">
              <h2 className="font-display text-[1.05rem] text-cream">Trace</h2>
              <span className="flex items-center gap-1.5 text-[0.7rem] uppercase tracking-[0.12em] text-cream-faint">
                <Dot
                  className={
                    status === 'open' ? 'bg-sage' : status === 'connecting' ? 'bg-lamp' : 'bg-ember'
                  }
                  pulse={status === 'open'}
                />
                {status === 'open' ? (transport === 'poll' ? 'live · polling' : 'live') : status}
              </span>
              <span className="tabnum truncate text-[0.7rem] text-cream-faint">
                {events.length}/{RING_SIZE}
              </span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button
                size="sm"
                variant={paused ? 'primary' : 'quiet'}
                icon={
                  paused ? (
                    <Play className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <Pause className="h-3.5 w-3.5" aria-hidden />
                  )
                }
                onClick={() => setPaused(!paused)}
              >
                {paused ? 'Resume' : 'Pause'}
              </Button>
              <IconButton label="Clear trace" icon={<Eraser className="h-4 w-4" />} onClick={clear} />
              <IconButton label="Close trace" icon={<X className="h-4 w-4" />} onClick={onClose} />
            </div>
          </div>

          <div
            className="mt-2.5 flex flex-wrap gap-1"
            role="group"
            aria-label="Filter trace events"
          >
            {TRACE_FILTERS.map((entry) => {
              const active = entry.id === filterId
              return (
                <button
                  key={entry.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setFilterId(entry.id)}
                  className={clsx(
                    'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-[0.2rem] text-[0.72rem] transition-colors duration-150',
                    active
                      ? 'border-lamp/40 bg-lamp/[0.12] text-lamp-wash'
                      : 'border-white/[0.08] bg-white/[0.02] text-cream-faint hover:border-white/20 hover:text-cream-dim',
                  )}
                >
                  {entry.label}
                  <span className={clsx('tabnum text-[0.66rem]', active ? 'text-lamp/80' : 'text-cream-faint')}>
                    {counts[entry.id] ?? 0}
                  </span>
                </button>
              )
            })}
          </div>
        </header>

        <div className="relative min-h-0 flex-1">
          <div
            ref={scroller}
            onScroll={(event) => {
              const node = event.currentTarget
              setPinned(node.scrollHeight - node.scrollTop - node.clientHeight < 40)
            }}
            className="porch-scroll h-full overflow-y-auto px-3 py-3"
          >
            {shown.length === 0 ? (
              <EmptyState
                compact
                title={events.length === 0 ? 'Nothing on the wire yet.' : 'Nothing of that kind yet.'}
                body={
                  events.length === 0
                    ? 'Send a message from the Inbox and the graph will narrate itself here.'
                    : undefined
                }
              />
            ) : (
              <ol className="space-y-[0.1rem]">
                {shown.map((event) => (
                  <TraceRow key={event.seq ?? `${event.ts}-${event.summary}`} event={event} />
                ))}
              </ol>
            )}
          </div>

          {!pinned && shown.length > 0 && (
            <button
              type="button"
              onClick={toBottom}
              className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-lamp/35 bg-porch-900/90 px-3 py-1.5 text-[0.74rem] text-lamp-wash shadow-halo backdrop-blur transition-colors hover:bg-porch-800/90"
            >
              <ArrowDownToLine className="h-3.5 w-3.5" aria-hidden />
              Jump to latest
            </button>
          )}
        </div>

        <footer className="border-t border-white/[0.07] px-4 py-2">
          {paused ? (
            <p className="text-center text-[0.72rem] text-lamp-glow">
              Paused — new events are still being collected.
            </p>
          ) : (
            <p className="text-center text-[0.7rem] text-cream-faint">
              {pinned ? 'Following the stream' : 'Scrolled back — auto-scroll paused'} · click a line for
              its payload
            </p>
          )}
        </footer>
      </aside>
    </>
  )
}
