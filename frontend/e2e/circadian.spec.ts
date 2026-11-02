import { writeFile } from 'node:fs/promises'
import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'

// Синтетический локальный HTTP/WS transport: проверяется production UI, внешних вызовов нет.
const NOON = '2026-06-21T12:00:00+03:00'
const NIGHT = '2026-06-21T23:00:00+03:00'
async function fixture(page: Page, { lang = 'ru', source = 'fixed', phase = 'noon', mode = 'circadian', deferSettings = false } = {}) {
  const errors: string[] = [], remote: string[] = [], patches: unknown[] = []
  let current = NOON, socket: WebSocketRoute | undefined
  let releaseSettings!: () => void
  const settingsReady = new Promise<void>(resolve => { releaseSettings = resolve })
  const ui: Record<string, unknown> = { theme_pack: 'brand', mode, density: 'comfortable', circadian: { source, fixed_phase: phase }, lang }
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('request', (request) => { if (!['127.0.0.1', 'localhost'].includes(new URL(request.url()).hostname)) remote.push(request.url()) })
  await page.addInitScript(({ lang, source, phase, mode, noon }) => {
    if (!localStorage.getItem('cx.ui.mode')) {
      localStorage.setItem('cx.ui.mode', mode)
      localStorage.setItem('cx.ui.circadian', JSON.stringify({ source, fixed_phase: phase }))
      localStorage.setItem('cx.ui.sim_time', noon)
      localStorage.setItem('cx.lang', lang)
    }
    const observer = new MutationObserver((records) => {
      for (const record of records) if (record.type === 'attributes') (window as unknown as { themeMutations: string[] }).themeMutations.push(`${record.attributeName}:${document.documentElement.getAttribute(record.attributeName!)}`)
    })
    ;(window as unknown as { themeMutations: string[] }).themeMutations = []
    observer.observe(document, { subtree: true, attributes: true, attributeFilter: ['data-mode', 'data-phase', 'data-pack'] })
    let geoCalls = 0
    Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition: (success: (value: unknown) => void) => { geoCalls++; success({ coords: { latitude: 40.7, longitude: -74 } }) } } })
    Object.defineProperty(window, 'geoCalls', { get: () => geoCalls })
  }, { lang, source, phase, mode, noon: NOON })
  const state = () => ({ sim_time: current, speed: 60, running: true, current_run_id: 1, current_run_status: 'running' })
  await page.routeWebSocket('**/ws/stream', (ws) => { ws.onMessage(() => { socket = ws; ws.send(JSON.stringify({ topic: 'sim', type: 'sim.tick', ts: current, data: state() })) }) })
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url()), method = route.request().method()
    let json: unknown = {}
    if (url.pathname === '/api/settings') {
      if (method === 'GET' && deferSettings) await settingsReady
      if (method === 'PATCH') { const patch = route.request().postDataJSON(); patches.push(patch); Object.assign(ui, patch.ui) }
      json = { ui }
    } else if (url.pathname === '/api/sim/state') json = state()
    else if (url.pathname === '/api/signals') json = { items: [{ id: 1, public_id: 'SIG-000001', classification: { criticality: 'high' } }], next_cursor: null }
    else if (url.pathname === '/api/demo/status') json = { mode: 'offline', badge_ru: null }
    else if (url.pathname === '/api/setup/status') json = { completed: true, steps_done: [] }
    else if (url.pathname.startsWith('/api/refs/') || url.pathname === '/api/compliance/alerts') json = []
    await route.fulfill({ json })
  })
  return { errors, remote, patches, releaseSettings, tick: async (time: string) => { current = time; await expect.poll(() => !!socket).toBe(true); socket!.send(JSON.stringify({ topic: 'sim', type: 'sim.tick', ts: time, data: state() })) } }
}
async function openControls(page: Page) {
  const details = page.getByTestId('circadian-controls')
  if ((await details.getAttribute('open')) === null) await details.locator('summary').click()
  return details
}
async function contrast(page: Page) {
  return page.evaluate(() => {
    const css = getComputedStyle(document.documentElement)
    const rgb = (key: string) => css.getPropertyValue(`--${key}`).trim().split(/\s+/).map(Number)
    const lum = (c: number[]) => c.map(v => { const n = v / 255; return n <= .03928 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4 }).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i]!, 0)
    const ratio = (a: number[], b: number[]) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05) }
    const text = Math.min(...['bg', 'surface', 'raised'].flatMap(bg => ['ink', 'muted', 'brand-foreground', 'ok', 'warn', 'danger', 'info'].map(fg => ratio(rgb(fg), rgb(bg)))))
    const control = Math.min(...['bg', 'surface', 'raised'].flatMap(bg => ['control-line', 'focus-ring', 'brand-strong'].map(fg => ratio(rgb(fg), rgb(bg)))))
    return { text, control, overflow: document.documentElement.scrollWidth - innerWidth }
  })
}
for (const lang of ['ru', 'en']) test(`T252 all packs/phases and manual override ${lang}`, async ({ page }, info) => {
  const f = await fixture(page, { lang })
  await page.goto('/trace')
  const label = lang === 'ru' ? { pack: 'Пакет темы', mode: 'Режим', phase: 'Фаза', allow: 'Разрешить геолокацию' } : { pack: 'Theme pack', mode: 'Mode', phase: 'Phase', allow: 'Allow location' }
  const controls = await openControls(page)
  for (const pack of ['brand', 'ops']) {
    await page.getByRole('combobox', { name: label.pack, exact: true }).selectOption(pack)
    for (const phase of ['dawn', 'morning', 'noon', 'sunset', 'twilight', 'night']) {
      await openControls(page)
      await controls.getByRole('combobox', { name: label.phase, exact: true }).selectOption(phase)
      await expect(page.locator('html')).toHaveAttribute('data-phase', phase)
      const c = await contrast(page); expect(c.text).toBeGreaterThanOrEqual(4.5); expect(c.control).toBeGreaterThanOrEqual(3); expect(c.overflow).toBeLessThanOrEqual(2)
      if (pack === 'brand' && ['noon', 'night'].includes(phase)) {
        if (phase === 'night') {
          // Закрываем перекрывающий popover обычным действием пользователя.
          await controls.locator('summary').click()
          await expect(controls).not.toHaveAttribute('open', '')
          await page.getByTestId('night-digest').locator('summary').click()
          await expect(page.getByText('SIG-000001')).toBeVisible()
        }
        await page.screenshot({ path: info.outputPath(`circadian-${phase === 'night' ? 'dark' : 'light'}-${lang}.png`) })
      }
    }
  }
  expect(await page.evaluate(() => (window as unknown as { geoCalls: number }).geoCalls)).toBe(0)
  await f.tick(NOON)
  await expect(page.locator('html')).toHaveAttribute('data-phase', 'night')
  const manualPaint = await page.getByRole('combobox', { name: label.mode, exact: true }).evaluate((element) => {
    (element as HTMLSelectElement).value = 'light'
    element.dispatchEvent(new Event('change', { bubbles: true }))
    const root = getComputedStyle(document.documentElement)
    return { actual: getComputedStyle([...document.querySelectorAll('header button')].find(button => /Режим жюри|Jury mode/.test(button.textContent ?? ''))!).backgroundColor, target: `rgb(${root.getPropertyValue('--surface').trim().split(/\s+/).join(', ')})` }
  })
  expect(manualPaint.actual).toBe(manualPaint.target)
  await f.tick(NIGHT)
  await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')
  expect(await page.evaluate(() => (window as unknown as { themeMutations: string[] }).themeMutations.filter(v => v.startsWith('data-mode:')))).toEqual(['data-mode:light'])
  expect(f.errors).toEqual([]); expect(f.remote).toEqual([])
})
test('T252 sim ×60 eight seconds per-frame WCAG and reduced motion', async ({ page }, info) => {
  test.setTimeout(35_000)
  const f = await fixture(page, { source: 'sim', deferSettings: true })
  await page.goto('/trace')
  await expect(page.locator('html')).toHaveAttribute('data-phase', 'noon')
  await f.tick(NIGHT)
  await expect(page.locator('html')).toHaveAttribute('data-theme-transition', 'running')
  f.releaseSettings()
  await expect(page.locator('html')).toHaveAttribute('data-theme-transition', 'running')
  const frames: { time: number; text: number; control: number }[] = []
  const start = Date.now()
  while (await page.locator('html').getAttribute('data-theme-transition') === 'running') {
    frames.push({ time: Date.now() - start, ...await contrast(page) })
    await page.evaluate(() => new Promise(requestAnimationFrame))
  }
  const duration = Date.now() - start
  expect(duration).toBeGreaterThan(7000); expect(duration).toBeLessThan(10_000)
  expect(frames.length).toBeGreaterThan(100)
  expect(Math.min(...frames.map(f => f.text))).toBeGreaterThanOrEqual(4.5)
  expect(Math.min(...frames.map(f => f.control))).toBeGreaterThanOrEqual(3)
  const proof = info.outputPath('actual-frame-contrast.json')
  await writeFile(proof, JSON.stringify({ duration, frames }))
  await info.attach('actual-frame-contrast.json', { path: proof, contentType: 'application/json' })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await f.tick(NOON)
  await expect(page.locator('html')).toHaveAttribute('data-phase', 'noon')
  await expect(page.locator('html')).toHaveAttribute('data-theme-transition', 'idle')
  expect(f.errors).toEqual([]); expect(f.remote).toEqual([])
})
test('T252 real bootstrap, explicit geo consent, exceptions and mobile', async ({ page }) => {
  const f = await fixture(page, { source: 'real' })
  await page.clock.setFixedTime(new Date('2026-06-21T12:00:00+03:00'))
  await page.goto('/trace')
  await expect(page.locator('html')).toHaveAttribute('data-phase', 'noon')
  expect(await page.evaluate(() => (window as unknown as { geoCalls: number }).geoCalls)).toBe(0)
  const controls = await openControls(page)
  await controls.getByRole('button', { name: 'Разрешить геолокацию' }).click()
  expect(await page.evaluate(() => (window as unknown as { geoCalls: number }).geoCalls)).toBe(1)
  expect(f.patches.every(p => !JSON.stringify(p).includes('latitude'))).toBe(true)
  await controls.getByRole('button', { name: 'Использовать Москву' }).click()
  await page.clock.setFixedTime(new Date('2026-06-21T23:00:00+03:00'))
  await expect(page.locator('html')).toHaveAttribute('data-phase', 'night')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
  expect(await page.evaluate(() => (window as unknown as { themeMutations: string[] }).themeMutations.filter(v => v.startsWith('data-mode:')))).toEqual(['data-mode:dark'])
  for (const route of ['/manager', '/compliance']) {
    await page.goto(route)
    await expect(page.getByTestId('night-digest')).toHaveCount(0)
    await expect(page.getByTestId('night-decoration')).toHaveCount(0)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/trace')
  await page.getByRole('button', { name: 'Открыть меню' }).click()
  await openControls(page)
  expect((await contrast(page)).overflow).toBeLessThanOrEqual(2)
  expect(f.errors).toEqual([]); expect(f.remote).toEqual([])
})

test('T252 Header Moscow clock and solar phase ignore device timezone/DST', async ({ browser }) => {
  for (const timezoneId of ['UTC', 'America/New_York', 'Pacific/Auckland']) for (const lang of ['ru', 'en']) {
    const context = await browser.newContext({ timezoneId })
    const page = await context.newPage()
    const f = await fixture(page, { lang, source: 'sim' })
    await page.goto(`${process.env.E2E_BASE_URL ?? 'http://localhost:8000'}/trace`)
    for (const date of ['2026-11-09', '2026-03-08']) {
      await f.tick(`${date}T06:00:00Z`)
      await expect(page.locator('header')).toContainText('09:00')
      await expect(page.locator('html')).toHaveAttribute('data-phase', 'morning')
    }
    expect(f.errors).toEqual([]); expect(f.remote).toEqual([])
    await context.close()
  }
})
