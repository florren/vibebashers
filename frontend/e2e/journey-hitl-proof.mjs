import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

// Дополнение actual proof: ключевой кадр ожидания человека, без действий HITL.
const root = fileURLToPath(new URL('../..', import.meta.url)), out = '/tmp/t229-actual-ui-proof'
const setup = JSON.parse(await readFile(`${out}/setup.json`, 'utf8'))
const path = setup.paths.find(item => item.trajectory === 'human')
const variants = ['ru', 'en'].flatMap(lang => ['light', 'dark'].map(theme => ({ lang, theme, layout: 'legacy', width: 1920, height: 1080 })))
variants.push({ lang: 'ru', theme: 'light', layout: 'v2', width: 320, height: 800 }, { lang: 'en', theme: 'dark', layout: 'v2', width: 320, height: 800 })
const browser = await chromium.launch({ headless: true }), results = []
try {
 for (const v of variants) {
  const labels = JSON.parse(await readFile(`${root}/frontend/src/shared/i18n/${v.lang}.json`, 'utf8'))
  const context = await browser.newContext({ viewport: { width: v.width, height: v.height } })
  await context.addInitScript(v => { localStorage.setItem('cx.lang', v.lang); localStorage.setItem('cx.ui.mode', v.theme); localStorage.setItem('cx.ui.layout', v.layout) }, v)
  const page = await context.newPage(), mutations = [], errors = []
  page.on('request', r => { if (!['GET', 'HEAD'].includes(r.method())) mutations.push(r.method()); assert.equal(new URL(r.url()).hostname, '127.0.0.1') })
  page.on('pageerror', e => errors.push(e.message))
  await page.goto(`http://127.0.0.1:18177/journey/${path.ref}?mode=presenter`)
  await page.getByRole('heading', { name: `${labels.journeyModes.presenter} · ${path.ref}`, exact: true }).waitFor()
  const next = page.getByRole('button', { name: labels.journeyModes.next, exact: true })
  await next.waitFor()
  for (let i = 0; i < 4; i++) await next.click()
  const bank = page.getByRole('region', { name: labels.journeyUi.bank, exact: true })
  await bank.getByRole('heading', { name: labels.journeyUi.stage.decision, exact: true }).waitFor()
  await bank.scrollIntoViewIfNeeded()
  await page.screenshot({ path: `${out}/human-decision-${v.layout}-${v.lang}-${v.theme}-${v.width}.png` })
  assert.deepEqual(mutations, []); assert.deepEqual(errors, [])
  results.push({ ...v, stage: 'decision', nonGet: 0, pageErrors: 0 })
  await context.close()
 }
} finally { await browser.close() }
await writeFile(`${out}/hitl-decision-proof.json`, JSON.stringify({ source: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(), scope: 'actual presenter waiting-human frame; no human decision submitted; no route mocks', results }, null, 2))
console.log(JSON.stringify({ cases: results.length, nonGet: 0 }))
