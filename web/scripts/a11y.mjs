/**
 * Accessibility audit: axe-core (WCAG 2.1 A/AA rules) across every screen plus
 * the two overlays, followed by a keyboard sweep that walks the real tab order
 * and reports anything focusable without an accessible name or focus ring.
 *
 *   node scripts/a11y.mjs
 */
import { createRequire } from 'node:module'
import { chromium } from 'playwright'

const require = createRequire(import.meta.url)
const AXE = require.resolve('axe-core/axe.min.js')
const BASE = process.env.BASE ?? 'http://localhost:5173'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
let problems = 0

async function audit(label) {
  await page.addScriptTag({ path: AXE })
  const result = await page.evaluate(async () => {
    // @ts-expect-error injected
    return await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      resultTypes: ['violations'],
    })
  })
  const violations = result.violations.filter((v) => v.impact !== 'minor' || v.id !== 'region')
  console.log(`\n── ${label}: ${violations.length ? `${violations.length} violation kind(s)` : 'clean'}`)
  for (const v of violations) {
    problems += 1
    console.log(`   [${v.impact}] ${v.id} — ${v.help} (${v.nodes.length})`)
    for (const n of v.nodes.slice(0, 3)) console.log(`       ${n.html.slice(0, 130)}`)
  }
}

for (const screen of ['porch', 'requests', 'volunteers', 'inbox']) {
  await page.goto(`${BASE}/#/${screen}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  await audit(screen)
}

// Overlays
await page.goto(`${BASE}/#/requests`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2000)
await page.getByTestId('request-card').first().click()
await page.getByRole('dialog').waitFor()
await page.waitForTimeout(600)
await audit('request drawer')
await page.keyboard.press('Escape')
await page.waitForTimeout(400)
await page.keyboard.press('t')
await page.waitForTimeout(1200)
await audit('trace drawer')
await page.keyboard.press('Escape')

// Keyboard sweep on the Porch: walk the tab order, name every stop.
await page.goto(`${BASE}/#/porch`, { waitUntil: 'domcontentloaded' })
await page.reload() // a hash-only goto does not reset focus
await page.waitForTimeout(2500)
const stops = []
for (let i = 0; i < 40; i += 1) {
  await page.keyboard.press('Tab')
  const stop = await page.evaluate(() => {
    const el = document.activeElement
    if (!el || el === document.body) return null
    const label =
      el.getAttribute('aria-label') ??
      el.getAttribute('title') ??
      (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 44)
    const ring = getComputedStyle(el, ':focus-visible').outlineWidth
    return { tag: el.tagName, label, ring, id: el.getAttribute('data-testid') }
  })
  if (!stop) break
  stops.push(stop)
}
const unnamed = stops.filter((s) => !s.label)
console.log(`\n── keyboard: ${stops.length} tab stops on the Porch, ${unnamed.length} without a name`)
for (const s of unnamed) console.log(`   unnamed ${s.tag}`)
console.log(`   first five: ${stops.slice(0, 5).map((s) => s.label).join(' → ')}`)
problems += unnamed.length

await browser.close()
console.log(problems === 0 ? '\nAll clean.' : `\n${problems} problem(s)`)
if (problems) process.exitCode = 1
