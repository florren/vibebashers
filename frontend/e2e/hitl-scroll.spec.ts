import { expect, test } from '@playwright/test'
import { captureAgentScreenshot } from './agent-screenshot'

// Synthetic read-only queue: no signal/decision writes and no live polling.
for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`HITL: фильтры непрозрачны при прокрутке ${lang}/${mode}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode) }, { lang, mode })
    await page.routeWebSocket('**/ws/stream', ws => { ws.onMessage(() => {}) })
    const items = Array.from({ length: 40 }, (_, i) => ({
      id: i + 1, public_id: `HD-${String(i + 1).padStart(6, '0')}`, reason: 'low_confidence',
      can_resume: false, process_outcome: 'deferred', agent_proposal: { kind: 'escalation' },
      signal: { id: i + 1, public_id: `SIG-${String(i + 1).padStart(6, '0')}`, text: `Scroll fixture ${i + 1}: service request`, channel_code: 'chat' },
    }))
    const [settings, sim] = await Promise.all(['/api/settings', '/api/sim/state'].map(async path => (await page.request.get(path)).json()))
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const mutations: string[] = []
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() !== 'GET') { mutations.push(path); await route.abort(); return }
      let body: unknown = { items: [], next_cursor: null }
      if (path === '/api/settings') body = { ...settings, ui: { ...settings.ui, theme_pack: 'brand', mode, density: 'compact' } }
      else if (path === '/api/sim/state') body = { ...sim, running: false, current_run_status: 'paused' }
      else if (path === '/api/health') body = { status: 'ok', db: true, setup_completed: true }
      else if (path === '/api/hitl/queue') body = { items, next_cursor: null, total: items.length }
      else if (/^\/api\/hitl\/\d+$/.test(path)) body = items[Number(path.split('/').at(-1)) - 1]
      else if (path.startsWith('/api/refs/')) body = []
      await route.fulfill({ json: body })
    })
    await page.goto('/?tab=hitl')
    await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
    const aside = page.locator('aside').filter({ has: page.getByPlaceholder('SIG, INC, HD, ESC, AR, CL, TSK…') })
    const filters = aside.locator('.sticky')
    await expect.poll(async () => ({ count: await aside.getByRole('button').count(), errors })).toEqual({ count: items.length, errors: [] })
    const before = await filters.boundingBox()
    await aside.evaluate(element => { element.scrollTop = 320 })
    expect(await aside.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
    const after = await filters.boundingBox()
    expect(after!.y).toBeCloseTo(before!.y, 0)
    // A missing background utility leaves this sticky element transparent.
    expect.soft(await filters.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
    await captureAgentScreenshot(page, info, info.outputPath(`hitl-scrolled-${lang}-${mode}.png`))
    expect(errors).toEqual([])
    expect(mutations).toEqual([])
  })
}
