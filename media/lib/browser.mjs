/**
 * Playwright, borrowed from web/node_modules.
 *
 * The video pipeline has no package.json of its own on purpose — the browser it
 * drives is the same one web/scripts/screenshots.mjs uses, installed once as a
 * devDependency of the web app. `createRequire` rooted at web/package.json
 * resolves it no matter which directory node was started from.
 */
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const requireFromWeb = createRequire(join(HERE, '../../web/package.json'))

/** @type {import('playwright')} */
const playwright = requireFromWeb('playwright')

export const { chromium } = playwright
export default playwright
