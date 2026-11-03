import { expect, test } from '@playwright/test'

// Настоящий local API; смена layout допускает только ui PATCH, бизнес-мутации запрещены.
for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`shell v2 opt-in/routes/keys/adaptive ${lang} ${mode}`, async ({ page, request, playwright, baseURL }, testInfo) => {
    const cleanup = await playwright.request.newContext({ baseURL, timeout: 10_000 })
    const previous = (await (await cleanup.get('/api/settings')).json()).ui ?? null
    const prioritySamples: object[] = []
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
      await page.locator('.incident-board article').first().waitFor()
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
      for (const [key, suffix] of [['1', '/overview'], ['2', '/workspace?tab=signals'], ['3', '/workspace?tab=incidents'], ['4', '/workspace?tab=hitl'], ['5', '/workspace?tab=map&run_id=current'], ['6', '/workspace?tab=map&map_mode=zones&run_id=current']]) {
        await page.keyboard.press(key!)
        await expect.poll(() => new URL(page.url()).pathname + new URL(page.url()).search).toBe(suffix)
      }
      await expect(page.getByRole('button', { name: lang === 'ru' ? 'Зоны' : 'Zones', exact: true })).toHaveClass(/bg-brand/)
      await page.keyboard.press('?')
      await expect(page.getByRole('dialog', { name: lang === 'ru' ? 'Горячие клавиши' : 'Keyboard shortcuts' })).toBeVisible()
      await page.keyboard.press('1'); await expect(page).toHaveURL(/\/workspace\?tab=map&map_mode=zones&run_id=current$/)
      await page.keyboard.press('Escape')
      await page.keyboard.press('Control+k'); await expect(page.getByRole('combobox', { name: lang === 'ru' ? 'Поиск' : 'Search', exact: true })).toBeFocused()
      await page.keyboard.press('Escape')
      await page.keyboard.press('/')
      await expect(page.getByRole('combobox', { name: lang === 'ru' ? 'Поиск' : 'Search', exact: true })).toBeFocused()
      await page.keyboard.press('Escape')
      const role = page.getByRole('combobox', { name: lang === 'ru' ? 'Пресет роли' : 'Role preset' })
      await role.selectOption('product_manager')
      await expect(page.getByRole('navigation', { name: navName }).getByRole('link', { name: lang === 'ru' ? 'Комплаенс' : 'Compliance', exact: true })).toHaveCount(0)
      await page.getByRole('button', { name: lang === 'ru' ? 'Отменить' : 'Undo', exact: true }).click()
      await expect(role).toHaveValue('cx_lead')
      await role.selectOption('cx_lead')
      await page.goto('/engine')
      await expect(page.getByRole('tab', { name: lang === 'ru' ? 'Шаги' : 'Steps', exact: true })).toBeVisible()
      await page.getByRole('navigation', { name: navName }).getByRole('link', { name: lang === 'ru' ? 'Финансовый эффект' : 'Financial impact', exact: true }).click()
      await expect(page).toHaveURL(/\/finance$/)
      const openSignals = async () => {
        const response = page.waitForResponse(result => { const url = new URL(result.url()); return url.pathname === '/api/incidents' && url.searchParams.get('sort') === 'priority' && url.searchParams.get('limit') === '3' })
        await page.goto('/workspace?tab=signals')
        return response
      }
      for (const width of [1920, 1440, 1024, 768, 360, 320]) {
        const height = width === 1024 ? 768 : 900
        await page.setViewportSize({ width, height })
        let priorityResponse = await openSignals()
        await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
        const nav = page.getByRole('navigation', { name: navName })
        if (width <= 360) expect(await page.locator('header').first().evaluate(el => el.clientHeight)).toBeLessThanOrEqual(100)
        if (width >= 1024) await expect(nav).toBeVisible()
        else {
          await expect(nav).toHaveCount(0)
          const opener = page.getByRole('button', { name: width < 768 ? (lang === 'ru' ? 'Открыть меню' : 'Open menu') : (lang === 'ru' ? 'Открыть навигацию' : 'Open navigation') })
          await opener.click(); await expect(nav).toBeVisible()
          await page.keyboard.press('Escape'); await expect(nav).toHaveCount(0); await expect(opener).toBeFocused()
        }
        if (width >= 1024) {
          await page.goto('/workspace?tab=map')
          await page.waitForLoadState('networkidle')
          const box = await page.getByRole('img', { name: lang === 'ru' ? 'Карта России — где болит' : 'Map of Russia — where it hurts' }).boundingBox()
          expect(box).not.toBeNull(); expect(box!.y + box!.height).toBeLessThanOrEqual(height)
          priorityResponse = await openSignals()
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
        expect(priorityResponse.status()).toBe(200)
        const priorityQuery = new URL(priorityResponse.url()).searchParams
        const current = (await (await request.get('/api/sim/state')).json()).current_run_id
        expect(['current', String(current)]).toContain(priorityQuery.get('run_id'))
        expect(priorityQuery.getAll('status')).toEqual(['new', 'classified', 'routed', 'in_progress', 'fix_proposed', 'fix_deployed', 'awaiting_human', 'awaiting_client', 'verifying', 'escalated'])
        const priorityItems = (await priorityResponse.json()).items
        expect(Array.isArray(priorityItems)).toBe(true); expect(priorityItems.length).toBeLessThanOrEqual(3)
        prioritySamples.push({ width, run: current, query: priorityQuery.toString(), ids: priorityItems.map((item: { id: number }) => item.id) })
        const strip = page.getByRole('region', { name: lang === 'ru' ? 'Приоритеты' : 'Priorities', exact: true })
        await expect(strip).toBeVisible()
        if (priorityItems.length) {
          await expect(strip.getByRole('button')).toHaveCount(priorityItems.length)
          for (const [index, item] of priorityItems.entries()) {
            await strip.getByRole('button').nth(index).click()
            await expect(strip.getByRole('link')).toHaveAttribute('href', `/incidents/${item.id}`)
            await expect(strip.getByRole('link')).toContainText(item.public_id)
          }
        } else {
          await expect(strip.getByRole('link')).toHaveCount(0)
          await expect(strip.getByRole('button')).toHaveCount(0)
          await expect(strip).toContainText(lang === 'ru' ? 'Пока тихо. Приоритетные инциденты появятся здесь.' : 'All quiet for now. Priority incidents will appear here.')
        }
        await page.locator('button.signal-row').first().waitFor()
        if (width === 1440 || width === 360) await page.screenshot({ path: testInfo.outputPath(`v2-${lang}-${mode}-${width}.png`) })
      }
      await page.setViewportSize({ width: 1440, height: 900 })
      await page.goto('/workspace?tab=signals'); const status = page.getByRole('region', { name: lang === 'ru' ? 'Состояние системы' : 'System status' }); await expect(status).toContainText('mock')
      await status.locator('summary').click(); await expect(status.getByText(lang === 'ru' ? 'База данных: доступна' : 'Database: available', { exact: true })).toBeVisible()
      await status.locator('summary').click()
      await page.getByRole('combobox', { name: lang === 'ru' ? 'Режим внимания' : 'Attention mode' }).selectOption('control_room')
      await expect(page.locator('html')).toHaveAttribute('data-attention', 'control_room')
      await expect(page.locator('main.app-content')).toHaveCSS('font-size', '14px')
      expect(await page.evaluate(() => document.getAnimations().filter(a => a.effect?.getTiming().iterations === Infinity).length)).toBe(0)
      await page.screenshot({ path: testInfo.outputPath(`control-room-${lang}-${mode}.png`) })
      await page.getByRole('combobox', { name: lang === 'ru' ? 'Каркас интерфейса' : 'Interface layout' }).selectOption('legacy')
      await expect(page.locator('[data-layout="v2"]')).toHaveCount(0)
      await page.goto('/?tab=signals'); await expect(page).toHaveURL(/\/\?tab=signals$/)
      await testInfo.attach('native-priorities.json', { body: JSON.stringify(prioritySamples), contentType: 'application/json' })
      expect(errors).toEqual([]); expect(external).toEqual([]); expect(writes).toEqual([])
    } finally {
      try { expect((await cleanup.post('/api/settings/import', { data: { settings: { ui: previous } } })).status()).toBe(200) }
      finally { await cleanup.dispose() }
    }
  })
}
