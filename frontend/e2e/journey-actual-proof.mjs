import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

// Actual native graphs на отдельной synthetic DB; не live/replay и без route mocks.
const root = fileURLToPath(new URL('../..', import.meta.url))
const base = 'http://127.0.0.1:18177', out = '/tmp/t229-actual-ui-proof'
await mkdir(out, { recursive: true })
const setup = JSON.parse(await readFile(`${out}/setup.json`, 'utf8'))
const probe = `
import json,psycopg
from psycopg import sql
with psycopg.connect('postgresql://cx:cx@127.0.0.1:55439/cx_t229_ui_fd254f7',options='-cdefault_transaction_read_only=on') as c:
 result={}
 for schema,table in c.execute("select schemaname,tablename from pg_tables where schemaname in ('public','langgraph','channel_runtime','llm_runtime') order by 1,2").fetchall():
  q=sql.SQL("select count(*),md5(coalesce(string_agg(to_jsonb(t)::text,chr(10) order by to_jsonb(t)::text),'')) from {} t").format(sql.Identifier(schema,table))
  result[schema+'.'+table]=c.execute(q).fetchone()
 print(json.dumps(result,sort_keys=True))
`
const snapshot = () => JSON.parse(execFileSync(`${root}/backend/.venv/bin/python`, ['-c', probe], { encoding: 'utf8' }))
const before = snapshot(), source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim()
const variants = ['ru', 'en'].flatMap(lang => ['light', 'dark'].map(theme => ({ layout: 'legacy', lang, theme, width: 1920, height: 1080 })))
variants.push({ layout: 'v2', lang: 'ru', theme: 'light', width: 320, height: 800 }, { layout: 'v2', lang: 'en', theme: 'dark', width: 320, height: 800 })
const browser = await chromium.launch({ headless: true }), results = []
try {
 for (const v of variants) {
  const labels = JSON.parse(await readFile(`${root}/frontend/src/shared/i18n/${v.lang}.json`, 'utf8'))
  for (const path of setup.paths) {
   for (const mode of ['follow', 'replay', 'presenter']) {
    const context = await browser.newContext({ viewport: { width: v.width, height: v.height } })
    await context.addInitScript(v => {
     localStorage.setItem('cx.lang', v.lang); localStorage.setItem('cx.ui.mode', v.theme)
     localStorage.setItem('cx.ui.layout', v.layout); localStorage.setItem('cx.ui.theme_pack', 'brand')
    }, v)
    const page = await context.newPage(), errors = [], external = [], mutations = [], failed = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => {
     if (new URL(request.url()).hostname !== '127.0.0.1') external.push(request.method())
     if (!['GET', 'HEAD'].includes(request.method())) mutations.push(request.method())
    })
    page.on('response', response => { if (response.status() >= 400) failed.push({ path: new URL(response.url()).pathname, status: response.status() }) })
    const api = await (await context.request.get(`${base}/api/journey/${path.ref}?run_id=${path.run_id}`)).json()
    assert.equal(api.summary.llm_source, 'mock')
    assert.equal(api.stages.length, 8)
    if (path.post_ref) {
     const response = await context.request.get(`${base}/api/journey/${path.post_ref}?run_id=${path.run_id}`)
     assert.equal(response.status(), 200)
     const postPath = await response.json()
     // Равные timestamps не задают порядок обхода graph; сравниваем все поля/кратности.
     assert.deepEqual(postPath.client_lane.map(message => JSON.stringify(message)).sort(), api.client_lane.map(message => JSON.stringify(message)).sort())
     assert.equal(postPath.client_lane.some(message => message.text_ru === 'Чужой синтетический ответ'), false)
    }
    if (path.trajectory === 'human') {
     assert.equal(api.stages[4].status, 'waiting_human'); assert.equal(api.client_lane.length, 0)
    }
    await page.goto(`${base}/journey/${path.ref}${mode === 'follow' ? '' : `?mode=${mode}`}`)
    await page.getByRole('heading', { name: mode === 'follow' ? labels.journeyUi.title : `${labels.journeyModes[mode]} · ${path.ref}`, exact: true }).waitFor()
    if (mode === 'follow') {
     await page.getByRole('region', { name: labels.journeyUi.bank, exact: true }).waitFor()
    } else {
     const next = page.getByRole('button', { name: labels.journeyModes.next, exact: true })
     await next.waitFor()
     if (mode === 'replay') {
      await page.getByRole('button', { name: labels.journeyModes.play, exact: true }).click()
      await page.getByRole('button', { name: labels.journeyModes.pause, exact: true }).click()
      await page.getByRole('button', { name: labels.journeyModes.reset, exact: true }).click()
      let steps = 0
      while (await next.isEnabled()) { assert.ok(++steps < 400); await next.click() }
     } else {
      await page.locator('h1').click()
      await page.keyboard.press('ArrowRight')
      await page.getByRole('heading', { name: labels.journeyUi.stage.understanding, exact: true }).waitFor()
      while (await next.isEnabled()) await next.click()
     }
     const lane = page.getByRole('region', { name: labels.journeyUi.client, exact: true })
     await lane.waitFor()
     for (const message of api.client_lane) await lane.getByText(message.text_ru, { exact: true }).first().waitFor()
     if (path.trajectory === 'human') await lane.getByText(labels.journeyModes.noMessages, { exact: true }).waitFor()
     await lane.scrollIntoViewIfNeeded()
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    assert.ok(overflow <= 1, `${mode}/${path.trajectory} horizontal overflow ${overflow}`)
    assert.equal(await page.locator('html').getAttribute('data-mode'), v.theme)
    assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(mutations, []); assert.deepEqual(failed, [])
    if (mode === 'presenter') await page.screenshot({ path: `${out}/${path.trajectory}-${v.layout}-${v.lang}-${v.theme}-${v.width}.png` })
    results.push({ ...v, trajectory: path.trajectory, mode, overflow, pageErrors: 0, external: 0, nonGet: 0, failedResponses: 0 })
    await context.close()
   }
  }
 }
} finally { await browser.close() }
const after = snapshot(); assert.deepEqual(after, before)
await writeFile(`${out}/proof.json`, JSON.stringify({ source, fixture: setup, scope: 'actual production UI/native Mock graphs on own read-only synthetic DB; no live/replay or external service claim; no route mocks', results, tablesUnchanged: Object.keys(before).length, before, after }, null, 2))
console.log(JSON.stringify({ variants: results.length, tablesUnchanged: Object.keys(before).length, external: 0, nonGet: 0 }))
