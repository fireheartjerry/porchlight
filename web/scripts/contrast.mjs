/**
 * Contrast audit. Screenshots each screen, then for every visible text node
 * measures the painted background (the 20th-percentile luminance inside the
 * text's own box — for light-on-dark that is the ground, not the glyphs) and
 * reports anything under WCAG AA for its size.
 *
 *   node scripts/contrast.mjs
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://localhost:5173'

const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const lum = (r, g, b) => 0.2126 * lin(r / 255) + 0.7152 * lin(g / 255) + 0.0722 * lin(b / 255)
const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const findings = []

for (const screen of ['porch', 'requests', 'volunteers', 'inbox']) {
  await page.goto(`${BASE}/#/${screen}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)
  const shot = (await page.screenshot()).toString('base64')
  const rows = await page.evaluate(async (b64) => {
    const img = new Image()
    img.src = `data:image/png;base64,${b64}`
    await img.decode()
    const canvas = document.createElement('canvas')
    canvas.width = img.width
    canvas.height = img.height
    const ctx = canvas.getContext('2d')
    ctx.drawImage(img, 0, 0)
    const dpr = img.width / document.documentElement.clientWidth

    const out = []
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    const seen = new Set()
    let node
    while ((node = walker.nextNode())) {
      const text = node.textContent?.trim()
      if (!text || text.length < 2) continue
      const el = node.parentElement
      if (!el || seen.has(el)) continue
      seen.add(el)
      const r = el.getBoundingClientRect()
      if (r.width < 4 || r.height < 4 || r.top < 0 || r.bottom > window.innerHeight || r.right > window.innerWidth) continue
      const cs = getComputedStyle(el)
      if (cs.visibility === 'hidden' || cs.opacity === '0') continue
      const px = ctx.getImageData(
        Math.round(r.left * dpr),
        Math.round(r.top * dpr),
        Math.max(1, Math.round(r.width * dpr)),
        Math.max(1, Math.round(r.height * dpr)),
      ).data
      const lums = []
      for (let i = 0; i < px.length; i += 4) lums.push([px[i], px[i + 1], px[i + 2]])
      out.push({
        text: text.slice(0, 46),
        color: cs.color,
        size: parseFloat(cs.fontSize),
        weight: cs.fontWeight,
        pixels: lums.filter((_, i) => i % 3 === 0).slice(0, 4000),
      })
    }
    return out
  }, shot)

  for (const row of rows) {
    const m = row.color.match(/[\d.]+/g)?.map(Number) ?? []
    const alpha = m[3] ?? 1
    const fg = lum(m[0], m[1], m[2])
    const ls = row.pixels.map(([r, g, b]) => lum(r, g, b)).sort((a, b) => a - b)
    if (!ls.length) continue
    const median = ls[Math.floor(ls.length * 0.5)]
    // Light text sits on the darkest pixels of its box; dark text on the lightest.
    const bg = fg > median ? ls[Math.floor(ls.length * 0.2)] : ls[Math.floor(ls.length * 0.85)]
    // Approximate a translucent text colour by blending toward the ground.
    const eff = fg * alpha + bg * (1 - alpha)
    const large = row.size >= 24 || (row.size >= 18.66 && Number(row.weight) >= 700)
    const need = large ? 3 : 4.5
    const got = ratio(eff, bg)
    if (got < need) findings.push({ screen, ...row, pixels: undefined, got: got.toFixed(2), need })
  }
}

findings.sort((a, b) => Number(a.got) - Number(b.got))
for (const f of findings.slice(0, 24)) {
  console.log(`${f.got.padStart(5)} (need ${f.need})  ${f.screen.padEnd(10)} ${f.size}px ${f.color}  "${f.text}"`)
}
console.log(`\n${findings.length} findings`)
await browser.close()
