import { test, expect, type Page } from '@playwright/test'
import { event, fanFixture, traceFixture } from '../src/pages/trace/components/__tests__/fixtures'

// Детерминированные синтетические UI-проверки. Producer отдельно проверяется на PG/BombLLM/fingerprints.
async function fixture(page: Page, count = 4) {
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const url = new URL(route.request().url())
    let body: unknown = {}
    if (url.pathname.endsWith('/relations')) {
      expect(url.searchParams.get('run_id')).toBe('27')
      const cursor = url.searchParams.get('cursor')
      body = fanFixture(cursor ? Number(cursor.split('-').at(-1)) : 0)
    } else if (url.pathname.startsWith('/api/trace/notification/')) {
      const ref = decodeURIComponent(url.pathname.split('/').at(-1)!)
      const id = Number(ref.split('-')[1])
      const parent = { ...event(1, 'before'), id: 'EVT-incident:1', kind: 'incident_created', object_ref: { kind: 'incident', ref: 'INC-000001' }, title_ru: 'Инцидент', links: { trace: '/trace/incident/INC-000001' } }
      body = { ...traceFixture(), subject: { kind: 'notification', ref, title_ru: `Сообщение ${id}` }, before: [parent], after: [], groups: [], edges: [{ from: parent.id, to: event(id).id, relation_ru: 'Привело к событию' }], terminal: { reached: true, event_ref: event(id).id, outcome_ru: 'Работа завершена' } }
    } else if (url.pathname.startsWith('/api/trace/')) {
      expect(url.searchParams.get('run_id')).toBe('27')
      body = traceFixture(count)
    } else if (url.pathname === '/api/search') body = { query: '', parsed: { mode: 'text' }, hits: [], counts_by_kind: {}, took_ms: 0 }
    else if (url.pathname.startsWith('/api/refs/')) body = []
    await route.fulfill({ json: body })
  })
}
const labels = {
  ru: { graph: 'Граф', columns: 'Колонки', next: 'Следующая страница', previous: 'Предыдущая страница', data: 'Данные', summary: 'Сводка', inspector: 'Сведения об узле', minimap: 'Мини-карта следа' },
  en: { graph: 'Graph', columns: 'Columns', next: 'Next page', previous: 'Previous page', data: 'Data', summary: 'Summary', inspector: 'Node inspector', minimap: 'Trace minimap' },
}
for (const theme of ['light', 'dark']) for (const lang of ['ru', 'en'] as const) {
  test(`trace graph ${theme} ${lang}`, async ({ page }, info) => {
    const errors: string[] = []
    const remote: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('request', (request) => { if (!['127.0.0.1', 'localhost'].includes(new URL(request.url()).hostname)) remote.push(request.url()) })
    await page.addInitScript(({ theme, lang }) => { localStorage.setItem('cx.ui.mode', theme); localStorage.setItem('cx.lang', lang) }, { theme, lang })
    await fixture(page)
    await page.goto('/trace/incident/INC-000001?mode=graph&run_id=27')
    const l = labels[lang]
    const graph = page.getByTestId('trace-graph')
    await expect(graph).toBeVisible()
    await expect(page.getByRole('img', { name: l.minimap })).toBeVisible()
    const subject = graph.getByRole('button', { name: /Инцидент проверки графа INC-000001/ })
    await subject.focus()
    await subject.press('End')
    const terminal = graph.getByRole('button', { name: /Сообщение 4 NTF-000004/ })
    await expect(terminal).toBeFocused()
    await expect(terminal).toHaveAttribute('aria-pressed', 'true')
    await expect(page).toHaveURL(/focus=EVT-notification%3A4/)
    await expect(graph.locator('.trace-graph-node.selected .trace-node-shape')).toHaveCSS('animation-name', 'none')
    await page.getByLabel(l.inspector).locator('summary', { hasText: l.data }).click()
    await expect(page.getByLabel(l.inspector).locator('pre')).toContainText('mock')
    await expect(page.getByLabel(l.inspector).locator('pre')).not.toContainText('raw_response')
    const transition = await graph.locator('.trace-graph-accordion').first().evaluate((element) => getComputedStyle(element, '::details-content').transitionDuration)
    expect(transition).toContain('0.4s')
    await page.screenshot({ path: info.outputPath(`trace-graph-${theme}-${lang}.png`), fullPage: true })
    await terminal.press('Enter')
    await expect(page).toHaveURL(/trace\/notification\/NTF-000004\?mode=graph&run_id=27/)
    await expect(graph.locator('.trace-graph-node.visited')).toContainText('✓')
    await page.goBack()
    await expect(graph).toBeVisible()
    await page.getByRole('button', { name: l.columns, exact: true }).click()
    await expect(graph).not.toBeVisible()
    await expect(page.locator('.trace-columns')).toBeVisible()
    await page.getByRole('button', { name: l.graph, exact: true }).click()
    await expect(graph).toBeVisible()
    await graph.getByRole('button', { name: /1001/ }).click()
    await expect(graph.locator('p[role=status]').filter({ hasText: /События|Events/ })).toHaveText(lang === 'ru' ? 'События 1–50 из 1001' : 'Events 1–50 of 1001')
    await graph.getByRole('button', { name: l.next }).click()
    await expect(graph.locator('p[role=status]').filter({ hasText: /События|Events/ })).toHaveText(lang === 'ru' ? 'События 51–100 из 1001' : 'Events 51–100 of 1001')
    await expect(graph.locator('svg[data-node-count]')).toHaveAttribute('data-node-count', '55')
    await graph.getByRole('button', { name: 'NTF-000100', exact: true }).click()
    await expect(graph.getByRole('button', { name: /Сообщение 100 NTF-000100/ })).toBeFocused()
    await graph.getByRole('button', { name: l.previous }).click()
    await expect(graph.locator('p[role=status]').filter({ hasText: /События|Events/ })).toHaveText(lang === 'ru' ? 'События 1–50 из 1001' : 'Events 1–50 of 1001')
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2)
    expect(errors).toEqual([]); expect(remote).toEqual([])
  })
}
for (const [lang, theme] of [['ru', 'dark'], ['en', 'light']] as const) {
  test(`trace graph mobile ${theme} ${lang}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.addInitScript(({ theme, lang }) => { localStorage.setItem('cx.ui.mode', theme); localStorage.setItem('cx.lang', lang) }, { theme, lang })
    await fixture(page)
    await page.goto('/trace/incident/INC-000001?mode=graph&run_id=27')
    const graph = page.getByTestId('trace-graph')
    await expect(graph).toBeVisible()
    const subject = graph.getByRole('button', { name: /Инцидент проверки графа INC-000001/ })
    await expect(subject).toBeVisible()
    const subjectBox = await subject.boundingBox()
    const viewportBox = await graph.locator('.trace-graph-viewport').boundingBox()
    expect(subjectBox!.x).toBeGreaterThanOrEqual(viewportBox!.x)
    expect(subjectBox!.x + subjectBox!.width).toBeLessThanOrEqual(viewportBox!.x + viewportBox!.width)
    const main = await graph.locator('.trace-graph-main').boundingBox()
    const panel = await graph.locator('.trace-graph-panel').boundingBox()
    expect(panel!.y).toBeGreaterThanOrEqual(main!.y + main!.height)
    await graph.locator('.trace-graph-panel summary').filter({ hasText: labels[lang].data }).click()
    await expect(graph.locator('pre')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2)
    await page.screenshot({ path: info.outputPath(`trace-graph-mobile-${theme}-${lang}.png`), fullPage: true })
  })
}
test('300-node graph renders and keyboard-pans with bounded SVG DOM', async ({ page }, info) => {
  await fixture(page, 299)
  const started = performance.now()
  await page.goto('/trace/incident/INC-000001?mode=graph&run_id=27')
  const graph = page.getByTestId('trace-graph')
  await expect(graph.locator('svg[data-node-count]')).toHaveAttribute('data-node-count', '300')
  const firstRender = performance.now() - started
  const nodeCount = await graph.locator('.trace-graph-node').count()
  expect(nodeCount).toBeLessThan(15)
  const subject = graph.getByRole('button', { name: /Инцидент проверки графа INC-000001/ })
  await subject.focus()
  const panStarted = performance.now()
  await subject.press('End')
  await expect(graph.getByRole('button', { name: /Сообщение 299 NTF-000299/ })).toBeFocused()
  const pan = performance.now() - panStarted
  expect(pan).toBeLessThan(1000)
  expect(firstRender).toBeLessThan(3000)
  expect(await graph.locator('.trace-graph-node').count()).toBeLessThan(15)
  await info.attach('graph-perf.json', { body: JSON.stringify({ mode: 'synthetic UI stress (API after<=200 unchanged)', nodes: 300, initial_render_ms: firstRender, keyboard_pan_ms: pan, initial_rendered_nodes: nodeCount }), contentType: 'application/json' })
  await page.screenshot({ path: info.outputPath('trace-graph-300.png'), fullPage: true })
})
