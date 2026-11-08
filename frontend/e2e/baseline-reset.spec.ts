import { expect, test } from '@playwright/test'
import { captureAgentScreenshot } from './agent-screenshot'

// Browser-only fixtures: ни один запрос сброса не достигает реального стенда.
for (const mobile of [false, true]) for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`baseline reset: подтверждение и обновление ${lang}/${mode} mobile=${mobile}`, async ({ page }, info) => {
    const label = lang === 'ru' ? 'Вернуть стартовые данные и время' : 'Restore starting data and time'
    const title = lang === 'ru' ? 'Вернуть стартовое состояние?' : 'Restore starting state?'
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 })
    const openMenu = async () => { if (mobile) await page.getByRole('button', { name: lang === 'ru' ? 'Открыть меню' : 'Open menu', exact: true }).click() }
    let restored = false
    const writes: string[] = []
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode) }, { lang, mode })
    await page.routeWebSocket('**/ws/stream', ws => { ws.onMessage(() => {}) })
    await page.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (!path.startsWith('/api/')) return route.continue()
      if (request.method() !== 'GET') {
        writes.push(path)
        if (path === '/api/sim/baseline/restore') { restored = true; return route.fulfill({ status: 202, json: { job_id: 'fixture-baseline' } }) }
        return route.abort()
      }
      if (path === '/api/settings') return route.fulfill({ json: { ui: { layout: 'legacy', theme_pack: 'brand', mode, density: 'comfortable' } } })
      if (path === '/api/sim/state') return route.fulfill({ json: { sim_time: restored ? '2026-11-09T06:00:00Z' : '2026-11-14T03:14:30Z', day_no: restored ? 0 : 5, phase: 'morning', speed: 10, running: false, current_run_id: restored ? null : 7, current_run_status: restored ? null : 'stopped', is_working_day: true } })
      if (path.startsWith('/api/refs/')) return route.fulfill({ json: [] })
      if (path === '/api/health') return route.fulfill({ json: { status: 'ok', db: true, tgbot: 'disabled' } })
      return route.fulfill({ json: { items: [] } })
    })
    await page.goto('/?tab=signals')
    await openMenu()
    const button = page.getByRole('button', { name: label, exact: true })
    await expect(button).toBeEnabled()
    await button.click()
    const dialog = page.getByRole('dialog', { name: title })
    await expect(dialog.getByText(lang === 'ru' ? /Накопленные.*сигналы.*будут удалены/ : /Signals.*will be deleted/)).toBeVisible()
    expect(writes).toEqual([])
    await captureAgentScreenshot(page, info, info.outputPath(`baseline-reset-${lang}-${mode}-${mobile ? 'mobile' : 'desktop'}.png`))
    await dialog.getByRole('button', { name: lang === 'ru' ? 'Вернуться' : 'Go back', exact: true }).click()
    expect(writes).toEqual([])
    await openMenu()
    await button.click()
    await page.getByRole('dialog', { name: title }).getByRole('button', { name: label, exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('status')).toContainText(lang === 'ru' ? 'Исходное состояние восстановлено' : 'Initial state restored')
    await expect(page.locator(mobile ? '.mobile-header' : '.desktop-header')).toContainText('09.11 09:00')
    await openMenu()
    await expect(page.getByRole('button', { name: lang === 'ru' ? 'Старт' : 'Start', exact: true })).toBeEnabled()
    expect(writes).toEqual(['/api/sim/baseline/restore'])
    expect(errors).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
