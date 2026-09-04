# The Porch — UI spec (`web/`)

React 18 + Vite + TypeScript + Tailwind v3 (no component library; hand-built), `react-router` not needed (single page with
left nav state), `@tanstack/react-query` for data, native `EventSource` for SSE. Build output → `web/dist` (served by
CloudFront in prod; in dev, Vite proxies `/api` to `http://localhost:8000`).

## Personality
Warm night on a porch. Not a SaaS dashboard. Deep, slightly blue-black background (`#0b1020` → `#141a33` gradient),
warm amber accent (`#ffb347` glow, `#f59e0b` solid), off-white text (`#f4efe6`), muted sage for "handled quietly"
(`#8fb996`), soft red for safety (`#ff6b6b`). Typography: a humanist serif for headings (Fraunces via Google Fonts,
fallback Georgia) and Inter for body. Generous spacing, rounded-2xl cards, subtle grain/vignette. Motion: the porch-light
glyph (an SVG lantern in the header) is dim/grey when there are no open decisions and glows with a soft animated halo
(CSS keyframes, prefers-reduced-motion respected) when `light_on` is true. New Quiet Log rows slide in. Nothing bouncy.

## Layout
- Header: lantern glyph + "Porchlight" wordmark + group name; right side: status line from `/api/porch`
  ("Quiet. 14 handled today · 2 need you.") and a small "Live" dot tied to SSE connection state.
- Left nav (icons + labels): Porch, Requests, Volunteers, Inbox, Trace. Collapsible on narrow screens (bottom tab bar < 768px).

## Screens
1. **Porch** (default): two columns on desktop.
   - Left: "Needs you" — Decision Cards (open decisions). Card = kind badge (safety=red, money=amber, vetting=violet,
     unmatched=blue, concern=orange, policy=grey), title, context (markdown → simple renderer), "Porchlight recommends:"
     recommendation callout, option buttons (primary = recommended option), optional note textarea, resolve → POST
     `/api/decisions/{id}/resolve`; optimistic removal with toast "Resumed. Porchlight is back on it."
     Empty state: dim lantern illustration + "All quiet. Nothing needs you right now."
   - Right: "Handled quietly" — Quiet Log timeline grouped by request (LogEvent list), each row: time, agent chip
     (intake/matcher/outreach/steward), plain-English summary; expandable detail JSON. Filter chips: all / messages / matches / memory.
   - Top strip: 4 stat tiles from `stats` (handled autonomously today, open decisions, confirmed this week, volunteers active).
2. **Requests**: kanban columns New → Matching → Awaiting reply → Confirmed → Done/Escalated; card shows category icon,
   summary, requester first name, window, assigned volunteer, attempt dots (green accepted / grey declined / amber pending).
   Click → drawer with the full request, attempts timeline, messages (outbound + replies), and its log.
3. **Volunteers**: roster grid: avatar initials, name, zones, skills chips, weekly load bar (this_week/max_per_week),
   vetted check, memory notes ("prefers mornings; great with seniors") from `/api/volunteers`.
4. **Inbox** (demo console): textarea "Paste a message the group received…" with source select (form/sms/email/voicemail/paper),
   optional image upload (paper slip → base64), "Send to Porchlight" → POST `/api/inbox`; left column: sample messages from
   `/api/demo/samples` (label + expected badge quiet/card) click-to-fill; button "Run a Tuesday" → POST `/api/demo/run_day`
   {count: 12} with a progress bar fed by `demo_progress` SSE events; "Reset demo" → POST `/api/demo/reset`.
5. **Trace** (drawer, toggled from header or nav): live feed of SSE events (`node_start`, `tool_call`, `tool_result`,
   `model_call`, `decision`, `log`) rendered as a compact monospace stream with colored type tags and the request id;
   pause/clear; auto-scroll. This is the "see the agents think" panel for the demo video.

## Data layer
`web/src/api.ts`: typed client for every endpoint in docs/CONTRACTS.md §9 (types mirrored from porchlight/models.py in
`web/src/types.ts`). `useEvents()` hook: single EventSource to `/api/events`, invalidates react-query caches on
`decision`/`log`/`demo_progress` events, exposes the last 500 events for the Trace drawer.

## Dev without the backend
`web/dev/mock-api.mjs`: a zero-dependency Node HTTP server on :8000 implementing every endpoint with fixture data
(mirroring porchlight/sim/fixtures.py: same names/zones), fake SSE events every 2s, and stateful inbox/decisions so the
whole UI can be exercised. `npm run dev:mock` runs it alongside Vite.

## Quality
- Keyboard accessible, focus rings, aria labels on icon buttons, color contrast AA on dark.
- Responsive: desktop two-column; tablet/mobile stacked with bottom nav.
- `npm run build` must succeed with zero TS errors; `npm run lint` (eslint) clean.
