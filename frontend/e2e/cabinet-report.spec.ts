import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'

const labels = Object.fromEntries(['ru', 'en'].map(lang => [lang,
  JSON.parse(readFileSync(new URL(`../src/shared/i18n/${lang}.json`, import.meta.url), 'utf8')),
]))

const runId = process.env.E2E_REPORT_RUN_ID ?? 'current'

for (const lang of ['ru', 'en'] as const) for (const mode of ['light', 'dark'] as const) {
  test(`report ${lang}/${mode}: actual API, scoped read-only SVG and A4`, async ({ page }, info) => {
    const mutations: string[] = [], external: string[] = []
    await page.route('**/*', route => {
      const url = new URL(route.request().url())
      if (url.origin !== new URL(info.project.use.baseURL as string).origin) { external.push(url.origin); return route.abort() }
      if (!['GET', 'HEAD'].includes(route.request().method())) { mutations.push(route.request().method() + ' ' + url.pathname); return route.abort() }
      return route.continue()
    })
    await page.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode); localStorage.setItem('cx.ui.role', 'cx_lead') }, { lang, mode })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    // При активной симуляции два GET — разные snapshots. Сверяем ответ именно этого UI.
    const renderedReport = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/cabinet/report' && url.searchParams.get('lang') === lang && !url.searchParams.has('format')
    })
    await page.goto('/cabinet/all/report?period=quarter&run_id=' + encodeURIComponent(runId))
    const apiResponse = await renderedReport
    expect(apiResponse.status()).toBe(200)
    const report = await apiResponse.json()
    const root = page.locator('[data-report]')
    await expect(root.locator('[data-report-page]')).toHaveCount(3)
    await expect(root.locator('.report-summary')).toContainText(report.summary[0])
    for (const code of ['daily', 'monthly', 'sources'] as const) {
      const hasData = code === 'daily' ? report.overview.daily.some((row: { potential_loss_rub: number | null; prevented_loss_rub: number | null }) => row.potential_loss_rub != null || row.prevented_loss_rub != null) : code === 'monthly' ? report.overview.monthly.length > 0 : report.overview.sources.length > 0
      const chart = root.locator(`[data-report-chart="${code}"]`)
      await expect(chart.locator('svg')).toHaveCount(hasData ? 1 : 0)
      if (!hasData) await expect(chart).toHaveText(labels[lang].cabinet[code === 'daily' ? 'noSavedEconomics' : 'noData'])
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
    for (const format of ['json', 'xlsx'] as const) {
      const button = root.getByRole('button', { name: (lang === 'ru' ? 'Скачать ' : 'Download ') + format.toUpperCase(), exact: true })
      const [download] = await Promise.all([page.waitForEvent('download'), button.click()])
      expect(download.suggestedFilename()).toBe(`cabinet-report.${format}`)
      const destination = info.outputPath(`report-${lang}-${mode}.${format}`)
      await download.saveAs(destination)
      const bytes = await readFile(destination)
      if (format === 'json') { const exported = JSON.parse(bytes.toString()); expect(exported.lang).toBe(lang); expect(exported.overview.scope.run_ids).toEqual(report.overview.scope.run_ids) }
      else expect(bytes.subarray(0, 2).toString()).toBe('PK')
    }
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

test('cabinet button preserves scope; strict report never widens an explicit manager binding', async ({ page, request }) => {
  const settings = await (await request.get('/api/settings')).json()
  const cabinet = settings.cabinet ?? {}
  const dotted = Object.hasOwn(settings, 'cabinet.visibility')
  const visibility = dotted ? settings['cabinet.visibility'] : cabinet.visibility ?? 'soft'
  expect(['soft', 'strict']).toContain(visibility)
  const restore = dotted ? { 'cabinet.visibility': visibility } : { cabinet: { visibility } }
  const strict = dotted ? { 'cabinet.visibility': 'strict' } : { cabinet: { visibility: 'strict' } }
  const catalog = await (await request.get('/api/cabinet/overview?product_line=all&period=month&run_id=current', { headers: { 'X-Cx-Role': 'cx_lead' } })).json()
  const [own, foreign] = catalog.product_lines
  expect(own).toBeTruthy(); expect(foreign).toBeTruthy()
  const headers = { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': own.code }
  const mutations: string[] = [], reportHeaders: Record<string, string>[] = []
  page.on('request', req => { if (new URL(req.url()).pathname === '/api/cabinet/report') reportHeaders.push(req.headers()) })
  await page.route('**/*', route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) { mutations.push(route.request().method()); return route.abort() }
    return route.continue()
  })
  await page.addInitScript((line: string) => { localStorage.setItem('cx.lang','en'); localStorage.setItem('cx.ui.mode','light'); localStorage.setItem('cx.ui.role','product_manager'); localStorage.setItem('cx.ui.productLine',line) }, own.code)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  try {
    // Strict — явная server fixture, не предположение о default soft или старом e2e state.
    if (visibility !== 'strict') expect((await request.patch('/api/settings', { data: strict })).status()).toBe(200)
    expect((await request.get(`/api/cabinet/report?product_line=${encodeURIComponent(foreign.code)}&period=month&run_id=current`, { headers })).status()).toBe(403)
    await page.goto(`/cabinet/${encodeURIComponent(own.code)}?period=month&run_id=current`)
    await page.getByRole('button',{ name:'Create report',exact:true }).click()
    await expect.poll(() => new URL(page.url()).pathname).toBe(`/cabinet/${own.code}/report`)
    expect(new URL(page.url()).searchParams.get('period')).toBe('month')
    expect(new URL(page.url()).searchParams.get('run_id')).toBe('current')
    await expect(page.locator('[data-report-page]')).toHaveCount(3)
    await expect(page.getByRole('heading',{name:'Product line report · ' + own.name_en, exact: true})).toBeVisible()
    const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/cabinet/report' && new URL(response.url()).searchParams.get('product_line') === foreign.code)
    await page.goto(`/cabinet/${encodeURIComponent(foreign.code)}/report?period=month&run_id=current`)
    expect((await response).status()).toBe(403)
    await expect(page.locator('[data-report-page]')).toHaveCount(0)
    await expect(page.getByRole('button',{name:'Save PDF',exact:true})).toBeDisabled()
    expect(mutations).toEqual([])
    expect(reportHeaders.length).toBeGreaterThanOrEqual(2)
    for (const sent of reportHeaders) {
      expect(sent['x-cx-role']).toBe('product_manager')
      expect(sent['x-cx-product-line']).toBe(own.code)
    }
  } finally {
    if (visibility !== 'strict') expect((await request.patch('/api/settings', { data: restore })).status()).toBe(200)
  }
})
