import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium } from '@playwright/test'
import { solarBoundaries, solarPhase } from '../src/shared/theming/circadian.ts'

// Запускается явно только против отдельной локальной scratch-БД: реальные API/WS, без route mocks.
const base = process.env.CX_CIRCADIAN_BASE_URL ?? 'http://127.0.0.1:18153'
assert.equal(new URL(base).hostname, '127.0.0.1')
assert.equal(new URL(base).port, '18153')
const out = process.env.CX_CIRCADIAN_PROOF_DIR ?? '/tmp/vibebashers-t252-actual-browser'
await mkdir(out, { recursive: true })
const sourceRevision = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: fileURLToPath(new URL('../..', import.meta.url)), encoding: 'utf8' }).trim()
const browser = await chromium.launch({ headless: true })
try {
const context = await browser.newContext({ timezoneId: 'America/New_York', viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const errors = [], remote = [], packets = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => { if (new URL(request.url()).hostname !== '127.0.0.1') remote.push(new URL(request.url()).hostname) })
page.on('websocket', socket => socket.on('framereceived', ({ payload }) => {
  const message = JSON.parse(String(payload))
  if (message.topic === 'sim' && ['sim.tick', 'sim.control'].includes(message.type)) packets.push({ type: message.type, sim_time: message.data.sim_time, speed: message.data.speed, running: message.data.running })
}))
async function call(path, data, method = 'POST') {
  const response = await context.request.fetch(`${base}${path}`, { method, ...(data ? { data } : {}) })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok()) {
    const known = ['jump_to: только вперёд', 'demo: закрытие без успешного артефакта проверки запрещено', 'обратный рабочий интервал должен быть неотрицательным', 'неизвестный исход demo-команды', 'Изолированный сценарий использует событийное время; доступны запуск, пауза и остановка']
    const message = body?.detail ?? body?.title
    const failure = { method, path, status: response.status(), detail: known.includes(message) ? message : 'Unrecognized detail withheld', time: new Date().toISOString() }
    const stateResponse = await context.request.get(`${base}/api/sim/state`)
    if (stateResponse.ok()) {
      const state = await stateResponse.json()
      failure.sim = Object.fromEntries(['sim_time', 'running', 'speed', 'current_run_id', 'current_run_status'].map(key => [key, state[key]]))
      if (state.current_run_id) {
        const runResponse = await context.request.get(`${base}/api/sim/runs/${state.current_run_id}`)
        if (runResponse.ok()) {
          const run = await runResponse.json()
          failure.run = Object.fromEntries(['id', 'kind', 'status', 'scenario_id', 'reset_mode'].map(key => [key, run[key]]))
        }
      }
    }
    await writeFile(`${out}/safe-failure.json`, JSON.stringify(failure, null, 2))
    throw new Error(`${method} ${path}: ${response.status()} ${failure.detail}`)
  }
  return body
}
const control = data => call('/api/sim/control', data)
await call('/api/settings', { ui: { theme_pack: 'brand', mode: 'circadian', density: 'comfortable', circadian: { source: 'sim', fixed_phase: 'morning' } } }, 'PATCH')
const initial = await call('/api/sim/state', null, 'GET')
assert.equal(initial.running, false)
await page.addInitScript(({ time }) => {
  localStorage.setItem('cx.ui.mode', 'circadian')
  localStorage.setItem('cx.ui.circadian', JSON.stringify({ source: 'sim', fixed_phase: 'morning' }))
  localStorage.setItem('cx.ui.sim_time', time)
  localStorage.setItem('cx.lang', 'ru')
  window.geoCalls = 0
  Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition: () => { window.geoCalls++; throw new Error('Unexpected geolocation request') } } })
}, { time: initial.sim_time })
await page.goto(`${base}/trace`)
await page.waitForFunction(() => document.documentElement.dataset.phase === 'morning')
const initialClock = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Moscow', hourCycle: 'h23', hour: '2-digit', minute: '2-digit' }).format(new Date(initial.sim_time))
assert.match(await page.locator('header').innerText(), new RegExp(initialClock))
for (const lang of ['ru', 'en']) {
  if (lang === 'en') await page.locator('header button[aria-label]').filter({ hasText: 'EN' }).click()
  await page.screenshot({ path: `${out}/circadian-light-${lang}.png` })
}
const boundary = solarBoundaries(Date.parse('2026-11-09T12:00:00+03:00')).boundaries[2]
await control({ action: 'set_speed', speed: 60 })
await control({ action: 'jump_to', sim_time: new Date(boundary - 10_000).toISOString() })
await page.waitForFunction(() => document.documentElement.dataset.phase === 'morning')
const before = await call('/api/sim/state', null, 'GET')
const start = performance.now()
await control({ action: 'start', label: 'T252 isolated circadian Mock proof' })
await page.waitForFunction(() => document.documentElement.dataset.phase === 'noon' && document.documentElement.dataset.themeTransition === 'running')
const changedAfterMs = performance.now() - start
await page.waitForFunction(() => document.documentElement.dataset.themeTransition === 'idle', { timeout: 12_000 })
const after = await control({ action: 'pause' })
const ticks = packets.filter(packet => packet.type === 'sim.tick' && packet.speed === 60 && packet.running && Date.parse(packet.sim_time) >= Date.parse(before.sim_time) && Date.parse(packet.sim_time) <= Date.parse(after.sim_time))
assert.ok(ticks.length >= 2)
assert.ok(Date.parse(after.sim_time) > Date.parse(before.sim_time))
assert.equal(solarPhase(Date.parse(after.sim_time)), 'noon')
const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Moscow', hourCycle: 'h23', hour: '2-digit', minute: '2-digit' }).formatToParts(new Date(after.sim_time)).map(part => [part.type, part.value]))
assert.match(await page.locator('header').innerText(), new RegExp(`${parts.hour}:${parts.minute}`))
await writeFile(`${out}/automatic-proof.json`, JSON.stringify({ sourceRevision, before: { sim_time: before.sim_time, speed: before.speed }, after: { sim_time: after.sim_time, speed: after.speed }, naturalRunningTicks: ticks.length, changedAfterMs, packets }, null, 2))
await control({ action: 'jump_to', sim_time: '2026-11-09T17:30:00Z' })
await page.waitForFunction(() => document.documentElement.dataset.phase === 'night')
await page.waitForFunction(() => document.documentElement.dataset.themeTransition === 'idle', { timeout: 12_000 })
await page.getByTestId('night-digest').locator('summary').click()
for (const lang of ['en', 'ru']) {
  if (lang === 'ru') await page.locator('header button[aria-label]').filter({ hasText: 'RU' }).click()
  await page.screenshot({ path: `${out}/circadian-dark-${lang}.png` })
}
assert.equal(await page.evaluate(() => window.geoCalls), 0)
assert.deepEqual(errors, [])
assert.deepEqual(remote, [])
const summary = { sourceRevision, source: 'actual backend API + actual /ws/stream, isolated scratch DB, standard lite seed with 200 synthetic clients, no browser/API mocks', before: { sim_time: before.sim_time, speed: before.speed }, after: { sim_time: after.sim_time, speed: after.speed }, changedAfterMs, naturalRunningTicks: ticks.length, phase: 'noon→night', defaultGeoCalls: 0, pageErrors: errors.length, browserExternalRequests: remote.length, packets }
await writeFile(`${out}/proof.json`, JSON.stringify(summary, null, 2))
console.log(JSON.stringify({ naturalRunningTicks: ticks.length, changedAfterMs, before: before.sim_time, after: after.sim_time, speed: after.speed, defaultGeoCalls: 0, errors: 0, external: 0 }))
} finally { await browser.close() }
