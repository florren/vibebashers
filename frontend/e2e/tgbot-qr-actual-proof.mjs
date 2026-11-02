import assert from 'node:assert/strict'
import { createHash, createHmac } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

// Явный synthetic signed poll proof + stand-in owned task. Никакого live Telegram.
const root = fileURLToPath(new URL('../..', import.meta.url))
const base = 'http://127.0.0.1:18160', out = '/tmp/t122-qr-ui-proof'
const secret = 'public-test-transport-vector-000000000000', token = `123456:${'A'.repeat(35)}`
await mkdir(out, { recursive: true })
const fingerprintSource = `
import json,psycopg
from psycopg import sql
with psycopg.connect('postgresql://cx:cx@127.0.0.1:55439/cx_t121_unknown_ui',options='-cdefault_transaction_read_only=on') as c:
 result={}
 for schema,table in c.execute("select schemaname,tablename from pg_tables where schemaname in ('public','channel_runtime','langgraph') order by 1,2").fetchall():
  q=sql.SQL("select count(*),md5(coalesce(string_agg(to_jsonb(t)::text,chr(10) order by to_jsonb(t)::text),'')) from {} t").format(sql.Identifier(schema,table))
  result[schema+'.'+table]=c.execute(q).fetchone()
 print(json.dumps(result,sort_keys=True))
`
const fingerprint = () => JSON.parse(execFileSync(`${root}/backend/.venv/bin/python`, ['-c', fingerprintSource], { encoding: 'utf8' }))
const before = fingerprint(), source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
const browser = await chromium.launch({ headless: true })
const results = []
try {
  const setup = await browser.newContext()
  const cold = await (await setup.request.get(`${base}/api/health`)).json()
  assert.equal(cold.tgbot, 'error')
  assert.equal(cold.tgbot_username, null)
  assert.equal((await setup.request.get(`${base}/api/public/bot/qr`)).status(), 503)
  async function heartbeat() {
    const path = '/api/internal/tgbot/heartbeat', stamp = String(Math.floor(Date.now() / 1000))
    const credential_ref = createHmac('sha256', secret).update(`cx-tgbot-credential-v1:${token}`).digest('hex')
    const body = JSON.stringify({ bot_id: 123456, username: 'ReviewBankBot', credential_ref })
    const digest = createHash('sha256').update(body).digest('hex')
    const signature = createHmac('sha256', secret).update(['cx-tgbot-v1', stamp, 'POST', path, digest].join('\n')).digest('hex')
    const response = await setup.request.post(`${base}${path}`, { data: body, headers: { 'Content-Type': 'application/json', 'X-CX-Tg-Timestamp': stamp, 'X-CX-Tg-Signature': signature } })
    assert.equal(response.status(), 200)
    assert.deepEqual(await response.json(), { accepted: true })
  }
  const variants = ['ru', 'en'].flatMap(lang => ['light', 'dark'].map(theme => ({ lang, theme, width: 1920, height: 1080 })))
  variants.push({ lang: 'ru', theme: 'light', width: 320, height: 800 }, { lang: 'en', theme: 'dark', width: 320, height: 800 })
  for (const v of variants) {
    await heartbeat()
    const context = await browser.newContext({ viewport: { width: v.width, height: v.height } })
    await context.addInitScript(({ lang, theme }) => {
      localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', theme)
      localStorage.setItem('cx.ui.theme_pack', 'brand'); localStorage.setItem('cx.ui.density', 'comfortable')
    }, v)
    const page = await context.newPage(), errors = [], remote = [], mutations = [], failed = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => {
      if (new URL(request.url()).hostname !== '127.0.0.1') remote.push(request.method())
      if (!['GET', 'HEAD'].includes(request.method())) mutations.push(request.method())
    })
    page.on('response', response => { if (response.status() >= 400) failed.push(response.status()) })
    const labels = JSON.parse(await readFile(`${root}/frontend/src/shared/i18n/${v.lang}.json`, 'utf8')).botQr
    await page.goto(`${base}/?tab=notifications`)
    const trigger = page.getByRole('button', { name: labels.open, exact: true })
    await trigger.click()
    assert.equal(await page.getByRole('dialog').count(), 1)
    await page.getByText('@ReviewBankBot', { exact: true }).waitFor()
    const qr = page.getByRole('img', { name: labels.alt })
    await qr.waitFor()
    await page.waitForFunction(() => [...document.images].some(img => img.src.endsWith('/api/public/bot/qr') && img.complete && img.naturalWidth > 0))
    await page.waitForFunction(() => { const panel = document.querySelector('[role=dialog] .fade-in'); return panel && getComputedStyle(panel).opacity === '1' && getComputedStyle(panel).transform === 'none' })
    assert.equal(await qr.getAttribute('src'), '/api/public/bot/qr')
    assert.equal(await page.locator('html').getAttribute('data-mode'), v.theme)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    assert.ok(overflow <= 1)
    const mobileHeaderHeight = v.width === 320 ? await page.locator('.mobile-header').evaluate(el => el.getBoundingClientRect().height) : null
    if (mobileHeaderHeight !== null) assert.ok(mobileHeaderHeight <= 100)
    await page.screenshot({ path: `${out}/qr-${v.lang}-${v.theme}-${v.width}.png` })
    await page.keyboard.press('Escape')
    assert.equal(await page.getByRole('dialog').count(), 0)
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true)
    assert.deepEqual(errors, []); assert.deepEqual(remote, []); assert.deepEqual(mutations, []); assert.deepEqual(failed, [])
    results.push({ ...v, qrLoaded: true, panelOpaqueAfterFiniteAnimation: true, oneDialog: true, escapeRestoresFocus: true, overflow, mobileHeaderHeight, pageErrors: 0, external: 0, nonGet: 0 })
    await context.close()
  }
  await setup.close()
} finally { await browser.close() }
const after = fingerprint(); assert.deepEqual(after, before)
await writeFile(`${out}/proof.json`, JSON.stringify({ source, scope: 'production UI/actual API on read-only synthetic DB; service poll proof signed locally; owned delivery task is explicit stand-in; NO live Telegram/getMe/getUpdates/sendMessage, no browser route mocks; 5m projector criterion unverified', cold: { tgbot: 'error', username: null, qr: 503 }, results, tablesUnchanged: Object.keys(before).length, before, after }, null, 2))
console.log(JSON.stringify({ variants: results.length, tablesUnchanged: Object.keys(before).length, external: 0, nonGet: 0 }))
