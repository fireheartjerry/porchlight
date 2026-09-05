/**
 * Shot 6's code close-ups: real excerpts from the repo, syntax-highlighted and
 * rendered to PNG with Playwright.
 *
 *   node media/code-cards.mjs
 *
 * The snippets are line ranges into the actual source files, not copies, so a
 * card can never drift from the code it claims to show — if a range stops
 * matching its `expect` anchor the run fails loudly instead of filming a lie.
 * Highlighting is highlight.js from cdnjs with a hand-written Porch theme; if
 * the CDN is unreachable the code still renders, just unhighlighted.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from './lib/browser.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')
const OUT = resolve(process.env.MEDIA_OUT ?? join(HERE, 'out'), 'code')

/**
 * One card per snippet. `ranges` are 1-based, inclusive line ranges; a gap
 * between two ranges is drawn as an elision. `expect` is a substring the first
 * line of each range must contain — the anchor that keeps the card honest.
 */
const SNIPPETS = [
  {
    id: '08-code-policy',
    file: 'porchlight/policy.py',
    caption: 'The autonomy boundary: one intervention, four answers.',
    ranges: [
      { from: 786, to: 793, expect: 'def before_tool_call' },
      { from: 795, to: 802, expect: 'A volunteer reporting something wrong' },
    ],
  },
  {
    id: '09-code-graph',
    file: 'porchlight/graph.py',
    caption: 'The orchestration: a Strands Graph with conditional edges.',
    ranges: [
      { from: 490, to: 501, expect: 'builder = GraphBuilder()' },
      { from: 506, to: 507, expect: 'reset_on_revisit' },
      { from: 511, to: 511, expect: 'return builder.build()' },
    ],
  },
  {
    id: '10-code-runtime',
    file: 'porchlight/runtime.py',
    caption: 'The deployment: one AgentCore entrypoint.',
    ranges: [
      { from: 31, to: 31, expect: 'BedrockAgentCoreApp' },
      { from: 48, to: 48, expect: 'app = BedrockAgentCoreApp()' },
      { from: 190, to: 191, expect: '@app.entrypoint' },
      { from: 199, to: 204, expect: 'payload = payload or {}' },
    ],
  },
]

/** Pull the ranges out of a source file, checking every anchor. */
async function excerpt(snippet) {
  const lines = (await readFile(join(ROOT, snippet.file), 'utf8')).split('\n')
  const blocks = []
  for (const range of snippet.ranges) {
    const first = lines[range.from - 1] ?? ''
    if (!first.includes(range.expect)) {
      throw new Error(
        `${snippet.file}:${range.from} no longer starts with ${JSON.stringify(range.expect)} — ` +
          `it reads ${JSON.stringify(first.trim())}. Fix the range in media/code-cards.mjs.`,
      )
    }
    blocks.push({ from: range.from, text: lines.slice(range.from - 1, range.to).join('\n') })
  }
  return blocks
}

const escapeHtml = (text) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

