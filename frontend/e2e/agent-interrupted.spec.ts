import { expect, test } from '@playwright/test'

// Default serial project; API GET projections only, все browser mutations запрещены.
for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`interrupted AR: статический граф и Resume ${lang}/${mode}`, async ({ browser, baseURL }, info) => {
    const context = await browser.newContext({ baseURL, viewport: { width: 1280, height: 800 } })
    const mutations: string[] = []
    let activeRoutes = 0
    const run = { id: 42, kind: 'agent', signal_id: 7, llm_profile_code: 'mock', prompt_version: 'v1', outcome: null, status: 'interrupted', interrupted_at: '2026-11-02T00:00:00Z', needed_human: false, total_tokens: 12, total_latency_ms: 50, started_at: '2026-11-02T00:00:00Z', finished_at: null, current_node: 'decide', steps: [{ seq: 1, node: 'classify', status: 'ok' }] }
    await context.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode) }, { lang, mode })
    // GET fixture interrupted не должна смешиваться с live tick чужой симуляции.
    await context.routeWebSocket('**/ws/stream', ws => { ws.onMessage(() => {}) })
    await context.route('**/api/**', async route => {
      activeRoutes++
      try {
        const request = route.request(), path = new URL(request.url()).pathname
        if (request.method() !== 'GET') { mutations.push(path); await route.abort(); return }
        if (path === '/api/agent/runs') { await route.fulfill({ json: { items: [run], next_cursor: null } }); return }
        if (path === '/api/agent/runs/42') { await route.fulfill({ json: run }); return }
        if (path === '/api/trace/agent_run/42') { await route.fulfill({ json: { subject: { kind: 'agent_run', ref: 'AR-42', title_ru: 'AR-42', status: 'interrupted' }, before: [], after: [], edges: [], groups: [], pending: [], terminal: { reached: false }, stats: { before_count: 0, after_count: 0, build_ms: 1 } } }); return }
        if (path === '/api/settings' || path === '/api/sim/state') {
          const response = await route.fetch(), value = await response.json()
          await route.fulfill({ response, json: path === '/api/settings' ? { ...value, ui: { ...value.ui, theme_pack: 'brand', mode, density: 'comfortable' } } : { ...value, running: false, current_run_id: 1, current_run_status: 'interrupted' } })
          return
        }
        await route.continue()
      } finally { activeRoutes-- }
    })
    try {
      const page = await context.newPage()
      await page.goto('/engine/42?tab=graph')
      await expect(page.getByText(lang === 'ru' ? 'прерван' : 'interrupted', { exact: true }).first()).toBeVisible()
      await expect(page.getByRole('button', { name: lang === 'ru' ? 'Продолжить' : 'Resume', exact: true }).first()).toBeVisible()
      await expect(page.locator('[data-execution-status="interrupted"]')).toBeVisible()
      await expect(page.locator('[data-execution-status="interrupted"] .animate-pulse')).toHaveCount(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      expect(mutations).toEqual([])
      await page.screenshot({ path: info.outputPath(`interrupted-${lang}-${mode}.png`), fullPage: true })
      await page.goto('/trace/agent_run/42')
      await expect(page.getByText(lang === 'ru' ? 'прерван' : 'interrupted', { exact: true }).first()).toBeVisible()
      expect(mutations).toEqual([])
      await page.screenshot({ path: info.outputPath(`trace-interrupted-${lang}-${mode}.png`), fullPage: true })
    } finally {
      await context.unrouteAll({ behavior: 'wait' })
      expect(activeRoutes).toBe(0)
      await context.close()
    }
  })
}
