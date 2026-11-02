import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

// Production UI и actual API/PG; только синтетическая БД, без browser route mocks.
const root = fileURLToPath(new URL('../..', import.meta.url))
const base = 'http://127.0.0.1:18173', out = '/tmp/t235-actual-ui-proof'
await mkdir(out, { recursive: true })
const probe = `
import json,psycopg
from psycopg import sql
with psycopg.connect('postgresql://cx:cx@127.0.0.1:55439/cx_t235_acceptance_revision',options='-cdefault_transaction_read_only=on') as c:
 result={}
 for schema,table in c.execute("select schemaname,tablename from pg_tables where schemaname in ('public','langgraph','channel_runtime','llm_runtime') order by 1,2").fetchall():
  q=sql.SQL("select count(*),md5(coalesce(string_agg(to_jsonb(t)::text,chr(10) order by to_jsonb(t)::text),'')) from {} t").format(sql.Identifier(schema,table))
  result[schema+'.'+table]=c.execute(q).fetchone()
 refs=c.execute("select s.public_id,i.public_id from agent_runs a join signals s on s.id=a.signal_id join incidents i on i.agent_run_id=a.id where a.prompt_version='synthetic-search-fixture' order by a.id limit 1").fetchone()
 print(json.dumps({'tables':result,'signal':refs[0],'incident':refs[1]},sort_keys=True))
`
const snapshot = () => JSON.parse(execFileSync(`${root}/backend/.venv/bin/python`, ['-c', probe], { encoding: 'utf8' }))
const before = snapshot(), source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
const variants = ['legacy', 'v2'].flatMap(layout => ['ru', 'en'].flatMap(lang => ['light', 'dark'].map(theme => ({ layout, lang, theme, width: 1920, height: 1080 }))))
variants.push({ layout: 'legacy', lang: 'ru', theme: 'light', width: 320, height: 800 }, { layout: 'v2', lang: 'en', theme: 'dark', width: 320, height: 800 })
const browser = await chromium.launch({ headless: true }), results = []
try {
 for (const v of variants) {
  const context = await browser.newContext({ viewport: { width: v.width, height: v.height }, acceptDownloads: true })
  await context.addInitScript(v => {
   localStorage.setItem('cx.lang', v.lang); localStorage.setItem('cx.ui.mode', v.theme)
   localStorage.setItem('cx.ui.theme_pack', 'brand'); localStorage.setItem('cx.ui.layout', v.layout)
  }, v)
  const page = await context.newPage(), errors = [], external = [], mutations = [], failed = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
   if (new URL(request.url()).hostname !== '127.0.0.1') external.push(request.method())
   if (!['GET', 'HEAD'].includes(request.method())) mutations.push(request.method())
  })
  page.on('response', response => { if (response.status() >= 400) failed.push({ path: new URL(response.url()).pathname, status: response.status() }) })
  const labels = JSON.parse(await readFile(`${root}/frontend/src/shared/i18n/${v.lang}.json`, 'utf8'))
  await page.goto(`${base}/trace`)
  await page.getByRole('heading', { name: labels.traceUi.title, exact: true }).waitFor()
  await page.keyboard.press('Control+Shift+r')
  await page.getByRole('button', { name: labels.demoMenu.scenario13, exact: true }).click()
  assert.equal(new URL(page.url()).pathname, '/trace')
  const search = page.getByRole('combobox', { name: labels.traceUi.search, exact: true })
  await search.fill(before.signal)
  await page.getByRole('listbox', { name: labels.traceUi.results, exact: true }).getByRole('option').waitFor()
  await search.press('Enter')
  await page.waitForURL(`**/trace/signal/${before.signal}`)
  await page.getByRole('button', { name: labels.traceUi.exportJson, exact: true }).waitFor()
  assert.equal(await page.locator('html').getAttribute('data-mode'), v.theme)
  const data = await (await context.request.get(`${base}/api/trace/signal/${before.signal}?run_id=all`)).json()
  assert.ok(data.before.length && data.after.length)
  if (v.width > 320) {
   await page.getByRole('checkbox', { name: labels.traceUi.keyOnly, exact: true }).uncheck()
   await page.locator('.trace-before').getByRole('button').first().click()
   await page.getByRole('dialog', { name: labels.traceUi.event, exact: true }).waitFor()
   await page.getByRole('link', { name: labels.traceUi.center, exact: true }).click()
   await page.getByRole('button', { name: labels.traceUi.exportJson, exact: true }).waitFor()
   assert.notEqual(new URL(page.url()).pathname, `/trace/signal/${before.signal}`)
   await page.goto(`${base}/trace/signal/${before.signal}`)
   await page.getByRole('button', { name: labels.traceUi.exportJson, exact: true }).waitFor()
   await page.locator('.trace-after').getByRole('button').first().click()
   await page.getByRole('dialog', { name: labels.traceUi.event, exact: true }).waitFor()
   await page.getByRole('button', { name: labels.traceUi.close, exact: true }).click()
  } else {
   for (const phase of ['before', 'subject', 'after']) await page.getByRole('tab', { name: labels.traceUi[phase], exact: true }).click()
  }
  for (const format of ['json', 'md']) {
   const waiting = page.waitForEvent('download')
   await page.getByRole('button', { name: format === 'json' ? labels.traceUi.exportJson : labels.traceUi.exportMarkdown, exact: true }).click()
   const download = await waiting, payload = await readFile(await download.path(), 'utf8')
   assert.equal(download.suggestedFilename(), `trace-${before.signal}.${format}`)
   if (format === 'json') {
    const parsed = JSON.parse(payload); assert.equal(parsed.scope, 'all'); assert.equal(parsed.trace.subject.ref, before.signal)
    assert.ok(parsed.trace.before.length && parsed.trace.after.length)
   } else { assert.ok(payload.includes('## ')); assert.ok(payload.includes('signal')) }
  }
  await page.screenshot({ path: `${out}/trace-${v.layout}-${v.lang}-${v.theme}-${v.width}.png` })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(mutations, []); assert.deepEqual(failed, [])
  results.push({ ...v, searchMatch: true, beforeCenterAfter: true, jsonDownload: true, markdownDownload: true, pageErrors: 0, external: 0, nonGet: 0, failedResponses: 0 })
  await context.close()
 }
} finally { await browser.close() }
const after = snapshot(); assert.deepEqual(after, before)
await writeFile(`${out}/proof.json`, JSON.stringify({ source, scope: 'actual production UI/API + explicitly synthetic scratch PG; SQL readonly, no actors, no route mocks, no real LLM/Telegram', results, tableCount: Object.keys(before.tables).length, before, after }, null, 2))
console.log(JSON.stringify({ variants: results.length, unchangedTables: Object.keys(before.tables).length, external: 0, nonGet: 0 }))
