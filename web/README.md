# The Porch — Porchlight web UI

React 18-era stack: **Vite + React + TypeScript (strict) + Tailwind v3**, `@tanstack/react-query`
for data, native `EventSource` for the live trace. No component library — everything is hand-built
so the "warm night on a porch" language stays consistent (see `docs/UI.md`).

## Scripts

| command | what it does |
|---|---|
| `npm run dev` | Vite on :5173, proxying `/api` → `http://localhost:8000` (the FastAPI app) |
| `npm run dev:mock` | the same, plus `dev/mock-api.mjs` on :8000 — **no Python needed** |
| `npm run build` | `tsc -b && vite build` → `dist/` |
| `npm run lint` | eslint (typescript-eslint + react-hooks), zero warnings expected |
| `npm run preview` | serve the production build |
| `npm run shots` | drives a headless Chromium through every screen, asserts the live behaviour, writes `docs/screenshots/*.png` |
| `npm run a11y` | axe-core (WCAG 2.1 A/AA) on every screen and overlay + a tab-order sweep |
| `npm run contrast` | samples the *painted* pixels behind each text node and reports anything under AA |

The three audit scripts need the app running (`npm run dev:mock` in another shell);
point them elsewhere with `BASE=http://localhost:5180 npm run shots`.

## Environment

| variable | default | meaning |
|---|---|---|
| `VITE_API_BASE` | `/api` | where the client sends every request. Leave it unset in dev (Vite proxies `/api` to :8000) and in prod when the API is same-origin behind CloudFront. Set it — e.g. `VITE_API_BASE=https://api.example.com/api` — only when the API lives on another origin; the value is baked in at build time and the SSE stream (`$VITE_API_BASE/events`) follows it, so that origin must send CORS headers. |

Start here: `npm install && npm run dev:mock`, then open http://localhost:5173. Nothing else is
required — no Python, no AWS, no keys.

Press <kbd>t</kbd> anywhere to open the Trace drawer, <kbd>Esc</kbd> to close it or any drawer.

## Layout

```
src/
  api.ts             typed client for every endpoint in docs/CONTRACTS.md §9 + query keys (`qk`)
  types.ts           domain types mirrored from porchlight/models.py
  hooks/
    useEvents.ts     the single EventSource: 500-event ring buffer, reconnect, query invalidation
    EventsProvider.tsx / events-context.ts
    useToast.ts
  components/        Lantern, Card, Badge, Button, StatTile, EmptyState, Markdown, Screen, Toast
  lib/
    format.ts        relative time, windows, initials
    kinds.ts         decision-kind / status / agent colour tables, board columns, category icons
  screens/           Porch, Requests, Volunteers, Inbox, TraceDrawer
  App.tsx            shell: header (lantern + status + Live dot), left rail, mobile tab bar
dev/
  mock-api.mjs       zero-dependency stateful mock of the whole API, incl. SSE
  fixtures.mjs       14 volunteers, 8 requesters, 12 requests, decisions, log, 24 samples
scripts/
  screenshots.mjs    playwright: screenshots + behavioural assertions (see below)
  a11y.mjs           playwright + axe-core
  contrast.mjs       playwright: pixel-sampled contrast audit
```

## What `npm run shots` proves

It is the regression harness as much as the screenshot generator — each step asserts the
behaviour it photographs, so a green run means these actually work against the API:

- the porch light: `--lamp-strength` is `1` while a decision is open and drops to `0.1` when the
  last card clears, and the header lantern carries the lit halo
- the SSE connection: the header reads **Live** within 20s of load
- resolving a decision removes the card *before* the request settles (optimistic), rolls the
  toast into the `aria-live` region, and the empty state takes over
- `demo_progress` SSE drives the "Run a Tuesday" progress bar off the real event stream
- the trace drawer fills from the live ring buffer
- no horizontal overflow at 390px, and no console errors anywhere

Output lands in `docs/screenshots/`: `01-porch-decisions`, `02-porch-after-resolve`,
`03-porch-all-quiet`, `04-requests-board`, `05-request-drawer`, `06-volunteers`,
`07-inbox-run-a-tuesday`, `08-trace-drawer`, `09-porch-mobile`.

## Conventions for the screen builders

- **Fetch through `src/api.ts`**, never `fetch()` directly, and key queries with `qk.*` so the SSE
  invalidation in `useEvents.ts` reaches them.
- **Colour comes from `lib/kinds.ts`** (`DECISION_TONES`, `STATUS_TONES`, `AGENT_TONES`,
  `ATTEMPT_TONES`). Don't hand-roll a red.
- **Agent-authored text goes through `<Markdown>`** — it builds React nodes, never HTML, so
  model output can't inject markup.
- Motion: keep it slow and warm. Everything is gated by the `prefers-reduced-motion` block in
  `index.css`.
- Icon-only controls use `<IconButton label="…">`; that label is the accessible name.
- The porch light: `--lamp-strength` on `<html>` is raised by `App.tsx` when `light_on` is true,
  which warms the whole background. Don't fight it with local backgrounds.

## Mock API notes

`dev/mock-api.mjs` is stateful for the life of the process:

- `POST /api/inbox` really creates a request and streams `node_start` / `tool_call` / `tool_result` /
  `model_call` / `message` / `log` over ~4s, then confirms it — unless the text trips the policy
  (words like *alone*, *stove*, *chest pain*, *bill*, *money*, *gift card*), in which case it raises a
  Decision Card and returns `interrupted: true`.
- `POST /api/decisions/{id}/resolve` resolves the card and moves the request on.
- `POST /api/demo/run_day` walks 12 requests over ~20s, emitting `demo_progress`.
- `POST /api/demo/reset` reseeds the fixtures.
- `GET /api/events` is SSE with a 15s heartbeat.

Fixture names/zones follow `docs/DESIGN.md` ("Maple Street Mutual Aid"); reconcile with
`porchlight/sim/fixtures.py` when that module lands.
