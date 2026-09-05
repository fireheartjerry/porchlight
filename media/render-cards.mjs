/**
 * Render media/cards/*.html to PNG with Playwright.
 *
 *   node media/render-cards.mjs
 *
 * Everything comes out at deviceScaleFactor 2 — 3840×2160 for the 1920×1080
 * cards, 3840×2560 for the 3:2 thumbnail — so media/assemble.py can run the slow
 * Ken Burns push by cropping a 1:1 1920×1080 window out of the 2× image instead
 * of upscaling a 1× one. The screen plate (05-frame) is the background the UI
 * screencasts are composited onto.
 *
 * Google Fonts are fetched if the network is up; if it is not, the cards still
 * lay out in Georgia/Helvetica and the run stays green (a warning is printed).
 */
import { mkdir, readdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from './lib/browser.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const CARDS = join(HERE, 'cards')
const OUT = resolve(process.env.MEDIA_OUT ?? join(HERE, 'out'), 'cards')

/** The thumbnail is 3:2 (1920×1280); every other card is 16:9. */
const TALL = /thumbnail/

async function main() {
  await mkdir(OUT, { recursive: true })
  const files = (await readdir(CARDS)).filter((name) => name.endsWith('.html')).sort()

  const browser = await chromium.launch()
  // A card only loads the faces it actually sets type in (05-frame has no text),
  // so the warning fires when *no* card managed to reach Google Fonts.
  let fontsOk = false
  for (const file of files) {
    const height = TALL.test(file) ? 1280 : 1080
    const context = await browser.newContext({
      viewport: { width: 1920, height },
      deviceScaleFactor: 2,
      colorScheme: 'dark',
    })
    const page = await context.newPage()
    await page.goto(`file://${join(CARDS, file)}`, { waitUntil: 'load' })
    // Give the webfonts a chance, but never hang the pipeline on the network.
    // `document.fonts.check()` lies about Google's unicode-range subsets, so ask
    // the face set instead: at least one Fraunces and one Inter face resolved.
    const loaded = await page
      .evaluate(async () => {
        await document.fonts.ready
        const families = new Set(
          Array.from(document.fonts)
            .filter((face) => face.status === 'loaded')
            .map((face) => face.family),
        )
        return families.has('Fraunces') && families.has('Inter')
      })
      .catch(() => false)
    if (loaded) fontsOk = true
    await page.waitForTimeout(350)

    const name = file.replace(/\.html$/, '')
    const path = join(OUT, `${name}.png`)
    await page.screenshot({ path, clip: { x: 0, y: 0, width: 1920, height } })
    console.log(`  card  ${name}.png  ${1920 * 2}×${height * 2}`)
    await context.close()
  }
  await browser.close()

  if (!fontsOk) {
    console.warn('  warn  Fraunces did not load from Google Fonts — cards fell back to Georgia')
  }
  console.log(`${files.length} cards → ${OUT}`)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
