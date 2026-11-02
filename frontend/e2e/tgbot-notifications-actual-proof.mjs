import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

// Explicit synthetic fixture DB + actor-free localhost server, never Telegram.
const root = fileURLToPath(new URL('../..', import.meta.url))
const base = 'http://127.0.0.1:18158'
const out = '/tmp/t121-unknown-ui-proof'
await mkdir(out, { recursive: true })
const fingerprintSource = `
import json, psycopg
from psycopg import sql
with psycopg.connect('postgresql://cx:cx@127.0.0.1:55439/cx_t121_unknown_ui', options='-cdefault_transaction_read_only=on') as c:
 tables=c.execute("select schemaname,tablename from pg_tables where schemaname in ('public','channel_runtime','langgraph') order by 1,2").fetchall()
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
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
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
    const labels = JSON.parse(await readFile(`${root}/frontend/src/shared/i18n/${lang}.json`, 'utf8')).notifStatus
    await page.goto(`${base}/?tab=notifications`)
    await page.getByText(labels.unknown, { exact: true }).waitFor()
    await page.getByText('Synthetic unknown delivery — no Telegram HTTP performed', { exact: true }).waitFor()
    assert.equal(await page.locator('html').getAttribute('data-mode'), theme)
    for (const status of ['queued', 'failed', 'sent']) assert.equal(await page.getByText(labels[status], { exact: true }).count(), 1)
    assert.match(await page.getByText(labels.unknown, { exact: true }).getAttribute('class'), /warn/)
    await page.screenshot({ path: `${out}/notifications-${lang}-${theme}.png` })
    assert.deepEqual(errors, [])
    assert.deepEqual(remote, [])
    assert.deepEqual(mutations, [])
    assert.deepEqual(failed, [])
    results.push({ lang, theme, unknownDistinct: true, pageErrors: 0, externalRequests: 0, nonGetRequests: 0, failedResponses: 0 })
    await context.close()
  }
} finally { await browser.close() }
const after = fingerprint()
assert.deepEqual(after, before)
const proof = { source, scope: 'production UI + actual API; four explicit synthetic notification fixtures, no seeded real receipts, no HTTP mocks; actor-free read-only scratch DB; Telegram disabled', results, tableCount: Object.keys(before).length, before, after }
await writeFile(`${out}/proof.json`, JSON.stringify(proof, null, 2))
console.log(JSON.stringify({ variants: results.length, tablesUnchanged: Object.keys(before).length, external: 0, nonGet: 0 }))
