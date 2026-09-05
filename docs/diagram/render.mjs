// Render docs/architecture.svg to docs/architecture.png at 2x with Playwright.
//   node docs/diagram/render.mjs
const { chromium } = await import(
  new URL('../../web/node_modules/playwright/index.mjs', import.meta.url).href,
);
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const svgPath = resolve(here, '..', 'architecture.svg');
const outPath = resolve(here, '..', 'architecture.png');
const svg = readFileSync(svgPath, 'utf8');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });
await page.setContent(
  `<!doctype html><meta charset="utf-8">
   <style>html,body{margin:0;padding:0;background:#fff}svg{display:block}</style>
   ${svg}`,
  { waitUntil: 'load' },
);
await page.screenshot({ path: outPath });
await browser.close();
console.log(`wrote ${outPath}`);
