import { expect, test } from '@playwright/test'
import { dbActivity, dbCounters, dbRows } from '../src/test/fixtures/dbActivity'

for (const lang of ['ru', 'en']) for (const theme of ['light', 'dark']) {
  test(`database audit ${lang} ${theme}`, async ({ page }) => {
    await page.addInitScript(({ lang, theme }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', theme) }, { lang, theme })
    const calls: URL[] = []
    let count = 120
    let sendDb: (() => void) | null = null
    await page.routeWebSocket('**/ws/stream', ws => {
      ws.onMessage(message => {
        const command = JSON.parse(String(message)) as { type: string; topics?: string[] }
        if (command.type === 'subscribe') {
          expect(command.topics).toContain('db')
          sendDb = () => ws.send(JSON.stringify({ topic: 'db', type: 'updated', ts: '2026-11-09T10:02:00Z', run_id: 7, data: { table: 'signals', op: 'INSERT', pk: '18', run_id: 7 } }))
        }
      })
    })
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const url = new URL(route.request().url()); calls.push(url)
      const path = url.pathname
      let body: unknown = {}
      if (path.endsWith('/db/tables')) body = dbCounters.map(row => row.table === 'signals' ? { ...row, rows: count } : row)
      else if (path.endsWith('/db/activity')) body = dbActivity.filter(row => !url.searchParams.get('table') || row.table_name === url.searchParams.get('table'))
      else if (path.endsWith('/rows')) body = dbRows
      else if (path === '/api/sim/state') body = { running: false, current_run_id: 7, sim_time: '2026-11-09T10:01:00Z', speed: 1 }
      else if (path === '/api/sim/runs') body = { items: [{ id: 7, label: 'Demo current' }, { id: 6, label: 'Demo history' }] }
      else if (path === '/api/agent/runs') body = { items: [] }
      else if (path.startsWith('/api/refs/')) body = []
      await route.fulfill({ json: body })
    })
    await page.goto('/engine?step=2')
    await page.getByRole('tab', { name: lang === 'ru' ? 'Данные в БД' : 'Database activity', exact: true }).click()
    await expect(page).toHaveURL(/step=2&tab=db/)
    const root = page.getByTestId('db-activity')
    await expect(root.getByRole('heading', { name: lang === 'ru' ? 'Данные в БД' : 'Database activity', exact: true })).toBeVisible()
    await expect(root.getByText('120', { exact: true })).toBeVisible()
    await expect(root.getByRole('list', { name: lang === 'ru' ? 'Лента изменений' : 'Change feed' }).getByRole('button')).toHaveCount(4)
    await root.getByRole('button', { name: /SIG-000017/ }).click()
    const inspector = root.getByRole('region', { name: lang === 'ru' ? 'Инспектор JSON' : 'JSON inspector' })
    await expect(inspector).toContainText('external_contact')
    await inspector.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `../docs/screenshots/db-activity/db-inspect-${lang}-${theme}.png` })
    await root.getByRole('heading', { name: lang === 'ru' ? 'Данные в БД' : 'Database activity', exact: true }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: `../docs/screenshots/db-activity/db-top-${lang}-${theme}.png` })
    await root.getByLabel(lang === 'ru' ? 'Таблица' : 'Table', { exact: true }).selectOption('incidents')
    await expect.poll(() => calls.some(url => url.pathname.endsWith('/activity') && url.searchParams.get('table') === 'incidents')).toBe(true)
    await root.getByLabel(lang === 'ru' ? 'Область запусков' : 'Run scope', { exact: true }).selectOption('all')
    await expect.poll(() => calls.some(url => url.pathname.endsWith('/db/tables') && url.searchParams.get('run_id') === 'all')).toBe(true)
    await expect.poll(() => sendDb != null).toBe(true)
    count = 121
    sendDb!()
    await expect(root.getByText('121', { exact: true })).toBeVisible({ timeout: 1000 })
    await expect(root.getByText('+1', { exact: true })).toBeVisible()
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(root.getByRole('button', { name: lang === 'ru' ? 'Обновить' : 'Refresh', exact: true })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(2)
  })
}
