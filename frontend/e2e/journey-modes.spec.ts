import { expect, test } from '@playwright/test'
import { recording } from '../src/pages/journey/__tests__/recordings'
import { readFileSync } from 'node:fs'
import { captureAgentScreenshot } from './agent-screenshot'
const ru = JSON.parse(readFileSync(new URL('../src/shared/i18n/ru.json', import.meta.url), 'utf8'))
const en = JSON.parse(readFileSync(new URL('../src/shared/i18n/en.json', import.meta.url), 'utf8'))

for (const lang of ['ru', 'en'] as const) for (const mode of ['light', 'dark']) {
  test(`последний ручной Journey вне current после переоткрытия ${lang}/${mode}`, async ({ page }, info) => {
    const labels = lang === 'ru' ? ru : en
    const live = recording(8)
    live.subject.ref = 'SIG-001295'
    const writes: string[] = []
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode) }, { lang, mode })
    await page.routeWebSocket('**/ws/stream', ws => { ws.onMessage(() => {}) })
    await page.route('**/api/**', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname
      if (request.method() !== 'GET') { writes.push(path); return route.abort() }
      if (path === '/api/journey/latest') {
        if (url.searchParams.get('run_id') !== 'all' || url.searchParams.get('origin') !== 'jury') return route.fulfill({ status: 404, json: { title: 'No manual case in current World' } })
        return route.fulfill({ json: live })
      }
      const data: Record<string, unknown> = {
        '/api/settings': { ui: { layout: 'legacy', theme_pack: 'brand', mode } },
        '/api/sim/state': { running: false, current_run_id: 5, current_run_status: 'paused' },
        '/api/signals/1295': { id: 1295, agent_runs: [], incidents: [] },
        '/api/clients': [], '/api/scenarios': [], '/api/stt/providers': [],
      }
      return route.fulfill({ json: path.startsWith('/api/refs/') ? [] : data[path] ?? {} })
    })
    for (let visit = 0; visit < 2; visit++) {
      await page.goto('/journey')
      await expect(page.getByRole('heading', { name: labels.journeyUi.title, exact: true })).toBeVisible()
      await expect(page.getByRole('link', { name: /SIG-001295/ }).first()).toBeVisible()
    }
    await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
    await captureAgentScreenshot(page, info, info.outputPath(`manual-latest-${lang}-${mode}.png`))
    expect(writes).toEqual([])
    expect(errors).toEqual([])
  })
}

for (const scenario of [1, 8, 11] as const) for (const lang of ['ru', 'en'] as const) for (const theme of ['light', 'dark']) {
  test(`запись сценария ${scenario} ${lang} ${theme}: повтор и ведущий без нового агента`, async ({ page }) => {
    const labels = lang === 'ru' ? ru : en
    await page.addInitScript(({ lang, theme }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', theme); localStorage.setItem('cx.ui.layout', 'legacy') }, { lang, theme })
    const writes: string[] = []
    await page.route('**/api/**', async (route) => {
      const req = route.request(),
        path = new URL(req.url()).pathname
      if (!path.startsWith('/api/')) { await route.continue(); return }
      if (req.method() !== 'GET') {
        writes.push(path)
        await route.abort()
        return
      }
      await route.fulfill({
        json: path.startsWith('/api/journey/')
          ? recording(scenario)
          : (path.startsWith('/api/refs/') || path === '/api/scenarios')
            ? []
            : path === '/api/sim/state'
              ? { running: false, current_run_status: 'none' }
              : {},
      })
    })
    await page.goto(`/journey/SIG-${scenario}?mode=replay`)
    await expect(page.getByRole('button', { name: labels.journeyModes.play, exact: true })).toBeVisible()
    await expect(page.getByRole('textbox', { name: labels.journeyLive.message })).toHaveCount(0)
    await page.getByRole('button', { name: labels.journeyModes.next, exact: true }).click()
    await expect(page.getByText(`Сценарий ${scenario}`, { exact: true })).toBeVisible()
    await expect(page.getByText('Ответ банка', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: labels.journeyModes.next, exact: true }).click()
    await page.getByRole('button', { name: labels.journeyModes.next, exact: true }).click()
    await expect(page.getByText('Ответ банка', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: labels.journeyModes.previous, exact: true }).click()
    await expect(page.getByText('Ответ банка', { exact: true })).toHaveCount(0)
    await page.getByRole('link', { name: labels.journeyModes.presenter, exact: true }).click()
    await expect(page.getByText(`Тезис сценария ${scenario}`, { exact: true })).toBeVisible()
    await page.locator('h1').click()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('heading', { name: labels.journeyUi.stage.understanding, exact: true })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
    await page.screenshot({ path: test.info().outputPath('journey-presenter.png') })
    expect(writes).toEqual([])
  })
}

test('Следить получает первый сигнал жюри до завершения обработки модала', async ({ page }) => {
  let accepted = false
  let publish: (() => void) | undefined
  let release: (() => void) | undefined
  const processing = new Promise<void>((resolve) => {
    release = resolve
  })
  const live = recording(1)
  live.subject.ref = 'SIG-000001'
  live.stages = live.stages.map((s) => ({ ...s, events: s.stage === 'intake' ? s.events : [], status: s.stage === 'intake' ? 'active' : 'pending' }))
  live.client_lane = []
  await page.routeWebSocket('**/ws/stream', (ws) => {
    publish = () => ws.send(JSON.stringify({ topic: 'signals', type: 'signal.created', ts: new Date().toISOString(), data: { signal_id: 1 } }))
  })
  await page.route('**/api/**', async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname
    if (!path.startsWith('/api/')) { await route.continue(); return }
    if (path === '/api/signals' && req.method() === 'POST') {
      accepted = true
      publish?.()
      await processing
      await route.fulfill({ json: { signal_id: 1, agent_run_id: 1 } })
      return
    }
    if (path === '/api/journey/latest' && !accepted) {
      await route.fulfill({ status: 404, json: { detail: 'Обращений пока нет' } })
      return
    }
    const values: Record<string, unknown> = {
      '/api/signals/1': { id: 1, agent_runs: [], incidents: [] },
      '/api/clients': [],
      '/api/scenarios': [],
      '/api/stt/providers': [],
      '/api/sim/state': { running: false, current_run_status: 'none' },
      '/api/refs/channels': [{ code: 'chat', name_ru: 'Чат' }],
    }
    await route.fulfill({ json: path.startsWith('/api/journey/') ? live : (values[path] ?? (path.startsWith('/api/refs/') ? [] : {})) })
  })
  await page.goto('/journey')
  await page.getByRole('button', { name: 'Режим жюри', exact: true }).click()
  const modal = page.getByRole('dialog')
  await modal.getByRole('textbox').first().fill('Проверьте условия моего вклада')
  await modal.getByRole('button', { name: 'Отправить агенту', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Открыть след SIG-000001' })).toBeVisible({ timeout: 1000 })
  release?.()
  await expect(modal.getByRole('link', { name: 'Показать путь', exact: true })).toHaveAttribute('href', '/journey/SIG-000001')
})
