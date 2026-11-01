import { expect, test, type Page } from '@playwright/test'
import { client360Fixture as profile, client360Refs } from '../src/test/fixtures/client360'

const brief = { id: profile.id, public_id: profile.public_id, display_name: profile.display_name, segment_code: profile.segment_code, city_name: profile.city_name, churn_risk: profile.churn_risk, is_active: profile.is_active }
const signal = { ...profile.signals[0], client: brief, classification: null, decision: null }
const incident = { ...profile.incidents[0], primary_client: brief, run_id: 42, priority: 3, complexity: 'medium', criticality: 'medium', team_code: 'team_cx', created_sim: '2026-10-20T09:00:00Z', sla_due_sim: '2026-10-21T09:00:00Z', sla_remaining_pct: 100, decision: null }
const hitl = { id: 3, public_id: 'HD-000003', signal, incident, sim_run_id: 42, run_public_id: 'RUN-000042', reason: 'low_confidence', can_resume: false, process_outcome: 'deferred', agent_proposal: { kind: 'escalation' }, requested_sim: '2026-10-20T09:05:00Z' }

// Только UI/cache fixtures. Sim-time, run isolation, closure и gift statuses проверяет реальная PostgreSQL regression.
async function fixtureApi(page: Page, mode = 'light') {
  let reads = 0
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (!path.startsWith('/api/')) { await route.continue(); return }
    let body: unknown = {}
    if (path === '/api/clients/17/360') { reads++; body = profile }
    else if (path.startsWith('/api/refs/')) body = client360Refs[path.split('/').at(-1)!] ?? []
    else if (path === '/api/sim/state') body = { current_run_id: 42, sim_time: '2026-10-20T11:00:00Z', running: false, speed: 1 }
    else if (path === '/api/sim/runs') body = { items: [{ id: 42, label: 'Проверка клиента' }] }
    else if (path === '/api/settings') body = { ui: { theme_pack: 'brand', mode, density: 'comfortable' } }
    else if (path === '/api/signals') body = { items: [signal], total: 1 }
    else if (path === '/api/signals/7') body = signal
    else if (path === '/api/incidents/11') body = incident
    else if (/\/api\/incidents\/11\/(history|signals|comms|notifications)/.test(path)) body = []
    else if (path === '/api/hitl/queue') body = { items: [hitl], total: 1 }
    else if (path === '/api/hitl/3') body = hitl
    else if (path.endsWith('/feedback')) body = { items: [] }
    await route.fulfill({ json: body })
  })
  return { reads: () => reads, errors }
}

for (const source of ['signal', 'incident', 'hitl']) {
  test(`warm Client360 opens from ${source} within 300ms`, async ({ page }) => {
    const fixture = await fixtureApi(page)
    const prefetched = page.waitForResponse(response => response.url().includes('/api/clients/17/360'))
    await page.goto(source === 'incident' ? '/incidents/11' : `/?tab=${source === 'hitl' ? 'hitl' : 'signals'}`)
    if (source === 'signal') await page.getByText('Не прошла оплата картой', { exact: true }).click()
    await prefetched
    const link = page.getByRole('link', { name: 'Клиент 360', exact: true })
    await expect(link).toBeVisible()
    // Порог относится к интерфейсу: DOM click → painted profile, без RPC задержек Playwright.
    await link.evaluate(element => element.addEventListener('click', () => {
      const started = performance.now()
      const observer = new MutationObserver(() => {
        if (!document.querySelector('h1')?.textContent?.includes('Клиент 360 · Ирина Т.')) return
        observer.disconnect()
        requestAnimationFrame(() => requestAnimationFrame(() => {
          document.documentElement.dataset.client360Elapsed = String(performance.now() - started)
        }))
      })
      observer.observe(document.getElementById('root')!, { childList: true, subtree: true, characterData: true })
    }, { once: true, capture: true }))
    await link.click()
    await expect(page.getByRole('heading', { name: 'Клиент 360 · Ирина Т.' })).toBeVisible({ timeout: 300 })
    await expect.poll(() => page.evaluate(() => document.documentElement.dataset.client360Elapsed)).toBeTruthy()
    const elapsed = await page.evaluate(() => Number(document.documentElement.dataset.client360Elapsed))
    expect(elapsed).toBeLessThanOrEqual(300)
    test.info().annotations.push({ type: 'warm-profile-ms', description: elapsed.toFixed(1) })
    await expect(page.getByRole('link', { name: 'Инцидент закрытия счёта · INC-000011' })).toHaveAttribute('href', '/incidents/11')
    expect(fixture.reads()).toBe(1)
    expect(fixture.errors).toEqual([])
  })
}

for (const lang of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`Client360 ${lang} ${mode} profile and history`, async ({ page }, info) => {
    const fixture = await fixtureApi(page, mode)
    await page.addInitScript(({ lang, mode }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', mode) }, { lang, mode })
    await page.goto('/clients/17')
    await expect(page.getByRole('heading', { name: `${lang === 'ru' ? 'Клиент' : 'Client'} 360 · Ирина Т.` })).toBeVisible()
    await expect(page.getByText(lang === 'ru' ? 'Бонусные баллы' : 'Bonus points', { exact: true })).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
    expect(await page.locator('body').innerText()).not.toMatch(/client360\./)
    await page.screenshot({ path: info.outputPath('client360-top.png'), fullPage: true })
    await page.getByRole('heading', { name: lang === 'ru' ? 'Как менялось состояние' : 'State history' }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath('client360-history.png'), fullPage: true })
    expect(fixture.errors).toEqual([])
  })
}

for (const mode of ['light', 'dark']) {
  test(`Client360 mobile ${mode} has contained tables and readable history`, async ({ page }, info) => {
    const fixture = await fixtureApi(page, mode)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.addInitScript(mode => localStorage.setItem('cx.ui.mode', mode), mode)
    await page.goto('/clients/17?run_id=42')
    await expect(page.getByRole('heading', { name: 'Клиент 360 · Ирина Т.' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2)
    await page.getByRole('heading', { name: 'История операций', exact: true }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath('client360-mobile.png'), fullPage: true })
    expect(fixture.errors).toEqual([])
  })
}
