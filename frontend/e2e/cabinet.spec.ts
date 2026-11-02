import { expect, test } from '@playwright/test'

// Настоящий production UI/API; fixture меняет только настройки собственного стенда.
for (const language of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`cabinet actual scoped seven blocks ${language} ${mode}`, async ({ page, request }, info) => {
    test.setTimeout(60_000)
    const settings = await (await request.get('/api/settings')).json()
    const initial = await (await request.get('/api/cabinet/overview?product_line=all&period=month&run_id=current', { headers: { 'X-Cx-Role': 'cx_lead' } })).json()
    const direction = initial.product_lines[0]
    const foreign = initial.product_lines[1]
    expect(direction).toBeTruthy(); expect(foreign).toBeTruthy()
    const line = direction.code as string
    const headers = { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': line }
    const api = await (await request.get(`/api/cabinet/overview?product_line=${encodeURIComponent(line)}&period=month&run_id=current`, { headers })).json()
    const errors: string[] = [], external: string[] = [], forbiddenWrites: string[] = [], globalQueries: string[] = [], calls: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', req => { const url = new URL(req.url()); if (url.pathname.startsWith('/api/cabinet/')) calls.push(url.pathname + url.search); if (url.pathname === '/api/incidents') globalQueries.push(url.pathname + url.search) })
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url())
      if (!['127.0.0.1', 'localhost'].includes(url.hostname)) { external.push(url.hostname); return route.abort() }
      if (!['GET', 'HEAD'].includes(req.method()) && url.pathname !== '/api/settings') { forbiddenWrites.push(req.method() + ' ' + url.pathname); return route.abort() }
      return route.continue()
    })
    await page.addInitScript(({ language, mode, line }) => {
      localStorage.setItem('cx.lang', language); localStorage.setItem('cx.ui.mode', mode); localStorage.setItem('cx.ui.layout', 'v2'); localStorage.setItem('cx.ui.attention', 'calm'); localStorage.setItem('cx.ui.theme_pack', 'brand'); if (!localStorage.getItem('cx.ui.role')) localStorage.setItem('cx.ui.role', 'cx_lead'); if (!localStorage.getItem('cx.ui.productLine')) localStorage.setItem('cx.ui.productLine', line)
    }, { language, mode, line })
    const ru = language === 'ru'
    const text = {
      role: ru ? 'Пресет роли' : 'Role preset', line: ru ? 'Направление' : 'Product line', visibility: ru ? 'Видимость' : 'Visibility',
      map: ru ? 'Карта направления' : 'Product line map', analytics: ru ? 'Динамика и источники' : 'Trends and sources',
      monthly: ru ? '12 месяцев' : '12 months', sources: ru ? 'Площадки-источники' : 'Source platforms',
      calc: ru ? 'Калькулятор потерь' : 'Loss calculator', openCalc: ru ? 'Открыть калькулятор' : 'Open calculator',
      affected: ru ? 'Пострадавшие' : 'Affected', rate: ru ? 'Ставка dCLTV' : 'dCLTV rate',
    }
    const ownPath = `/cabinet/${encodeURIComponent(line)}?period=month&run_id=current`
    try {
      await request.patch('/api/settings', { data: { ui: { layout: 'v2', mode, theme_pack: 'brand', attention: 'calm' }, cabinet: { visibility: 'soft' } } })
      await page.goto(ownPath)
      const root = page.locator('[data-cabinet]'), header = root.locator('[data-block="cabinet-header"]')
      await expect(root.locator('[data-block]')).toHaveCount(7)
      await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
      await expect(root.locator('[data-block="cabinet-kpi"]')).toContainText(String(api.kpi.signals))
      await expect(root.locator('[data-block="cabinet-kpi"]')).toContainText(api.kpi.potential_loss_rub == null ? '—' : '')
      await expect(root.getByRole('link', { name: /SIG-/ }).first()).toHaveAttribute('href', /run_id=current/)
      await page.screenshot({ path: info.outputPath(`cabinet-${language}-${mode}-top.png`) })
      const region = api.top_regions[0]
      expect(region).toBeTruthy()
      const name = ru ? region.name_ru : region.name_en
      const regionButton = root.getByRole('button', { name: new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ':') })
      await regionButton.focus()
      await expect.poll(() => calls.some(call => new URL(call, 'http://localhost').searchParams.get('region') === region.code)).toBe(true)
      await page.keyboard.press('Enter')
      await expect(page).toHaveURL(new RegExp('region=' + region.code))
      await expect(root.getByLabel(ru ? 'Сигналы выбранного региона' : 'Selected region signals')).toBeVisible()
      await expect(root.locator('svg g[transform]')).toHaveAttribute('transform', /scale\(1\.8\)/)
      await page.keyboard.press(' ')
      await expect.poll(() => new URL(page.url()).searchParams.has('region')).toBe(false)
      const chart = root.locator('[data-block="cabinet-charts"]')
      await chart.scrollIntoViewIfNeeded()
      await chart.getByRole('button', { name: text.monthly, exact: true }).click()
      await expect(chart.locator('svg')).toBeVisible()
      await expect(chart).toContainText(ru ? 'синтетические' : 'synthetic')
      await chart.getByRole('button', { name: text.sources, exact: true }).click()
      await page.screenshot({ path: info.outputPath(`cabinet-${language}-${mode}-analytics.png`) })
      await root.getByRole('button', { name: text.openCalc, exact: true }).click()
      const calc = page.getByRole('dialog', { name: text.calc, exact: true })
      await expect(calc.getByLabel(text.rate)).toHaveValue(direction.rate_code)
      await expect(calc.getByLabel(text.affected)).toHaveValue('')
      await page.screenshot({ path: info.outputPath(`cabinet-${language}-${mode}-calculator.png`) })
      await page.keyboard.press('Escape')
      await expect(calc).toHaveCount(0)
      await expect(root.getByRole('button', { name: text.openCalc, exact: true })).toBeFocused()
      await header.getByRole('combobox', { name: text.role, exact: true }).selectOption('product_manager')
      await expect.poll(async () => (await (await request.get('/api/cabinet/overview', { headers })).json()).scope.product_lines).toEqual([line])
      await header.getByRole('combobox', { name: text.line, exact: true }).selectOption('all')
      await expect(root.locator('[data-block="cabinet-kpi"]')).toContainText(String(initial.kpi.signals))
      await header.getByRole('combobox', { name: text.visibility, exact: true }).selectOption('strict')
      await expect(root.locator('[data-block="cabinet-kpi"]')).toHaveCount(0)
      const forbidden = await request.get(`/api/cabinet/signals?product_line=${encodeURIComponent(foreign.code)}`, { headers })
      expect(forbidden.status()).toBe(403)
      await page.goto(ownPath)
      await expect(root.locator('[data-block]')).toHaveCount(7)
      expect(await header.getByRole('combobox', { name: text.line, exact: true }).locator('option').evaluateAll(options => options.map(option => (option as HTMLOptionElement).value))).toEqual([line])
      await page.goto(`/cabinet/${encodeURIComponent(foreign.code)}?period=month`)
      await expect(root.locator('[data-block="cabinet-kpi"]')).toHaveCount(0)
      await page.goto(ownPath)
      await expect(root.locator('[data-block]')).toHaveCount(7)
      await page.setViewportSize({ width: 360, height: 900 })
      await expect(root.locator('[data-block="cabinet-header"]')).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
      expect(await page.locator('header').first().evaluate(element => element.clientHeight)).toBeLessThanOrEqual(100)
      await page.screenshot({ path: info.outputPath(`cabinet-${language}-${mode}-mobile.png`) })
      const infinite = await page.evaluate(() => document.getAnimations().filter(animation => animation.playState === 'running' && animation.effect?.getTiming().iterations === Infinity).length)
      expect(infinite).toBe(0)
      expect(globalQueries).toEqual([]); expect(forbiddenWrites).toEqual([]); expect(external).toEqual([]); expect(errors).toEqual([])
      await page.getByRole('button', { name: ru ? 'Открыть меню' : 'Open menu', exact: true }).click()
      await page.keyboard.press('Escape')
      await info.attach('cabinet-actual-proof', { body: JSON.stringify({ language, mode, block_count: 7, product_line: line, strict_foreign_status: forbidden.status(), global_queries: globalQueries, forbidden_writes: forbiddenWrites, external, page_errors: errors }), contentType: 'application/json' })
    } finally {
      await request.patch('/api/settings', { data: { ui: settings.ui ?? null, cabinet: settings.cabinet ?? null } })
    }
  })
}
