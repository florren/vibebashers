import { expect, test } from '@playwright/test'

const routes = ['/', ...['incidents', 'hitl', 'tickets', 'deferred', 'map', 'dashboard', 'teams', 'notifications', 'tasks'].map(tab => `/?tab=${tab}`), '/journey', '/journey/SIG-000001', '/finance', '/economics', '/engine', '/compliance', '/manager', '/feed', '/claim', '/trace', '/trace/signal/SIG-000001', '/incidents/1', '/setup', ...Array.from({ length: 8 }, (_, i) => `/setup?step=${i + 2}`), '/personal.html']

// Только чтение: тема подменяется в GET, любые записи запрещены.
for (const width of [320, 390, 430]) for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`все экраны ${width}px ${lang}/${mode}`, async ({ browser, baseURL }) => {
    test.setTimeout(120_000)
    const context = await browser.newContext({ baseURL, viewport: { width, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1, colorScheme: mode as 'light' | 'dark' })
    const mutations: string[] = [], errors: string[] = []
    await context.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode) }, { lang, mode })
    await context.route('**/api/**', async route => {
      if (route.request().method() !== 'GET') { mutations.push(route.request().url()); await route.abort(); return }
      if (new URL(route.request().url()).pathname === '/api/settings') {
        const response = await route.fetch(), settings = await response.json()
        await route.fulfill({ response, json: { ...settings, ui: { ...settings.ui, theme_pack: 'brand', mode, density: 'comfortable' } } })
      } else await route.continue()
    })
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    try {
      for (const path of routes) {
        await page.goto(path)
        await expect(page.locator('html')).toHaveAttribute('data-device', 'mobile')
        await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
        await page.evaluate(() => document.fonts.ready)
        await page.waitForTimeout(1100)
        const size = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
        expect(size.scroll, path).toBeLessThanOrEqual(size.width + 1)
        expect(errors, path).toEqual([])
        if (path === '/') {
          expect(await page.locator('header').first().evaluate(e => e.clientHeight)).toBeLessThanOrEqual(100)
          await expect(page.locator('.kpi-card')).toHaveCount(4)
          await page.locator('.kpi-toggle').click()
          await expect(page.locator('.kpi-card')).toHaveCount(8)
          await page.locator('.kpi-toggle').click()
          await page.locator('.mobile-header button[aria-expanded]').click()
          const dialog = page.getByRole('dialog')
          await expect(dialog).toBeVisible()
          await expect(dialog.locator('nav a')).toHaveCount(10)
          await page.keyboard.press('Escape')
          await expect(dialog).not.toBeVisible()
          await expect(page.locator('.mobile-header button[aria-expanded]')).toBeFocused()
        }
      }
      expect(mutations).toEqual([])
    } finally {
      // Незавершённый route.fetch должен закончиться до уничтожения browser context.
      try { await context.unrouteAll({ behavior: 'wait' }) }
      finally { await context.close() }
    }
  })
}

test('мобильный режим на ПК сохраняется после reload', async ({ page }) => {
  await page.goto('/')
  await page.locator('.desktop-header .device-selector select').selectOption('mobile')
  await expect(page.locator('.mobile-header')).toBeVisible()
  expect(await page.locator('.app-shell').evaluate(e => e.clientWidth)).toBeLessThanOrEqual(480)
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-device-preference', 'mobile')
  await page.locator('.mobile-header button[aria-expanded]').click()
  await page.locator('[role=dialog] .device-selector select').selectOption('auto')
  await expect(page.locator('.desktop-header')).toBeVisible()
})

test('телефон: версия для ПК, возврат в auto и горизонтальная ориентация', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  const page = await context.newPage()
  try {
    await page.goto('/journey')
    await page.locator('.mobile-header button[aria-expanded]').click()
    await page.locator('[role=dialog] .device-selector select').selectOption('desktop')
    await expect(page.locator('.desktop-header')).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-device-preference', 'desktop')
    await page.locator('.desktop-header .device-selector select').selectOption('auto')
    await expect(page.locator('.mobile-header')).toBeVisible()
    await context.addInitScript(() => localStorage.setItem('cx.ui.device_mode', 'auto'))
    await page.setViewportSize({ width: 844, height: 390 })
    await expect(page.locator('.mobile-header')).toBeVisible()
    const width = await page.evaluate(() => document.documentElement.clientWidth)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
  } finally { await context.close() }
})
