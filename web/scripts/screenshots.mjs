/**
 * Drives The Porch in headless Chromium and writes PNGs to docs/screenshots/.
 *
 *   node scripts/screenshots.mjs            # against http://localhost:5173
 *   BASE=http://localhost:5180 node scripts/screenshots.mjs
 *
 * Every shot is taken against the real API with a real evening behind it: the
 * script seeds by POSTing /api/demo/reset then /api/demo/run_day {count: 12},
 * and waits for the day to finish by polling /api/events/poll, so the porch is
 * photographed with a dozen requests' worth of quiet log rather than fixtures.
 *
 * It is also the visual regression harness: every step asserts the behaviour it
 * is photographing (lantern glow, Live dot, optimistic removal, toast, SSE
 * progress), so a green run means those actually work against the API.
 */
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(HERE, '../../docs/screenshots')
const BASE = process.env.BASE ?? 'http://localhost:5173'
const API = process.env.API ?? 'http://localhost:8000/api'

/** How many inbound messages a seeded evening runs through the graph. */
const DAY_COUNT = 12
/** A mock-provider day is seconds, not minutes; this is the safety net. */
const DAY_TIMEOUT_MS = 240_000

const checks = []
function check(name, ok, detail = '') {
  checks.push({ name, ok: Boolean(ok), detail })
  console.log(`${ok ? '  ok  ' : ' FAIL '} ${name}${detail ? ` — ${detail}` : ''}`)
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms))

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
  return res.json().catch(() => ({}))
}

async function resetDemo() {
  await post('/demo/reset')
}

async function getJson(path) {
  const res = await fetch(`${API}${path}`)
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json()
}

/**
 * Poll the porch until it stops changing.
 *
 * `demo_progress` rides the SSE bus and is never persisted, so the honest signal
 * that the background day has finished is the porch itself: the newest quiet-log
 * row and the counters stay put across three reads.
 */
async function waitForQuietPorch(deadline) {
  let previous = null
  let stable = 0
  while (Date.now() < deadline) {
    const porch = await getJson('/porch?log_limit=1')
    const newest = porch.quiet_log[0]?.id ?? ''
    const key = `${newest}|${porch.stats.handled_autonomously}|${porch.stats.decisions_open}`
    stable = key === previous ? stable + 1 : 0
    previous = key
    if (stable >= 2) return
    await sleep(800)
  }
  throw new Error('the porch never settled')
}

/**
 * Reset, run a day of `count` requests, and wait for it to land.
 *
 * `/api/demo/run_day` answers 202 and works in the background, so the wait is in
 * two parts: every request has to exist, and the porch has to stop moving.
 */
async function seedDay(count = DAY_COUNT) {
  await resetDemo()
  const before = (await getJson('/requests')).length
  const started = await post('/demo/run_day', { count })
  if (!started.started) throw new Error(`run_day refused: ${started.detail}`)

  const deadline = Date.now() + DAY_TIMEOUT_MS
  while (Date.now() < deadline) {
    if ((await getJson('/requests')).length >= before + count) break
    await sleep(600)
  }
  if (Date.now() >= deadline) {
    throw new Error(`demo day of ${count} requests did not finish within ${DAY_TIMEOUT_MS}ms`)
  }
  await waitForQuietPorch(deadline)
}

/** Settle: fonts loaded, no in-flight animation frame, give the lamp a beat. */
async function settle(page, ms = 550) {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(ms)
}

async function shoot(page, name, opts = {}) {
  const path = resolve(OUT, `${name}.png`)
  if (!opts.noScrollReset) await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(250)
  const { noScrollReset: _ignored, ...shot } = opts
  await page.screenshot({ path, ...shot })
  console.log(`  →   ${path}`)
}

