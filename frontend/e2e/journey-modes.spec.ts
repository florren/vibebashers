import { expect, test } from '@playwright/test'
import { recording } from '../src/pages/journey/__tests__/recordings'

for (const scenario of [1, 8, 11] as const) {
  test(`запись сценария ${scenario}: повтор и ведущий без нового агента`, async ({ page }) => {
    const writes: string[] = []
    await page.route('**/api/**', async (route) => {
      const req = route.request(),
        path = new URL(req.url()).pathname
      if (req.method() !== 'GET') {
        writes.push(path)
        await route.abort()
        return
      }
      await route.fulfill({
        json: path.startsWith('/api/journey/')
          ? recording(scenario)
          : path.startsWith('/api/refs/')
            ? []
            : path === '/api/sim/state'
              ? { running: false, current_run_status: 'none' }
              : {},
      })
    })
    await page.goto(`/journey/SIG-${scenario}?mode=replay`)
    await expect(page.getByRole('button', { name: 'Воспроизвести', exact: true })).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Сообщение клиента' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Вперёд', exact: true }).click()
    await expect(page.getByText(`Сценарий ${scenario}`, { exact: true })).toBeVisible()
    await expect(page.getByText('Ответ банка', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Вперёд', exact: true }).click()
    await page.getByRole('button', { name: 'Вперёд', exact: true }).click()
    await expect(page.getByText('Ответ банка', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Назад', exact: true }).click()
    await expect(page.getByText('Ответ банка', { exact: true })).toHaveCount(0)
    await page.getByRole('link', { name: 'Ведущий', exact: true }).click()
    await expect(page.getByText(`Тезис сценария ${scenario}`, { exact: true })).toBeVisible()
    await page.locator('h1').click()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('heading', { name: 'Понимание', exact: true })).toBeVisible()
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
