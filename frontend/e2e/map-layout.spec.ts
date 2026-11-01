import { expect, test } from '@playwright/test'

// HiDPI: 2880×1800 при системном масштабе 200 % даёт viewport 1440×900.
for (const viewport of [{ width: 1024, height: 768 }, { width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 2880, height: 1800 }]) {
  for (const language of ['ru', 'en']) for (const mode of ['light', 'dark']) {
    test(`карта и Journey ${viewport.width} ${language} ${mode}`, async ({ browser }, testInfo) => {
      const context = await browser.newContext({ viewport, deviceScaleFactor: viewport.width === 1440 ? 2 : 1 })
      let activeRoutes = 0
      try {
        const page = await context.newPage()
        // Настройки темы подменяем только в браузере: общий стенд не меняется.
        await context.route('**/api/settings', async (route) => {
          activeRoutes += 1
          try {
            const response = await route.fetch()
            const settings = await response.json()
            await route.fulfill({ response, json: { ...settings, ui: { ...settings.ui, theme_pack: 'brand', mode, density: 'comfortable' } } })
          } finally {
            activeRoutes -= 1
          }
        })
        await page.addInitScript((lang) => localStorage.setItem('cx.lang', lang), language)
        await page.goto('/?tab=map')
        const svg = page.locator('svg[role="img"]')
        await expect(svg.locator('path')).toHaveCount(83)
        await expect(svg.locator('circle')).toHaveCount(6)
        await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
        const bounds = await svg.evaluate((el) => {
          const svg = el as SVGSVGElement
          return Array.from(svg.querySelectorAll('path, circle')).map((shape) => {
            const b = (shape as SVGGraphicsElement).getBBox()
            return { left: b.x, top: b.y, right: b.x + b.width, bottom: b.y + b.height }
          })
        })
        for (const b of bounds) {
          expect(b.left).toBeGreaterThanOrEqual(0)
          expect(b.top).toBeGreaterThanOrEqual(0)
          expect(b.right).toBeLessThanOrEqual(960)
          expect(b.bottom).toBeLessThanOrEqual(540)
        }
        const box = await svg.boundingBox()
        expect(box!.y).toBeGreaterThanOrEqual(0)
        expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
        expect(await page.locator('body').evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16)
        await page.screenshot({ path: testInfo.outputPath('map.png'), fullPage: true })
        await page.goto('/journey')
        await expect(page.locator('textarea').first()).toBeVisible()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
        await page.screenshot({ path: testInfo.outputPath('journey.png'), fullPage: true })
      } finally {
        // Сначала снимаем interception и дожидаемся route.fetch/fulfill, затем закрываем context.
        try {
          await context.unrouteAll({ behavior: 'wait' })
          expect(activeRoutes).toBe(0)
        } finally {
          await context.close()
        }
      }
    })
  }
}
