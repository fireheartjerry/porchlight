/**
 * Render burned-in captions as transparent 1920×1080 PNGs.
 *
 *   node media/captions.mjs media/out/captions/jobs.json
 *
 * This exists because the ffmpeg on this machine is built without libfreetype,
 * so `drawtext` is not available — and honestly, laying type out in a browser is
 * the better half of that trade: real Inter, real kerning, real line breaking,
 * and the same scrim treatment the app uses. media/assemble.py decides *what*
 * each caption says and *when* it shows; this only draws them.
 *
 * The jobs file is `[{ "file": "...png", "text": "..." }]`.
 */
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from './lib/browser.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))

const PAGE = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  html, body { margin: 0; padding: 0; width: 1920px; height: 1080px; background: transparent; }
  body { display: flex; align-items: flex-end; justify-content: center; }
  #caption {
    margin-bottom: 28px;
    max-width: 1420px;
    padding: 18px 34px 20px;
    border-radius: 16px;
    background: rgba(6, 10, 20, 0.74);
    box-shadow: 0 18px 50px -26px rgba(0, 0, 0, 0.95), inset 0 1px 0 rgba(255, 255, 255, 0.05);
    font-family: Inter, 'Helvetica Neue', Arial, sans-serif;
    font-size: 40px;
    font-weight: 500;
    line-height: 1.3;
    letter-spacing: -0.005em;
    color: #f4efe6;
    text-align: center;
    text-wrap: balance;
    text-shadow: 0 2px 10px rgba(0, 0, 0, 0.6);
  }
</style></head>
<body><div id="caption"></div></body></html>`

async function main() {
  const jobsPath = resolve(process.argv[2] ?? resolve(HERE, 'out/captions/jobs.json'))
  const jobs = JSON.parse(await readFile(jobsPath, 'utf8'))

  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    colorScheme: 'dark',
  })
  const page = await context.newPage()
  await page.setContent(PAGE, { waitUntil: 'load' })
  await page.evaluate(() => document.fonts.ready).catch(() => {})

  let tallest = 0
  for (const job of jobs) {
    await page.evaluate((text) => {
      document.getElementById('caption').textContent = text
    }, job.text)
    const height = await page.evaluate(
      () => document.getElementById('caption').getBoundingClientRect().height,
    )
    tallest = Math.max(tallest, height)
    await page.screenshot({ path: job.file, omitBackground: true })
  }

  await context.close()
  await browser.close()
  // Three lines is the point at which a caption stops being glanceable; the
  // splitter in assemble.py should have prevented it.
  const lines = Math.round((tallest - 38) / 52)
  console.log(`  caps  ${jobs.length} captions, tallest ${lines} line(s)`)
  if (lines > 2) {
    console.error(`  warn  a caption ran to ${lines} lines — shorten the split in assemble.py`)
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
