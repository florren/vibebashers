import { expect, test } from '@playwright/test'
import { writeFile } from 'node:fs/promises'
import { formatCompactRub } from '../src/shared/lib/compactMoney'

// Consumer composition T242+T243, не подмена ещё не реализованного сценария T262.
test('T243 actual full catalog uses server preview for each selected rate', async ({ page, request }, info) => {
  test.setTimeout(60_000)
  const settings = await (await request.get('/api/settings')).json()
  const economics = await (await request.get('/api/settings/economics')).json()
  const overview = await (await request.get('/api/cabinet/overview?period=month&run_id=current')).json()
  const line = overview.product_lines.find((row: { rate_code: string | null }) => row.rate_code)
  expect(line).toBeTruthy(); expect(economics.rates).toHaveLength(31)
  const failures: string[] = []
  page.on('pageerror', error => failures.push(error.message))
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname) || !['GET', 'HEAD'].includes(route.request().method())) { failures.push('Blocked non-readonly or external request'); return route.abort() }
    return route.continue()
  })
  await page.addInitScript((line: string) => { localStorage.setItem('cx.lang', 'ru'); localStorage.setItem('cx.ui.mode', 'light'); localStorage.setItem('cx.ui.layout', 'v2'); localStorage.setItem('cx.ui.role', 'product_manager'); localStorage.setItem('cx.ui.productLine', line) }, line.code)
  try {
    await request.patch('/api/settings', { data: { ui: { mode: 'light', layout: 'v2', attention: 'calm' }, cabinet: { visibility: 'soft' } } })
    await page.goto(`/cabinet/${line.code}?period=month&run_id=current`)
    await page.getByRole('button', { name: 'Открыть калькулятор', exact: true }).click()
    const drawer = page.getByRole('dialog', { name: 'Калькулятор потерь', exact: true })
    await expect(drawer.getByLabel('Ставка dCLTV')).toHaveValue(line.rate_code)
    await expect(drawer.getByLabel('Пострадавшие')).toHaveValue('')
    await expect(drawer.locator('[aria-live]')).toHaveText('—')
    await drawer.getByLabel('Пострадавшие').fill('3')
    const codes: string[] = []
    for (const rate of economics.rates) {
      const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/metrics/economics/preview' && new URL(response.url()).searchParams.get('rate_code') === rate.code && new URL(response.url()).searchParams.get('affected') === '3')
      await drawer.getByLabel('Ставка dCLTV').selectOption(rate.code)
      const actualResponse = await response
      expect(actualResponse.status()).toBe(200)
      const actual = await actualResponse.json()
      expect(actual.rate_code).toBe(rate.code); expect(actual.rate_rub).toBe(rate.rate_rub)
      await expect(drawer.locator('[aria-live]')).toHaveText(formatCompactRub(actual.potential_loss_rub > 0 ? -actual.potential_loss_rub : actual.potential_loss_rub, 'ru'))
      codes.push(actual.rate_code)
    }
    expect(codes.sort()).toEqual(economics.rates.map((rate: { code: string }) => rate.code).sort())
    await page.keyboard.press('Escape')
    const scoped = await (await request.get(`/api/cabinet/overview?product_line=${line.code}&period=month&run_id=current`, { headers: { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': line.code } })).json()
    const empty = scoped.regions.find((region: { affected_clients: number | null; signals: number }) => region.affected_clients === 0 && region.signals === 0)
    expect(empty).toBeTruthy()
    const name = empty.name_ru.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const emptyRegion = page.locator('[data-cabinet]').getByRole('button', { name: new RegExp('^' + name + ':') })
    // У маленького полигона bbox-центр может лежать в соседнем регионе; проверяем штатную клавиатуру.
    await emptyRegion.focus({ timeout: 5_000 })
    await page.keyboard.press('Enter')
    await expect.poll(() => new URL(page.url()).searchParams.get('region')).toBe(empty.code)
    await expect(page.getByTestId('region-loss-preview')).toContainText('0 ₽')
    await page.getByRole('button', { name: 'Рассчитать потерю', exact: true }).click()
    await expect(drawer.getByLabel('Пострадавшие')).toHaveValue('0')
    await expect(drawer.locator('[aria-live]')).toHaveText('0 ₽')
    expect(failures).toEqual([])
    const proof = info.outputPath('actual-rate-catalog.json')
    await writeFile(proof, JSON.stringify({ source: 'T242+T243 actual production composition', catalog_count: codes.length, actual_empty_region_prefill: 0, actual_empty_region_server_result: 0, all_selected_codes: codes, readonly_page_failures: failures }, null, 2))
    await info.attach('actual-rate-catalog', { path: proof, contentType: 'application/json' })
  } finally {
    await request.patch('/api/settings', { data: { ui: settings.ui ?? null, cabinet: settings.cabinet ?? null } })
  }
})
