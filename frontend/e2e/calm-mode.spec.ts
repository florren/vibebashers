import { expect, test } from '@playwright/test'

// Настоящий локальный backend со штатным seed; HTTP ответы не подменяются.
for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`calm settings/undo/finite motion ${lang} ${mode}`, async ({ page, request }, testInfo) => {
    const previous = (await (await request.get('/api/settings')).json()).ui ?? null
    const remote: string[] = [], errors: string[] = [], businessWrites: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url())
      if (!['127.0.0.1', 'localhost'].includes(url.hostname)) { remote.push(url.hostname); return route.abort() }
      if (!['GET', 'HEAD'].includes(req.method()) && url.pathname !== '/api/settings') { businessWrites.push(req.method() + ' ' + url.pathname); return route.abort() }
      return route.continue()
    })
    await page.addInitScript(({ lang }) => localStorage.setItem('cx.lang', lang), { lang })
    try {
      await request.patch('/api/settings', { data: { ui: { attention: 'calm', theme_pack: 'brand', mode, density: 'comfortable', motion_sentinel: 'preserve', circadian: { source: 'sim', fixed_phase: 'morning' } } } })
      await page.goto('/')
      await expect(page.locator('html')).toHaveAttribute('data-attention', 'calm')
      await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
      const attention = page.getByRole('combobox', { name: lang === 'ru' ? 'Режим внимания' : 'Attention mode' })
      await attention.selectOption('control_room')
      await expect.poll(async () => (await (await request.get('/api/settings')).json()).ui).toMatchObject({ attention: 'control_room', motion_sentinel: 'preserve' })
      await page.reload()
      await expect(page.locator('html')).toHaveAttribute('data-attention', 'control_room')
      await attention.selectOption('calm')
      await expect(page.locator('html')).toHaveAttribute('data-attention', 'calm')
      const search = page.getByRole('textbox', { name: lang === 'ru' ? 'Поиск сигнала: код или текст' : 'Find signal: identifier or text' })
      await search.fill('SIG-000001')
      await page.getByRole('button', { name: lang === 'ru' ? 'Сбросить' : 'Reset', exact: true }).click()
      await expect(search).toHaveValue('')
      await page.getByRole('button', { name: lang === 'ru' ? 'Отменить' : 'Undo', exact: true }).click()
      await expect(search).toHaveValue('SIG-000001')
      const blocks = await page.locator('main [data-block]').count()
      expect(blocks).toBeGreaterThan(0); expect(blocks).toBeLessThanOrEqual(9)
      const loops = await page.evaluate(() => [...document.getAnimations()].filter(animation => animation.effect?.getTiming().iterations === Infinity).length)
      expect(loops).toBe(0)
      await search.fill('')
      await page.screenshot({ path: testInfo.outputPath(`calm-${lang}-${mode}.png`), fullPage: true })
      await page.setViewportSize({ width: 360, height: 800 })
      await page.reload()
      await expect(page.locator('html')).toHaveAttribute('data-attention', 'calm')
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
      await page.getByRole('button', { name: lang === 'ru' ? 'Открыть меню' : 'Open menu' }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      expect(await page.evaluate(() => [...document.getAnimations()].filter(animation => animation.playState === 'running').length)).toBe(0)
      for (const path of ['/manager', '/compliance']) {
        await page.goto(path)
        await expect(page.locator('html')).toHaveAttribute('data-alert-exception', 'true')
      }
      expect(remote).toEqual([]); expect(errors).toEqual([]); expect(businessWrites).toEqual([])
    } finally {
      await request.patch('/api/settings', { data: { ui: null } })
      if (previous !== null) await request.patch('/api/settings', { data: { ui: previous } })
    }
  })
}