async function main() {
  await mkdir(OUT, { recursive: true })
  await seedDay()

  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    // 1, not 2: these ship in the README and the Devpost page, and a 4x-heavier
    // PNG buys nothing that a reader of a repo page can see.
    deviceScaleFactor: 1,
    colorScheme: 'dark',
  })
  const page = await context.newPage()
  const consoleErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(String(err)))

  // ── 1. Porch, decisions waiting ───────────────────────────────────────────
  await page.goto(`${BASE}/#/porch`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: 'Needs you', exact: true }).waitFor()
  await page.getByTestId('decision-card').first().waitFor()
  await settle(page, 1200)

  const cardsBefore = await page.getByTestId('decision-card').count()
  check('porch shows open decision cards', cardsBefore >= 1, `${cardsBefore} card(s)`)

  const logRows = await page.getByTestId('quiet-row').count()
  check('quiet log filled by the seeded day', logRows >= 5, `${logRows} rows`)
  const toolish = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid="quiet-row"] p')).filter((p) =>
      /^[a-z_]+ (success|error|cancelled)$/.test((p.textContent ?? '').trim()),
    ).length,
  )
  check('no raw tool names on the porch', toolish === 0, `${toolish} row(s) look like tool calls`)

  const lampLit = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--lamp-strength').trim(),
  )
  check('lantern glow raised while decisions are open', lampLit === '1', `--lamp-strength: ${lampLit}`)
  check(
    'lantern halo animating',
    (await page.locator('[data-lantern="lit"]').count()) > 0,
    'header lantern in lit state',
  )

  await page.waitForFunction(
    () => /\blive\b/i.test(document.querySelector('header')?.innerText ?? ''),
    null,
    { timeout: 20_000 },
  )
  check('SSE Live dot connected', true, 'header reads "Live"')

  await shoot(page, '01-porch-decisions')

  // ── 2. Resolve one decision: optimistic removal + toast ───────────────────
  const cards = page.getByTestId('decision-card')
  const firstCardTitle = await cards.first().locator('h3').first().innerText()
  const option = cards.first().locator('[role="group"] button').first()
  const optionLabel = await option.innerText()
  await option.click()

  // Optimistic = the card is gone before the network settles.
  await page.waitForFunction(
    (title) =>
      !Array.from(document.querySelectorAll('[data-testid="decision-card"] h3')).some(
        (h) => h.textContent === title,
      ),
    firstCardTitle,
    { timeout: 2000 },
  )
  check('decision removed optimistically', true, `chose "${optionLabel.split('\n')[0]}"`)

  const live = page.locator('[aria-live="polite"]')
  await live.getByText(/Resumed\. Porchlight is back on it\./).waitFor({ timeout: 4000 })
  check('toast announced in aria-live region', true, '"Resumed. Porchlight is back on it."')

  await settle(page, 400)
  await shoot(page, '02-porch-after-resolve')

  // ── 3. Resolve the rest: empty state + lantern dims ───────────────────────
  for (let i = 0; i < 8; i += 1) {
    const remaining = await page.locator('[data-testid="decision-card"] [role="group"] button').count()
    if (remaining === 0) break
    await page.locator('[data-testid="decision-card"] [role="group"] button').first().click()
    await page.waitForTimeout(900)
  }
  await page.getByText('All quiet. Nothing needs you right now.').waitFor({ timeout: 12_000 })
  // Let the "Resumed" toasts expire so the empty porch is photographed, not the confetti.
  await page.waitForFunction(
    () => (document.querySelector('[aria-live="polite"]')?.childElementCount ?? 0) === 0,
    null,
    { timeout: 12_000 },
  )
  await page.waitForFunction(
    () => getComputedStyle(document.documentElement).getPropertyValue('--lamp-strength').trim() === '0.1',
    null,
    { timeout: 8000 },
  )
  check('lantern dims when nothing needs you', true, '--lamp-strength: 0.1')
  await settle(page, 700)
  await shoot(page, '03-porch-all-quiet')

  // ── 4. Requests board + drawer ────────────────────────────────────────────
  await seedDay()
  await page.goto(`${BASE}/#/requests`, { waitUntil: 'domcontentloaded' })
  await page.reload()
  await page.getByTestId('request-card').first().waitFor({ timeout: 15_000 })
  await settle(page, 900)
  const boardCards = await page.getByTestId('request-card').count()
  check('requests board rendered', boardCards >= 8, `${boardCards} card(s)`)
  await shoot(page, '04-requests-board')

  // The confirmed column has the interesting drawer: a volunteer, a reply, messages.
  const confirmed = page.getByTestId('request-card').filter({ hasText: /Confirmed|confirmed/ })
  const target = (await confirmed.count()) > 0 ? confirmed.first() : page.getByTestId('request-card').first()
  await target.click()
  await page.getByRole('dialog').waitFor({ timeout: 5000 })
  await settle(page, 900)
  check('request drawer opens', true)
  await shoot(page, '05-request-drawer')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)

  // ── 5. Volunteers ─────────────────────────────────────────────────────────
  await page.goto(`${BASE}/#/volunteers`, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('volunteer-card').first().waitFor({ timeout: 15_000 })
  await settle(page, 800)
  check('volunteer roster rendered', (await page.getByTestId('volunteer-card').count()) >= 6)
  await shoot(page, '06-volunteers')

  // ── 6. Inbox, mid "Run a Tuesday" (progress fed by demo_progress SSE) ─────
  await resetDemo()
  await page.goto(`${BASE}/#/inbox`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /Run a Tuesday/i }).waitFor()
  await settle(page, 600)
  await page.getByRole('button', { name: /Run a Tuesday/i }).click()
  const bar = page.locator('[role="progressbar"]')
  await bar.waitFor({ timeout: 10_000 })
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[role="progressbar"]')
      return el ? Number(el.getAttribute('aria-valuenow') ?? 0) > 15 : false
    },
    null,
    { timeout: 30_000 },
  )
  const moved = Number(await bar.getAttribute('aria-valuenow'))
  check('demo_progress SSE drives the progress bar', moved > 15, `${moved}%`)

  // A mock-provider evening is over in seconds, and the bar's width animates for
  // half a second after the label flips — so photograph the settled end state,
  // where the copy and the bar agree, rather than a torn mid-frame.
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[role="progressbar"]')
      return el ? Number(el.getAttribute('aria-valuenow') ?? 0) >= 100 : false
    },
    null,
    { timeout: 60_000 },
  )
  await page.getByText(/Tuesday done/).waitFor({ timeout: 5000 })
  check('the evening finishes and the panel says how it split', true, 'Tuesday done')
  // The "Running a Tuesday" toast would argue with the "Tuesday done" panel; let it go.
  await page.waitForFunction(
    () => (document.querySelector('[aria-live="polite"]')?.childElementCount ?? 0) === 0,
    null,
    { timeout: 12_000 },
  )
  await settle(page, 500)
  await shoot(page, '07-inbox-run-a-tuesday')

  // ── 7. Trace drawer, live stream ──────────────────────────────────────────
  await page.getByRole('button', { name: /^Trace/ }).first().click()
  await page.waitForTimeout(2500)
  // The drawer and the toasts share the top-right corner; the toasts are the transient one.
  await page.waitForFunction(
    () => (document.querySelector('[aria-live="polite"]')?.childElementCount ?? 0) === 0,
    null,
    { timeout: 12_000 },
  )
  const rows = await page.getByTestId('trace-row').count()
  check('trace drawer streaming events', rows > 5, `${rows} rows`)
  await settle(page, 400)
  await shoot(page, '08-trace-drawer')
  await page.keyboard.press('Escape')

  // ── 8. Mobile porch ───────────────────────────────────────────────────────
  await seedDay()
  const mobile = await context.newPage()
  await mobile.setViewportSize({ width: 390, height: 844 })
  await mobile.goto(`${BASE}/#/porch`, { waitUntil: 'domcontentloaded' })
  await mobile.getByTestId('decision-card').first().waitFor({ timeout: 15_000 })
  await settle(mobile, 1200)
  const overflow = await mobile.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  check('no horizontal overflow at 390px', overflow <= 0, `${overflow}px`)
  await shoot(mobile, '09-porch-mobile', { fullPage: false })
  await mobile.close()

  check('no console errors', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))

  await context.close()
  await browser.close()

  const failed = checks.filter((c) => !c.ok)
  console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
  if (failed.length) process.exitCode = 1
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
