import { expect, test } from '@playwright/test'

// Настоящий local API; смена layout допускает только ui PATCH, бизнес-мутации запрещены.
for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`shell v2 opt-in/routes/keys/adaptive ${lang} ${mode}`, async ({ page, request }, testInfo) => {
    const previous = (await (await request.get('/api/settings')).json()).ui ?? null
    const errors: string[] = [], external: string[] = [], writes: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await page.route('**/*', route => {
      const r = route.request(), u = new URL(r.url())
      if (!['127.0.0.1', 'localhost'].includes(u.hostname)) { external.push(u.hostname); return route.abort() }
      if (!['GET', 'HEAD'].includes(r.method()) && u.pathname !== '/api/settings') { writes.push(r.method() + ' ' + u.pathname); return route.abort() }
      return route.continue()
    })
    await page.addInitScript(({ lang }) => localStorage.setItem('cx.lang', lang), { lang })
    const navName = lang === 'ru' ? 'Навигация' : 'Navigation'
    try {
      await request.patch('/api/settings', { data: { ui: { layout: 'legacy', mode, theme_pack: 'brand', attention: 'calm', layout_sentinel: true } } })
      await page.goto('/?tab=incidents&scope=current')
      await expect(page).toHaveURL(/\/\?tab=incidents&scope=current$/)
      await expect(page.getByRole('navigation', { name: navName })).toHaveCount(0)
      await page.screenshot({ path: testInfo.outputPath(`legacy-${lang}-${mode}.png`) })
      await page.goto('/setup')
      await page.getByText(lang === 'ru' ? 'Оформление интерфейса' : 'Interface appearance', { exact: true }).click()
      await page.getByRole('combobox', { name: lang === 'ru' ? 'Каркас интерфейса' : 'Interface layout' }).selectOption('v2')
      await expect(page.locator('[data-layout="v2"]')).toBeVisible()
      await expect.poll(async () => (await (await request.get('/api/settings')).json()).ui).toMatchObject({ layout: 'v2', layout_sentinel: true, attention: 'calm' })
      await page.goto('/')
      await expect(page).toHaveURL(/\/overview$/)
      await expect(page.getByRole('heading', { name: lang === 'ru' ? 'Обзор' : 'Overview', exact: true })).toBeVisible()
      await page.goto('/?tab=signals&q=SIG-000001')
      await expect(page).toHaveURL(/\/workspace\?tab=signals&q=SIG-000001$/)
      await page.getByRole('textbox', { name: lang === 'ru' ? 'Поиск сигнала: код или текст' : 'Find signal: identifier or text' }).focus()
      await page.keyboard.press('3'); await expect(page).toHaveURL(/tab=signals/)
      await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur() })
      for (const [key, suffix] of [['1', '/overview'], ['2', '/workspace?tab=signals'], ['3', '/workspace?tab=incidents'], ['4', '/workspace?tab=hitl'], ['5', '/workspace?tab=map'], ['6', '/workspace?tab=map&map_mode=zones']]) {
        await page.keyboard.press(key!)
        await expect.poll(() => new URL(page.url()).pathname + new URL(page.url()).search).toBe(suffix)
      }
      await expect(page.getByRole('button', { name: lang === 'ru' ? 'Зоны' : 'Zones', exact: true })).toHaveClass(/bg-brand/)
      await page.keyboard.press('?')
      await expect(page.getByRole('dialog', { name: lang === 'ru' ? 'Горячие клавиши' : 'Keyboard shortcuts' })).toBeVisible()
      await page.keyboard.press('1'); await expect(page).toHaveURL(/map_mode=zones$/)
      await page.keyboard.press('Escape')
      await page.keyboard.press('Control+k'); await expect(page.getByRole('combobox', { name: lang === 'ru' ? 'Поиск' : 'Search', exact: true })).toBeFocused()
      await page.keyboard.press('Escape')
      await page.keyboard.press('/')
      await expect(page.getByRole('combobox', { name: lang === 'ru' ? 'Поиск' : 'Search', exact: true })).toBeFocused()
      await page.keyboard.press('Escape')
      const role = page.getByRole('combobox', { name: lang === 'ru' ? 'Пресет роли' : 'Role preset' })
      await role.selectOption('product_manager')
      await expect(page.getByRole('navigation', { name: navName }).getByRole('link', { name: lang === 'ru' ? 'Комплаенс' : 'Compliance', exact: true })).toHaveCount(0)
      await role.selectOption('cx_lead')
      await page.goto('/engine')
      await expect(page.getByRole('tab', { name: lang === 'ru' ? 'Шаги' : 'Steps', exact: true })).toBeVisible()
      for (const width of [1920, 1440, 1024, 768, 360]) {
        await page.setViewportSize({ width, height: 900 })
        await page.goto('/workspace?tab=signals')
        await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
        const nav = page.getByRole('navigation', { name: navName })
        if (width >= 1024) await expect(nav).toBeVisible()
        else {
          await expect(nav).toHaveCount(0)
          const opener = page.getByRole('button', { name: width < 768 ? (lang === 'ru' ? 'Открыть меню' : 'Open menu') : (lang === 'ru' ? 'Открыть навигацию' : 'Open navigation') })
          await opener.click(); await expect(nav).toBeVisible()
          await page.keyboard.press('Escape'); await expect(nav).toHaveCount(0); await expect(opener).toBeFocused()
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
        await page.getByRole('region', { name: lang === 'ru' ? 'Приоритеты' : 'Priorities', exact: true }).getByRole('link').waitFor()
        if (width === 1440 || width === 360) await page.screenshot({ path: testInfo.outputPath(`v2-${lang}-${mode}-${width}.png`) })
      }
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto('/workspace?tab=signals'); await expect(page.getByRole('region', { name: lang === 'ru' ? 'Состояние системы' : 'System status' })).toContainText('mock')
      await page.getByRole('combobox', { name: lang === 'ru' ? 'Каркас интерфейса' : 'Interface layout' }).selectOption('legacy')
      await expect(page.locator('[data-layout="v2"]')).toHaveCount(0)
      await page.goto('/?tab=signals'); await expect(page).toHaveURL(/\/\?tab=signals$/)
      expect(errors).toEqual([]); expect(external).toEqual([]); expect(writes).toEqual([])
    } finally {
      await request.patch('/api/settings', { data: { ui: null } })
      if (previous !== null) await request.patch('/api/settings', { data: { ui: previous } })
    }
  })
}
