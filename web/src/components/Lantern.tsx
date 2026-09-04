import clsx from 'clsx'

interface LanternProps {
  /** True when there are open decisions: the light comes on. */
  lit: boolean
  size?: number
  className?: string
  /** Suppress the halo (for small inline uses and empty-state illustrations). */
  halo?: boolean
  title?: string
}

/**
 * The porch light. Dim and grey when nothing needs the coordinator; warm, haloed
 * and gently breathing when a decision is open. Motion respects
 * prefers-reduced-motion via the global media query in index.css.
 */
export function Lantern({ lit, size = 40, className, halo = true, title }: LanternProps) {
  // `title=""` marks a decorative lantern (the empty-state illustration): it
  // gets hidden from the a11y tree rather than announced with an empty name.
  const label = title ?? (lit ? 'Porch light on — a decision needs you' : 'Porch light off — all quiet')
  const decorative = label === ''

  return (
    <span
      data-lantern={lit ? 'lit' : 'dim'}
      className={clsx('relative inline-flex shrink-0 items-center justify-center', className)}
      style={{ width: size, height: size }}
    >
      {lit && halo && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-[-75%] rounded-full animate-lantern-glow"
          style={{
            background:
              'radial-gradient(circle, rgba(255,179,71,0.38) 0%, rgba(255,179,71,0.13) 38%, rgba(255,179,71,0) 68%)',
          }}
        />
      )}
      <svg
        viewBox="0 0 48 48"
        width={size}
        height={size}
        role={decorative ? undefined : 'img'}
        aria-label={decorative ? undefined : label}
        aria-hidden={decorative || undefined}
        className="relative"
        fill="none"
      >
        <defs>
          <linearGradient id="pl-flame" x1="24" y1="18" x2="24" y2="30" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#fff3d6" />
            <stop offset="0.45" stopColor="#ffb347" />
            <stop offset="1" stopColor="#f59e0b" />
          </linearGradient>
          <radialGradient id="pl-inner" cx="0.5" cy="0.42" r="0.6">
            <stop offset="0" stopColor="#ffb347" stopOpacity="0.55" />
            <stop offset="1" stopColor="#ffb347" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* hook and cap */}
        <g
          stroke={lit ? '#ffd9a0' : '#6c748c'}
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={lit ? 0.95 : 0.65}
        >
          <path d="M24 3.5v3.2" />
          <path d="M18.6 12.4 20.4 8.2h7.2l1.8 4.2" />
          <path d="M15.4 12.4h17.2" />
          {/* housing */}
          <path d="M17 12.4h14l1.4 20.2a2.2 2.2 0 0 1-2.2 2.4H17.8a2.2 2.2 0 0 1-2.2-2.4z" />
          {/* base */}
          <path d="M14.6 35h18.8l-1.3 3.4H15.9z" />
        </g>

        {/* glazing bars */}
        <g stroke={lit ? '#ffd9a0' : '#6c748c'} strokeWidth="0.9" opacity={lit ? 0.35 : 0.28}>
          <path d="M20.6 13.4 19.9 34" />
          <path d="M27.4 13.4 28.1 34" />
        </g>

        {/* the light inside */}
        {lit ? (
          <g className="animate-flicker">
            <ellipse cx="24" cy="24.4" rx="8" ry="9" fill="url(#pl-inner)" />
            <path
              d="M24 17.4c2.9 2.2 4.4 4.4 4.4 6.8 0 2.7-1.9 4.7-4.4 4.7s-4.4-2-4.4-4.7c0-2.4 1.5-4.6 4.4-6.8z"
              fill="url(#pl-flame)"
            />
            <ellipse cx="24" cy="24.8" rx="1.5" ry="2.1" fill="#fff6e2" opacity="0.9" />
          </g>
        ) : (
          <path
            d="M24 17.4c2.9 2.2 4.4 4.4 4.4 6.8 0 2.7-1.9 4.7-4.4 4.7s-4.4-2-4.4-4.7c0-2.4 1.5-4.6 4.4-6.8z"
            fill="#5b6480"
            opacity="0.5"
          />
        )}
      </svg>
    </span>
  )
}
