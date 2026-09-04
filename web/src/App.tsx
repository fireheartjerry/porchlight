import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Activity, ClipboardList, Home, Inbox as InboxIcon, UsersRound } from 'lucide-react'
import { useCallback, useEffect, useState, type ComponentType } from 'react'
import { getPorch, qk } from './api'
import { Dot } from './components/Badge'
import { Lantern } from './components/Lantern'
import { useEvents } from './hooks/useEvents'
import { Inbox } from './screens/Inbox'
import { Porch } from './screens/Porch'
import { Requests } from './screens/Requests'
import { TraceDrawer } from './screens/TraceDrawer'
import { Volunteers } from './screens/Volunteers'

type ScreenId = 'porch' | 'requests' | 'volunteers' | 'inbox'

const NAV: { id: ScreenId; label: string; icon: ComponentType<{ className?: string }> }[] = [
  { id: 'porch', label: 'Porch', icon: Home },
  { id: 'requests', label: 'Requests', icon: ClipboardList },
  { id: 'volunteers', label: 'Volunteers', icon: UsersRound },
  { id: 'inbox', label: 'Inbox', icon: InboxIcon },
]

function readHash(): ScreenId {
  const value = window.location.hash.replace(/^#\/?/, '')
  return NAV.some((item) => item.id === value) ? (value as ScreenId) : 'porch'
}

export default function App() {
  const [screen, setScreen] = useState<ScreenId>(readHash)
  const [traceOpen, setTraceOpen] = useState(false)
  const { status } = useEvents()

  const porch = useQuery({ queryKey: qk.porch, queryFn: getPorch, refetchInterval: 30_000 })
  const lightOn = porch.data?.light_on ?? false

  useEffect(() => {
    const onHashChange = () => setScreen(readHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // The whole night warms up when the porch light is on.
  useEffect(() => {
    document.documentElement.style.setProperty('--lamp-strength', lightOn ? '1' : '0.1')
  }, [lightOn])

  useEffect(() => {
    document.title = lightOn ? 'Porchlight — someone needs you' : 'Porchlight — all quiet'
  }, [lightOn])

  const go = useCallback((id: ScreenId) => {
    window.location.hash = `/${id}`
    setScreen(id)
  }, [])

  // `t` toggles the Trace drawer — unless you're typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return
      if (event.key === 't' || event.key === 'T') setTraceOpen((value) => !value)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-lamp focus:px-3 focus:py-2 focus:text-porch-950"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-30 border-b border-white/[0.07] bg-porch-900/85 backdrop-blur-xl">
        <div className="mx-auto flex h-[4.5rem] w-full max-w-[110rem] items-center gap-4 px-4 sm:px-6">
          <button
            type="button"
            onClick={() => go('porch')}
            className="flex min-w-0 items-center gap-3 rounded-xl pr-2 text-left"
            aria-label="Porchlight — go to the Porch"
          >
            <Lantern lit={lightOn} size={38} />
            <span className="min-w-0">
              <span className="block font-display text-[1.25rem] leading-none tracking-[-0.015em] text-cream">
                Porchlight
              </span>
              <span className="mt-1 block truncate text-[0.72rem] uppercase tracking-[0.16em] text-cream-faint">
                {porch.data?.group.name ?? 'Loading…'}
              </span>
            </span>
          </button>

          <div className="mx-auto hidden min-w-0 max-w-xl flex-1 px-4 text-center md:block">
            <p
              className={clsx(
                'truncate font-display text-[0.98rem] transition-colors duration-500',
                lightOn ? 'text-lamp-wash' : 'text-cream-dim',
              )}
              title={porch.data?.status_line}
            >
              {porch.data?.status_line ?? '…'}
            </p>
          </div>

          <div className="ml-auto flex items-center gap-2 md:ml-0">
            <span
              role="status"
              aria-label={`Live updates ${status}`}
              className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-[0.68rem] uppercase tracking-[0.14em] text-cream-faint sm:px-2.5"
              title={`SSE ${status}`}
            >
              <Dot
                className={clsx(
                  status === 'open' ? 'bg-sage' : status === 'connecting' ? 'bg-lamp' : 'bg-ember',
                )}
                pulse={status === 'open'}
              />
              <span className="hidden sm:inline">{status === 'open' ? 'Live' : status}</span>
            </span>
            <button
              type="button"
              onClick={() => setTraceOpen((value) => !value)}
              aria-pressed={traceOpen}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-[0.78rem] transition-colors duration-150',
                traceOpen
                  ? 'border-lamp/40 bg-lamp/12 text-lamp-glow'
                  : 'border-white/[0.1] bg-white/[0.03] text-cream-dim hover:border-white/20 hover:text-cream',
              )}
            >
              <Activity className="h-3.5 w-3.5" aria-hidden />
              Trace
              <kbd
                aria-hidden
                className="ml-0.5 hidden rounded border border-white/15 px-1 font-mono text-[0.62rem] text-cream-faint lg:inline"
              >
                t
              </kbd>
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[110rem] flex-1">
        <nav
          aria-label="Sections"
          className="sticky top-[4.5rem] hidden h-[calc(100dvh-4.5rem)] w-[15.5rem] shrink-0 flex-col gap-1 border-r border-white/[0.06] px-3 py-5 md:flex"
        >
          {NAV.map((item) => (
            <NavItem key={item.id} item={item} active={screen === item.id} onSelect={() => go(item.id)} />
          ))}
          <button
            type="button"
            onClick={() => setTraceOpen(true)}
            className={clsx(
              'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[0.9rem] transition-colors duration-150',
              traceOpen ? 'bg-white/[0.06] text-cream' : 'text-cream-dim hover:bg-white/[0.04] hover:text-cream',
            )}
          >
            <Activity className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
            Trace
          </button>

          <div className="mt-auto px-3 pb-1">
            <p className="text-pretty font-display text-[0.82rem] italic leading-relaxed text-cream-faint">
              “Runs the coordination. Lights up only when you’re needed.”
            </p>
          </div>
        </nav>

        <main id="main" className="min-w-0 flex-1">
          {screen === 'porch' && <Porch />}
          {screen === 'requests' && <Requests />}
          {screen === 'volunteers' && <Volunteers />}
          {screen === 'inbox' && <Inbox />}
        </main>
      </div>

      <nav
        aria-label="Sections"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-white/[0.08] bg-porch-900/92 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden"
      >
        {NAV.map((item) => {
          const Icon = item.icon
          const active = screen === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => go(item.id)}
              aria-current={active ? 'page' : undefined}
              className={clsx(
                'flex flex-1 flex-col items-center gap-1 py-2.5 text-[0.66rem] tracking-wide transition-colors',
                active ? 'text-lamp-glow' : 'text-cream-faint',
              )}
            >
              <Icon className="h-[1.15rem] w-[1.15rem]" />
              {item.label}
            </button>
          )
        })}
        <button
          type="button"
          onClick={() => setTraceOpen(true)}
          className={clsx(
            'flex flex-1 flex-col items-center gap-1 py-2.5 text-[0.66rem] tracking-wide transition-colors',
            traceOpen ? 'text-lamp-glow' : 'text-cream-faint',
          )}
        >
          <Activity className="h-[1.15rem] w-[1.15rem]" />
          Trace
        </button>
      </nav>

      <TraceDrawer open={traceOpen} onClose={() => setTraceOpen(false)} />
    </div>
  )
}

function NavItem({
  item,
  active,
  onSelect,
}: {
  item: { id: ScreenId; label: string; icon: ComponentType<{ className?: string }> }
  active: boolean
  onSelect: () => void
}) {
  const Icon = item.icon
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? 'page' : undefined}
      className={clsx(
        'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[0.9rem] transition-colors duration-150',
        active ? 'bg-white/[0.06] text-cream' : 'text-cream-dim hover:bg-white/[0.04] hover:text-cream',
      )}
    >
      {active && (
        <span
          aria-hidden
          className="absolute inset-y-2 left-0 w-[2px] rounded-full bg-lamp shadow-[0_0_12px_2px_rgba(255,179,71,0.5)]"
        />
      )}
      <Icon className={clsx('h-4 w-4 shrink-0', active ? 'text-lamp-glow' : 'opacity-80')} />
      {item.label}
    </button>
  )
}
