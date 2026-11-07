import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { captureAgentScreenshot } from './agent-screenshot'

async function closeInterruptedContext(page: Page, context: BrowserContext, activeRoutes: () => number) {
  // Сначала остановить polling: unrouteAll ждёт только уже известные callbacks.
  // Иначе поздний route.fetch может завершиться после удаления interceptor.
  await page.goto('about:blank')
  await expect.poll(activeRoutes).toBe(0)
  await context.unrouteAll({ behavior: 'wait' })
  expect(activeRoutes()).toBe(0)
  await context.close()
}

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
    const page = await context.newPage()
    try {
      await page.goto('/engine/42?tab=graph')
      await expect(page.getByText(lang === 'ru' ? 'прерван' : 'interrupted', { exact: true }).first()).toBeVisible()
      await expect(page.getByRole('button', { name: lang === 'ru' ? 'Продолжить' : 'Resume', exact: true }).first()).toBeVisible()
      await expect(page.locator('[data-execution-status="interrupted"]')).toBeVisible()
      await expect(page.locator('[data-execution-status="interrupted"] .animate-pulse')).toHaveCount(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      expect(mutations).toEqual([])
      await captureAgentScreenshot(page, info, info.outputPath(`interrupted-${lang}-${mode}.png`))
      await page.goto('/trace/agent_run/42')
      await expect(page.getByText(lang === 'ru' ? 'прерван' : 'interrupted', { exact: true }).first()).toBeVisible()
      expect(mutations).toEqual([])
      await captureAgentScreenshot(page, info, info.outputPath(`trace-interrupted-${lang}-${mode}.png`))
    } finally {
      await closeInterruptedContext(page, context, () => activeRoutes)
    }
  })
}


test('interrupted fixture завершает pending GET до удаления interceptor', async ({ browser }) => {
  const context = await browser.newContext()
  const page = await context.newPage()
  let activeRoutes = 0
  let fulfilled = false
  let release!: () => void
  let started!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const requested = new Promise<void>(resolve => { started = resolve })
  await context.route('https://interrupted.test/api/settings', async route => {
    activeRoutes++
    started()
    try {
      await pending
      await route.fulfill({ json: {}, headers: { 'access-control-allow-origin': '*' } })
      fulfilled = true
    } finally { activeRoutes-- }
  })
  await page.goto('data:text/html,<p>interrupted fixture</p>')
  // Навигация намеренно отменит browser fetch; завершение route проверяется отдельно.
  await page.evaluate(() => { void fetch('https://interrupted.test/api/settings').catch(() => {}) })
  await requested
  const unroute = context.unrouteAll.bind(context)
  context.unrouteAll = async options => {
    expect(page.url()).toBe('about:blank')
    expect(activeRoutes).toBe(0)
    expect(fulfilled).toBe(true)
    return unroute(options)
  }
  const closing = closeInterruptedContext(page, context, () => activeRoutes)
  await page.waitForURL('about:blank')
  expect(activeRoutes).toBe(1)
  release()
  await closing
})