function pageHtml(snippet, blocks) {
  const body = blocks
    .map(
      (block, index) =>
        (index > 0 ? '<div class="gap">⋯</div>' : '') +
        `<pre class="block" data-from="${block.from}"><code class="language-python">${escapeHtml(
          block.text,
        )}</code></pre>`,
    )
    .join('\n')

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>${snippet.id}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT,WONK@9..144,300..800,0..100,0..1&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="file://${join(HERE, 'cards', 'card.css')}">
<style>
  /* Top-aligned: the bottom 170px of every frame belongs to the caption. */
  .stage { padding: 34px 132px 0; justify-content: flex-start; gap: 0; }
  .window {
    border-radius: 20px;
    border: 1px solid rgba(255,255,255,0.10);
    background: linear-gradient(180deg, rgba(10,15,30,0.94), rgba(7,11,21,0.97));
    box-shadow: 0 60px 130px -40px rgba(0,0,0,0.92), 0 0 90px -28px rgba(255,179,71,0.18);
    overflow: hidden;
  }
  .titlebar {
    display: flex; align-items: center; gap: 16px;
    padding: 20px 32px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.025);
  }
  .lights { display: flex; gap: 10px; }
  .lights i { width: 15px; height: 15px; border-radius: 50%; background: rgba(255,255,255,0.14); }
  .lights i:first-child { background: rgba(255,107,107,0.5); }
  .lights i:nth-child(2) { background: rgba(245,158,11,0.5); }
  .lights i:last-child { background: rgba(143,185,150,0.5); }
  .path {
    font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
    font-size: 26px; color: var(--cream-dim); letter-spacing: 0.01em;
  }
  .code { padding: 30px 40px 36px; }
  pre.block { margin: 0; }
  pre.block + .gap, .gap {
    font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
    color: var(--cream-faint); font-size: 26px; padding: 4px 0 4px 6px; letter-spacing: 0.3em;
  }
  code {
    display: block;
    font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
    font-size: 26px; line-height: 1.5; color: var(--cream);
    white-space: pre-wrap; word-break: break-word;
    text-indent: -3.2ch; padding-left: 3.2ch;
  }
  /* The Porch, applied to code: amber for the machinery, sage for what it says. */
  .hljs-keyword, .hljs-built_in { color: #ffb347; }
  .hljs-title, .hljs-title.function_, .hljs-title.class_ { color: #ffd9a0; }
  .hljs-string { color: #8fb996; }
  .hljs-number, .hljs-literal { color: #b39ddb; }
  .hljs-comment { color: #7d8499; font-style: italic; }
  .hljs-params { color: #cbc4b8; }
  .hljs-decorator, .hljs-meta { color: #7fa9d8; }
  /* The one-line "what am I looking at" sits in the title bar, not under the
     window: the bottom of the frame belongs to the burned-in caption. */
  .note {
    margin-left: auto;
    font-family: Fraunces, Georgia, serif;
    font-size: 26px; font-style: italic; color: var(--lamp-wash);
  }
</style></head>
<body>
  <div class="stage">
    <div class="window">
      <div class="titlebar"><span class="lights"><i></i><i></i><i></i></span><span class="path">${snippet.file}</span><span class="note">${snippet.caption}</span></div>
      <div class="code">${body}</div>
    </div>
  </div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js"></script>
  <script>
    window.__highlighted = false
    try {
      document.querySelectorAll('pre.block code').forEach((node) => hljs.highlightElement(node))
      window.__highlighted = true
    } catch (error) { /* offline: plain cream code is still readable */ }
  </script>
</body></html>`
}

async function main() {
  await mkdir(OUT, { recursive: true })
  const browser = await chromium.launch()
  let highlighted = true

  for (const snippet of SNIPPETS) {
    const blocks = await excerpt(snippet)
    const html = pageHtml(snippet, blocks)
    // Written to disk so the page can `file://` the shared card.css and so a
    // broken card can be opened in a browser and poked at.
    const htmlPath = join(OUT, `${snippet.id}.html`)
    await writeFile(htmlPath, html, 'utf8')

    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 2,
      colorScheme: 'dark',
    })
    const page = await context.newPage()
    await page.goto(`file://${htmlPath}`, { waitUntil: 'load' })
    await page.waitForTimeout(500)
    if (!(await page.evaluate(() => window.__highlighted).catch(() => false))) highlighted = false

    // `.window` clips its own overflow, so a too-long snippet would be silently
    // guillotined rather than pushing the page taller. Measure the last code
    // line against the frame instead.
    const overflow = await page.evaluate(() => {
      const blocks = document.querySelectorAll('pre.block')
      const last = blocks[blocks.length - 1].getBoundingClientRect()
      const win = document.querySelector('.window').getBoundingClientRect()
      return Math.max(0, last.bottom - (win.bottom - 24), win.top < 8 ? 8 - win.top : 0, win.bottom - 906)
    })
    if (overflow > 0) {
      throw new Error(
        `${snippet.id} overflows its card by ${Math.round(overflow)}px — shorten a range or drop the font size`,
      )
    }

    await page.screenshot({
      path: join(OUT, `${snippet.id}.png`),
      clip: { x: 0, y: 0, width: 1920, height: 1080 },
    })
    console.log(`  code  ${snippet.id}.png  ${snippet.file}`)
    await context.close()
  }

  await browser.close()
  if (!highlighted) console.warn('  warn  highlight.js did not load — code cards are unhighlighted')
  console.log(`${SNIPPETS.length} code cards → ${OUT}`)
}

main().catch((error) => {
  console.error(String(error?.message ?? error))
  process.exit(1)
})
