import { expect, test, type Request } from '@playwright/test'
import type { components } from '../src/shared/api/types'
type Detail = components['schemas']['BranchDetailResponse']

// Требуется synthetic стенд с current run и native direct signal у закрытого ВСП.
// Темы меняются только в browser GET; бизнес-ответы API не подменяются.
for (const language of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`ВСП: native counts, карточка и scope ${language} ${mode}`, async ({ browser, baseURL }, info) => {
    if (!baseURL) throw new Error('Нужен E2E_BASE_URL synthetic стенда')
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const forbidden: string[] = [], failures: string[] = [], pending = new Set<Request>()
    const details = new Map<string, Detail>(), bodies: Promise<void>[] = []
    try {
      await context.addInitScript(({ language, mode }) => {
        localStorage.setItem('cx.lang', language); localStorage.setItem('cx.ui.mode', mode)
        localStorage.setItem('cx.ui.layout', 'v2'); localStorage.setItem('cx.ui.theme_pack', 'brand')
      }, { language, mode })
      await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url())
        if (url.origin !== new URL(baseURL).origin || !['GET', 'HEAD'].includes(request.method()) || url.pathname === '/api/metrics/economics' || /^\/api\/incidents\/\d+\/economics$/.test(url.pathname)) {
          forbidden.push(request.method() + ' ' + url.pathname); await route.abort(); return
        }
        if (url.pathname === '/api/settings') {
          const response = await route.fetch(), settings = await response.json()
          await route.fulfill({ response, json: { ...settings, ui: { ...settings.ui, mode, layout: 'v2', theme_pack: 'brand' } } }); return
        }
        await route.continue()
      })
      const page = await context.newPage()
      page.on('pageerror', error => failures.push(error.message))
      page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) pending.add(request) })
      page.on('requestfinished', request => pending.delete(request))
      page.on('requestfailed', request => { pending.delete(request); failures.push(request.url() + ' ' + request.failure()?.errorText) })
      page.on('response', response => {
        const path = new URL(response.url()).pathname
        if (response.status() >= 400) failures.push(response.status() + ' ' + path)
        if (/^\/api\/branches\/(?!analytics$)[^/]+$/.test(path) && response.ok()) bodies.push(response.json().then((detail: Detail) => { details.set(detail.branch.code, detail) }))
      })
      await page.goto('/workspace?tab=map')
      await expect(page).toHaveURL(/run_id=current/)
      const toggle = page.getByRole('button', { name: language === 'ru' ? 'ВСП' : 'Branches', exact: true })
      const started = Date.now(); await toggle.click()
      await expect(page.getByTestId('branch-layer')).toBeVisible()
      await expect(page.getByRole('heading', { name: language === 'ru' ? 'Динамика сети: 12 месяцев' : 'Network history: 12 months', exact: true })).toBeVisible()
      await expect.poll(() => pending.size).toBe(0); await Promise.all(bodies)
      const target = [...details.values()].find(row => row.branch.branch_status === 'closed' && row.signals.total > 0)
      expect(target, 'Нужен actual closed branch с direct signal, не city-zone proxy').toBeTruthy()
      info.annotations.push({ type: 'branches_all_reads_ms', description: String(Date.now() - started) })
      const code = target!.branch.code, run = String(target!.scope.run_ids![0])
      await page.locator(`[data-branch-codes~="${code}"]`).click()
      const member = page.getByRole('button', { name: new RegExp('^' + code + ' ·') })
      if (await member.count()) {
        await expect(member).toContainText(String(target!.signals.total)); await member.click()
      }
      await expect(page.getByRole('heading', { name: code, exact: true })).toBeVisible()
      await expect(page.locator(`a.block[href="/trace/branch/${code}?run_id=${run}"]`)).toBeVisible()
      await expect(page.locator('a[href*="/trace/signal/"]').first()).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: info.outputPath('branch.png'), fullPage: true })
      await page.getByRole('button', { name: language === 'ru' ? 'Закрыть' : 'Close', exact: true }).click()
      await toggle.click(); await expect(page.getByTestId('branch-layer')).toHaveCount(0)
      expect(forbidden).toEqual([]); expect(failures).toEqual([])
    } finally {
      await context.unrouteAll({ behavior: 'wait' }); await context.close()
    }
  })
}
