import { test, expect } from '@playwright/test'

const runId = process.env.E2E_REPORT_RUN_ID ?? 'current'

for (const lang of ['ru', 'en'] as const) for (const mode of ['light', 'dark'] as const) {
  test(`report ${lang}/${mode}: actual API, scoped read-only SVG and A4`, async ({ page, request }, info) => {
    const apiResponse = await request.get('/api/cabinet/report', { params: { product_line: 'all', period: 'quarter', run_id: runId, lang } })
    expect(apiResponse.status()).toBe(200)
    const report = await apiResponse.json()
    const mutations: string[] = [], external: string[] = []
    await page.route('**/*', route => {
      const url = new URL(route.request().url())
      if (url.origin !== new URL(info.project.use.baseURL as string).origin) { external.push(url.origin); return route.abort() }
      if (!['GET', 'HEAD'].includes(route.request().method())) { mutations.push(route.request().method() + ' ' + url.pathname); return route.abort() }
      return route.continue()
    })
    await page.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode); localStorage.setItem('cx.ui.role', 'cx_lead') }, { lang, mode })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/cabinet/all/report?period=quarter&run_id=' + encodeURIComponent(runId))
    const root = page.locator('[data-report]')
    await expect(root.locator('[data-report-page]')).toHaveCount(3)
    await expect(root.locator('.report-summary')).toContainText(report.summary[0])
    for (const code of ['daily', 'monthly', 'sources'] as const) {
      const hasData = code === 'daily' ? report.overview.daily.some((row: { potential_loss_rub: number | null; prevented_loss_rub: number | null }) => row.potential_loss_rub != null || row.prevented_loss_rub != null) : code === 'monthly' ? report.overview.monthly.length > 0 : report.overview.sources.length > 0
      const chart = root.locator(`[data-report-chart="${code}"]`)
      await expect(chart.locator('svg')).toHaveCount(hasData ? 1 : 0)
      if (!hasData) await expect(chart).toContainText(lang === 'ru' ? 'Нет' : 'No')
    }
    await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
    await expect(root.getByRole('heading', { name: lang === 'ru' ? 'Главное за период' : 'Period summary' })).toBeVisible()
    if (report.overview.daily.some((row: { prevented_loss_rub: number | null }) => row.prevented_loss_rub != null)) expect(await root.locator('.report-chart svg path[stroke-dasharray]').count()).toBeGreaterThan(0)
    const clipped = await root.locator('.report-chart svg').evaluateAll(svgs => svgs.flatMap(svg => {
      const box = svg.getBoundingClientRect()
      return Array.from(svg.querySelectorAll('text')).filter(text => {
        const bounds = text.getBoundingClientRect()
        return bounds.width > 0 && (bounds.left < box.left - 1 || bounds.right > box.right + 1 || bounds.top < box.top - 1 || bounds.bottom > box.bottom + 1)
      }).map(text => text.textContent)
    }))
    expect(clipped).toEqual([])
    await page.screenshot({ path: info.outputPath(`report-${lang}-${mode}.png`) })
    await page.emulateMedia({ media: 'print' })
    for (const control of await root.locator('.report-controls').all()) await expect(control).toBeHidden()
    for (const paper of await root.locator('[data-report-page]').all()) {
      const size = await paper.evaluate(node => {
        const footer = node.querySelector('.report-footer')!.getBoundingClientRect()
        const content = Array.from(node.children).filter(child => !child.classList.contains('report-footer')).at(-1)!.getBoundingClientRect()
        return { client: node.clientHeight, scroll: node.scrollHeight, width: node.clientWidth, fullWidth: node.scrollWidth, footerTop: footer.top, contentBottom: content.bottom }
      })
      expect(size.scroll).toBeLessThanOrEqual(size.client + 1)
      expect(size.fullWidth).toBeLessThanOrEqual(size.width + 1)
      expect(size.client).toBeLessThanOrEqual(1050)
      expect(size.contentBottom).toBeLessThanOrEqual(size.footerTop - 8)
    }
    await page.pdf({ path: info.outputPath(`report-${lang}-${mode}.pdf`), preferCSSPageSize: true, printBackground: true })
    await page.emulateMedia({ media: 'screen' })
    await page.setViewportSize({ width: 360, height: 800 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360)
    expect(await root.evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(360)
    await page.screenshot({ path: info.outputPath(`report-${lang}-${mode}-mobile.png`) })
    expect(mutations).toEqual([]); expect(external).toEqual([])
  })
}

test('cabinet button preserves scope; report never widens an explicit manager binding', async ({ page }) => {
  const mutations: string[] = []
  await page.route('**/*', route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) { mutations.push(route.request().method()); return route.abort() }
    return route.continue()
  })
  await page.addInitScript(() => { localStorage.setItem('cx.lang','en'); localStorage.setItem('cx.ui.mode','light'); localStorage.setItem('cx.ui.role','product_manager'); localStorage.setItem('cx.ui.productLine','deposits') })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/cabinet/deposits?period=month&run_id=current')
  await page.getByRole('button',{ name:'Create report',exact:true }).click()
  await expect(page).toHaveURL(/\/cabinet\/deposits\/report\?period=month&run_id=current/)
  await expect(page.locator('[data-report-page]')).toHaveCount(3)
  await expect(page.getByRole('heading',{name:/Product line report.*Deposits/})).toBeVisible()
  const response=page.waitForResponse(response=>response.url().includes('/api/cabinet/report')&&response.url().includes('product_line=mortgage'))
  await page.goto('/cabinet/mortgage/report?period=month&run_id=current')
  expect((await response).status()).toBe(403)
  await expect(page.locator('[data-report-page]')).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Save PDF',exact:true})).toBeDisabled()
  expect(mutations).toEqual([])
})
