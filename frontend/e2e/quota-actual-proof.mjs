import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

// Синтетические quota fixtures + localhost API, без реальных provider HTTP.
const root = fileURLToPath(new URL('../..', import.meta.url))
const base = 'http://127.0.0.1:18171'
const out = '/tmp/t050-quota-ui-proof'
await mkdir(out, { recursive: true })
const fingerprintSource = `
import json, psycopg
from psycopg import sql
with psycopg.connect('postgresql://cx:cx@127.0.0.1:55439/cx_quota_ui_revision', options='-cdefault_transaction_read_only=on') as c:
 tables=c.execute("select schemaname,tablename from pg_tables where schemaname in ('public','channel_runtime','langgraph','llm_runtime') order by 1,2").fetchall()
 result={}
 for schema,table in tables:
  query=sql.SQL("select count(*),md5(coalesce(string_agg(to_jsonb(t)::text,chr(10) order by to_jsonb(t)::text),'')) from {} t").format(sql.Identifier(schema,table))
  result[schema+'.'+table]=c.execute(query).fetchone()
 print(json.dumps(result,sort_keys=True))
`
const fingerprint = () => JSON.parse(execFileSync(`${root}/backend/.venv/bin/python`, ['-c', fingerprintSource], { encoding: 'utf8' }))
const before = fingerprint()
const source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const lang of ['ru', 'en']) for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
    await context.addInitScript(({ lang, theme }) => {
      localStorage.setItem('cx.lang', lang)
      localStorage.setItem('cx.ui.mode', theme)
      localStorage.setItem('cx.ui.theme_pack', 'brand')
      localStorage.setItem('cx.ui.density', 'comfortable')
    }, { lang, theme })
    const page = await context.newPage()
    const errors = [], remote = [], mutations = [], failed = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => {
      if (new URL(request.url()).hostname !== '127.0.0.1') remote.push(request.method())
      if (!['GET', 'HEAD'].includes(request.method())) mutations.push(request.method())
    })
    page.on('response', response => { if (response.status() >= 400) failed.push(response.status()) })
    const labels = JSON.parse(await readFile(`${root}/frontend/src/shared/i18n/${lang}.json`, 'utf8')).setup.keys
    await page.goto(`${base}/setup?step=1`)
    const section = page.locator('section').filter({ has: page.getByRole('heading', { name: labels.title, exact: true }) })
    await section.getByRole('cell').filter({ hasText: 'Synthetic legacy' }).waitFor()
    const row = name => section.getByRole('row').filter({ hasText: `Synthetic ${name}` })
    assert.match(await row('legacy').innerText(), new RegExp(labels.usageUnknown))
    assert.ok((await row('legacy').innerText()).includes(labels.legacyHint.replace('{{value}}', '17')))
    assert.ok((await row('partial').innerText()).includes(labels.usageUnknown))
    assert.ok((await row('partial').innerText()).includes(labels.observedFloor.replace('{{value}}', '5')))
    assert.match(await row('zero').innerText(), /0 \/ 1000/)
    assert.match(await row('confirmed').innerText(), /123 \/ 1000/)
    assert.equal(await page.locator('html').getAttribute('data-mode'), theme)
    await section.scrollIntoViewIfNeeded()
    await section.screenshot({ path: `${out}/quota-${lang}-${theme}.png` })
    assert.deepEqual(errors, [])
    assert.deepEqual(remote, [])
    assert.deepEqual(mutations, [])
    assert.deepEqual(failed, [])
    results.push({ lang, theme, unknownAndZeroDistinct: true, pageErrors: 0, externalRequests: 0, nonGetRequests: 0, failedResponses: 0 })
    await context.close()
  }
} finally { await browser.close() }
const after = fingerprint()
assert.deepEqual(after, before)
const proof = { source, scope: 'production UI + actual API; four synthetic operational fixtures, no HTTP mocks; actor-free scratch DB, GET-only browser, network guard; SQL connection allows legacy FOR UPDATE, fingerprints verify unchanged; Telegram disabled', results, tableCount: Object.keys(before).length, before, after }
await writeFile(`${out}/proof.json`, JSON.stringify(proof, null, 2))
console.log(JSON.stringify({ variants: results.length, tablesUnchanged: Object.keys(before).length, external: 0, nonGet: 0 }))
