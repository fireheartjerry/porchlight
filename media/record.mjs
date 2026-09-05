/**
 * Shots 3–6 of the demo video: the real Porch, driven by Playwright, recorded
 * as one .webm per shot.
 *
 *   node media/record.mjs                       # API :8000, UI :5173
 *   BASE=http://localhost:5180 node media/record.mjs
 *   ONLY=05-safety node media/record.mjs        # re-shoot one clip
 *
 * Nothing here is faked: every clip starts from `POST /api/demo/reset` and then
 * types into the same composer a coordinator would, against the same FastAPI
 * app, with PORCHLIGHT_MODEL_PROVIDER=mock behind it.
 *
 * Pacing. The mock provider answers in under a tenth of a second, so a clip's
 * length is set by the voiceover, not by the machine. Each shot is driven by a
 * Pacer built from that shot's narration: `pace.until(0.4)` means "hold here
 * until we are 40% of the way through what the narrator is saying". So the
 * picture and the words stay in step even when the script is re-timed — and
 * because the pacer prefers real durations from media/out/vo/durations.json
 * when a previous `make video` left them behind, the second run of the pipeline
 * is frame-accurate rather than merely close.
 *
 * Output: media/out/clips/<shot>.webm plus media/out/clips.json, which records
 * how much dead air at the head of each clip (browser paint, first data)
 * media/assemble.py should trim off.
 */
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from './lib/browser.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(process.env.MEDIA_OUT ?? join(HERE, 'out'))
const CLIPS = join(OUT, 'clips')
const BASE = process.env.BASE ?? 'http://localhost:5173'
const API = process.env.API ?? 'http://localhost:8000/api'
const ONLY = process.env.ONLY ?? ''

/** The screencast size — 1440×900, scaled by ~3% into the 1920×1080 plate. */
const SIZE = { width: 1440, height: 900 }

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
  return res.json().catch(() => ({}))
}

// ── pacing ────────────────────────────────────────────────────────────────────

/** Wall-clock metronome for one shot, in units of "fraction of the narration". */
class Pacer {
  constructor(page, target) {
    this.page = page
    this.target = target
    this.t0 = Date.now()
  }

  get elapsed() {
    return (Date.now() - this.t0) / 1000
  }

  /** Hold until `fraction` of the narration has gone by. Never rewinds. */
  async until(fraction) {
    const wait = this.target * fraction - this.elapsed
    if (wait > 0) await this.page.waitForTimeout(Math.round(wait * 1000))
  }
}

/**
 * A slow, readable scroll — `steps` nudges of `delta` pixels spread over the
 * clip's own clock, so the eye can follow a Quiet Log rather than chase it.
 */
async function creep(page, { selector = null, delta = 90, steps = 8, gap = 500 } = {}) {
  for (let i = 0; i < steps; i += 1) {
    await page.evaluate(
      ({ selector, delta }) => {
        const node = selector ? document.querySelector(selector) : null
        if (node) node.scrollBy({ top: delta, behavior: 'smooth' })
        else window.scrollBy({ top: delta, behavior: 'smooth' })
      },
      { selector, delta },
    )
    await page.waitForTimeout(gap)
  }
}

/** Put the mouse somewhere harmless so no hover state is frozen into the frame. */
async function parkMouse(page) {
  await page.mouse.move(30, 880)
}

// ── the shots ────────────────────────────────────────────────────────────────

const DIALYSIS =
  "Hi, it's Ezra Okafor's daughter. My mom needs a ride to dialysis Thursday at 7am " +
  'on Riverside, back around 11. She uses a walker. Thank you.'

const SAFETY =
  "My neighbour's kid is home alone next door and I can smell gas. " +
  "Nobody is answering the door and I don't know what to do."

/** Type into the composer the way a person does, then send. */
async function compose(page, text, { delay = 42 } = {}) {
  const box = page.getByPlaceholder('Paste a message the group received…')
  await box.click()
  await box.pressSequentially(text, { delay })
  await page.waitForTimeout(700)
  await page.getByRole('button', { name: /Send to Porchlight/i }).click()
}

const SHOTS = [
  {
    id: '03-porch-quiet',
    /** Reset first: the shot is *about* an empty porch. */
    before: () => post('/demo/reset'),
    async run(page, pace) {
      await page.goto(`${BASE}/#/porch`, { waitUntil: 'domcontentloaded' })
      await page.getByText('All quiet. Nothing needs you right now.').waitFor({ timeout: 20_000 })
      await page.waitForFunction(
        () => /\blive\b/i.test(document.querySelector('header')?.innerText ?? ''),
        null,
        { timeout: 20_000 },
      )
      await parkMouse(page)
      return async () => {
        // Let the lamp breathe: the dim lantern, the stat tiles at zero, and the
        // status line that says nothing needs anyone.
        await pace.until(0.55)
        await creep(page, { delta: 120, steps: 3, gap: 700 })
        await pace.until(1)
      }
    },
  },

  {
    id: '04-dialysis',
    async run(page, pace) {
      await page.goto(`${BASE}/#/inbox`, { waitUntil: 'domcontentloaded' })
      await page.getByPlaceholder('Paste a message the group received…').waitFor({ timeout: 20_000 })
      await parkMouse(page)
      return async () => {
        // 0 → 0.20: the message arrives, in ordinary English, typed out.
        await compose(page, DIALYSIS)
        await page.getByText(/Handled quietly\.|Handled without you/).first().waitFor({ timeout: 20_000 })
        await pace.until(0.16)

        // 0.16 → 0.62: the trace, read top to bottom — intake, matcher, outreach, steward.
        await page.getByRole('button', { name: /^Trace/ }).first().click()
        await page.getByTestId('trace-row').first().waitFor({ timeout: 10_000 })
        await parkMouse(page)
        await page.waitForTimeout(900)
        await page.evaluate(() => {
          document.querySelector('aside[aria-label="Trace"] .porch-scroll')?.scrollTo({ top: 0 })
        })
        await pace.until(0.24)
        await creep(page, { selector: 'aside[aria-label="Trace"] .porch-scroll', delta: 120, steps: 14, gap: 1150 })
        await pace.until(0.62)

        // 0.62 → 0.78: close the trace; the Inbox says how it went.
        await page.keyboard.press('Escape')
        await page.waitForTimeout(700)
        await pace.until(0.78)

        // 0.78 → 1: it lands in the Quiet Log, in plain English.
        await page.goto(`${BASE}/#/porch`, { waitUntil: 'domcontentloaded' })
        await page.getByTestId('quiet-row').first().waitFor({ timeout: 15_000 })
        await parkMouse(page)
        await pace.until(0.86)
        await creep(page, { delta: 130, steps: 5, gap: 800 })
        await pace.until(1)
      }
    },
  },

  {
    id: '05-safety',
    async run(page, pace) {
      await page.goto(`${BASE}/#/inbox`, { waitUntil: 'domcontentloaded' })
      await page.getByPlaceholder('Paste a message the group received…').waitFor({ timeout: 20_000 })
      await parkMouse(page)
      return async () => {
        // 0 → 0.22: a very different message, and the light comes on.
        await compose(page, SAFETY)
        await page.getByText('The porch light is on.').first().waitFor({ timeout: 20_000 })
        await parkMouse(page)
        await pace.until(0.22)

        // 0.22 → 0.72: the Decision Card — context, recommendation, options.
        await page.goto(`${BASE}/#/porch`, { waitUntil: 'domcontentloaded' })
        const card = page.getByTestId('decision-card').first()
        await card.waitFor({ timeout: 15_000 })
        await parkMouse(page)
        await pace.until(0.4)
        await creep(page, { delta: 90, steps: 4, gap: 900 })
        await pace.until(0.72)

        // 0.72 → 1: "I'll handle this" — the graph resumes where it paused.
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
        await page.waitForTimeout(600)
        const choice = card.getByRole('button', { name: /I'll handle this|I’ll handle this/ }).first()
        await choice.scrollIntoViewIfNeeded()
        await choice.hover()
        await page.waitForTimeout(600)
        await choice.click()
        await page.getByText('Resumed. Porchlight is back on it.').first().waitFor({ timeout: 15_000 })
        await parkMouse(page)
        await pace.until(1)
      }
    },
  },

  {
    id: '06-tuesday',
    before: () => post('/demo/reset'),
    async run(page, pace) {
      await page.goto(`${BASE}/#/inbox`, { waitUntil: 'domcontentloaded' })
      const run = page.getByRole('button', { name: /Run a Tuesday/i })
      await run.waitFor({ timeout: 20_000 })
      return async () => {
        // 0 → 0.28: twelve requests, start to finish. The bar is over in a blink,
        // which is exactly what the narration says.
        await pace.until(0.06)
        await run.hover()
        await page.waitForTimeout(400)
        await run.click()
        await page.getByText(/Tuesday done/).waitFor({ timeout: 90_000 })
        await parkMouse(page)
        await pace.until(0.3)

        // 0.3 → 0.62: the porch afterwards — what it handled, what it surfaced.
        await page.goto(`${BASE}/#/porch`, { waitUntil: 'domcontentloaded' })
        await page.getByTestId('quiet-row').first().waitFor({ timeout: 20_000 })
        await parkMouse(page)
        await pace.until(0.4)
        await creep(page, { delta: 140, steps: 5, gap: 800 })
        await pace.until(0.62)

        // 0.62 → 1: the roster — spread load, vetted badges, memory notes.
        await page.goto(`${BASE}/#/volunteers`, { waitUntil: 'domcontentloaded' })
        await page.getByTestId('volunteer-card').first().waitFor({ timeout: 20_000 })
        await parkMouse(page)
        await pace.until(0.74)
        await creep(page, { delta: 150, steps: 6, gap: 900 })
        await pace.until(1)
      }
    },
  },
]

// ── driver ───────────────────────────────────────────────────────────────────

/** How long each shot's narration runs: measured if we have it, estimated if not. */
async function targets(narration) {
  const measured = await readFile(join(OUT, 'vo', 'durations.json'), 'utf8')
    .then((text) => JSON.parse(text))
    .catch(() => null)
  const wps = narration.voice.say.words_per_second || 2.87
  const out = {}
  for (const shot of narration.shots) {
    const real = measured?.shots?.[shot.id]?.seconds
    out[shot.id] = real ?? shot.text.trim().split(/\s+/).length / wps
  }
  return { targets: out, measured: Boolean(measured) }
}

async function main() {
  await rm(CLIPS, { recursive: true, force: true })
  await mkdir(CLIPS, { recursive: true })

  const narration = JSON.parse(await readFile(join(HERE, 'narration.json'), 'utf8'))
  const { targets: target, measured } = await targets(narration)
  console.log(measured ? '  pacing from measured voiceover' : '  pacing from estimated voiceover')

  const browser = await chromium.launch()
  const problems = []
  const manifest = []

  for (const shot of SHOTS) {
    if (ONLY && ONLY !== shot.id) continue
    if (shot.before) await shot.before()

    const raw = join(CLIPS, `${shot.id}.raw`)
    const context = await browser.newContext({
      viewport: SIZE,
      deviceScaleFactor: 1,
      colorScheme: 'dark',
      recordVideo: { dir: raw, size: SIZE },
      // A recording is not a screenshot: motion must be allowed to happen.
      reducedMotion: 'no-preference',
    })
    const errors = []
    const page = await context.newPage()
    const videoStart = Date.now()
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    page.on('pageerror', (error) => errors.push(String(error)))

    const seconds = target[shot.id]
    const pace = new Pacer(page, seconds)
    // `run` does the setup (navigation, first paint) and hands back the take;
    // the pacer's clock only starts when the take does, so the dead air at the
    // head of the file is exactly what `trim` says it is.
    const take = await shot.run(page, pace)
    await page.waitForTimeout(400)
    const trim = (Date.now() - videoStart) / 1000
    pace.t0 = Date.now()
    await take()
    // A beat of margin so assemble.py never runs off the end of the file.
    await page.waitForTimeout(900)

    const video = page.video()
    await context.close()
    const from = await video.path()
    const file = join(CLIPS, `${shot.id}.webm`)
    await rename(from, file)
    await rm(raw, { recursive: true, force: true })

    manifest.push({
      id: shot.id,
      file: `clips/${shot.id}.webm`,
      trim: Number(trim.toFixed(2)),
      target: Number(seconds.toFixed(2)),
      recorded: Number(((Date.now() - videoStart) / 1000).toFixed(2)),
    })
    console.log(
      `  clip  ${shot.id}  trim ${trim.toFixed(1)}s  take ${seconds.toFixed(1)}s` +
        (errors.length ? `  (${errors.length} console error(s))` : ''),
    )
    if (errors.length) problems.push(`${shot.id}: ${errors.slice(0, 3).join(' | ')}`)
  }

  await browser.close()
  await writeFile(join(OUT, 'clips.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
  console.log(`${manifest.length} clips → ${CLIPS}`)
  if (problems.length) {
    console.error('console errors during recording:')
    for (const line of problems) console.error(`  ${line}`)
    process.exitCode = 1
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
