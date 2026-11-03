import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
const ru = JSON.parse(readFileSync(new URL('../src/shared/i18n/ru.json', import.meta.url), 'utf8'))
const en = JSON.parse(readFileSync(new URL('../src/shared/i18n/en.json', import.meta.url), 'utf8'))
import { formatCompactRub } from '../src/shared/lib/compactMoney'

test.describe.configure({ mode: 'serial' })
let C: number, K: number, plan: { closed_branch_code: string; xlsx_sha256: string; cohort_sha256: string }
let legal: { id: number; public_id: string; red_words: string[]; summary: string }, ordinary: { id: number; public_id: string }
let legalHd: { id: number; decision: null }, modes: string[], preparation: object
let cleanup: APIRequestContext, previousUi: unknown, changedUi = false
const headers = { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'deposits' }
async function json(request: APIRequestContext, path: string, params?: Record<string, string | number>, role = 'cx_lead') {
  const response = await request.get(path, { params, headers: { 'X-Cx-Role': role, ...(role === 'product_manager' ? { 'X-Cx-Product-Line': 'deposits' } : {}) } })
  expect(response.status(), path).toBe(200); return response.json()
}
async function all(request: APIRequestContext, path: string, query: Record<string, string | number>) {
  const rows = [], seen = new Set<string>(); let cursor: string | undefined
  do { const page = await json(request, path, { ...query, limit: 200, ...(cursor ? { cursor } : {}) }); rows.push(...page.items); cursor = page.next_cursor ?? undefined; if (cursor) { expect(seen.has(cursor)).toBe(false); seen.add(cursor) } } while (cursor)
  return rows
}
async function drain(request: APIRequestContext, run: number, count: number) {
  await expect.poll(async () => {
    const signals = await all(request, '/api/signals', { run_id: run }), agents = await all(request, '/api/agent/runs', { run_id: run, kind: 'agent' })
    const ids = new Set(signals.map(s => s.id)), linked = new Set(agents.map(a => a.signal_id))
    return { signals: ids.size, agents: agents.length, active: agents.filter(a => a.outcome == null).length, failed: agents.filter(a => ['failed', 'error'].includes(a.outcome)).length, missing: [...ids].filter(id => !linked.has(id)).length, foreign: [...linked].filter(id => !ids.has(id)).length, duplicates: agents.length - linked.size }
  }, { timeout: 120_000 }).toEqual({ signals: count, agents: count, active: 0, failed: 0, missing: 0, foreign: 0, duplicates: 0 })
}
test.beforeAll(async ({ request, playwright, baseURL }) => {
  test.setTimeout(150_000)
  if (!process.env.E2E_ISOLATED_SCENARIOS || !baseURL || !['127.0.0.1', 'localhost'].includes(new URL(baseURL).hostname)) throw new Error('T262 требует свой disposable localhost стенд и E2E_ISOLATED_SCENARIOS')
  cleanup = await playwright.request.newContext({ baseURL, timeout: 10_000 })
  const before = await json(request, '/api/sim/state'); expect(before.running).toBe(false)
  await expect.poll(async () => (await all(request, '/api/agent/runs', { run_id: before.current_run_id })).filter(a => a.outcome == null).length, { timeout: 120_000 }).toBe(0)
  const supplied = [process.env.E2E_T262_CSI_RUN_ID, process.env.E2E_T262_CABINET_RUN_ID]
  expect(supplied.every(v => v === undefined) || supplied.every(v => v !== undefined && /^[1-9][0-9]*$/.test(v) && Number.isSafeInteger(Number(v)))).toBe(true)
  const runs = []
  for (const [index, scenario, count] of [[0, 'csi_and_branches', 301], [1, 'cabinet_red_words_report', 2]] as const) {
    let run
    if (supplied[index]) run = await json(request, '/api/sim/runs/' + supplied[index])
    else { const response = await request.post(`/api/scenarios/${scenario}/run`, { data: { label: `T262 native UI ${scenario}`, reset_mode: 'counters', seed: 42 } }); expect(response.status()).toBe(202); run = (await response.json()).run }
    expect(run.kind).toBe('scenario'); expect(run.scenario_id).toBe(scenario)
    const roles = run.settings_snapshot.llm_profiles.roles
    expect(Object.keys(roles).sort()).toEqual(['fast', 'main', 'twin']); expect(Object.values(roles).every(role => (role as { provider: string }).provider === 'mock')).toBe(true)
    await drain(request, run.id, count); runs.push(await json(request, '/api/sim/runs/' + run.id))
  }
  C = runs[0].id; K = runs[1].id; plan = runs[0].settings_snapshot.t262_inputs
  expect(plan.xlsx_sha256).toMatch(/^[0-9a-f]{64}$/); expect(plan.cohort_sha256).toMatch(/^[0-9a-f]{64}$/)
  const state = await json(request, '/api/sim/state'); expect(state.running).toBe(false); expect(state.current_run_id).toBe(K)
  expect(Date.parse(state.sim_time)).toBe(Date.parse(before.sim_time)); expect(Date.parse(runs[0].started_sim)).toBe(Date.parse(runs[1].started_sim))
  const rows = await json(request, '/api/cabinet/signals', { run_id: K, product_line: 'deposits', period: 'week' }, 'product_manager')
  expect(rows.total).toBe(2); legal = rows.items.find((s: { flags: string[] }) => s.flags.includes('red_word')); ordinary = rows.items.find((s: { id: number }) => s.id !== legal.id)
  expect(legal.red_words).toEqual(expect.arrayContaining(['суд', 'налоговую']))
  const agents = await all(request, '/api/agent/runs', { run_id: K, kind: 'agent' })
  const legalAr = await json(request, '/api/agent/runs/' + agents.find(a => a.signal_id === legal.id).id)
  const ordinaryAr = await json(request, '/api/agent/runs/' + agents.find(a => a.signal_id === ordinary.id).id)
  expect(legalAr.outcome).toBe('awaiting_human')
  const calls = ordinaryAr.steps.flatMap((s: { tool_calls?: object[] }) => s.tool_calls ?? [])
  expect(calls).toEqual(expect.arrayContaining([expect.objectContaining({ name: 'route_to_product_team', wraps: ['route_to_department'], result: expect.objectContaining({ department: 'team_deposits' }) })]))
  modes = [...legalAr.steps, ...ordinaryAr.steps].map(s => s.model).filter((model): model is string => typeof model === 'string')
  expect(modes.length).toBeGreaterThan(0); expect(modes.every(model => model.startsWith('mock'))).toBe(true)
  const queue = await json(request, '/api/hitl/queue', { run_id: K }); legalHd = queue.items.find((h: { reason: string }) => h.reason === 'legal_regulatory'); expect(legalHd.decision).toBeNull()
  previousUi = (await json(cleanup, '/api/settings')).ui ?? null
  if (previousUi !== null) { expect((await cleanup.post('/api/settings/import', { data: { settings: { ui: null } } })).status()).toBe(200); changedUi = true }
  preparation = { C, K, sim_time: state.sim_time, plan, legal: { id: legal.id, ref: legal.public_id }, ordinary, legalHd: legalHd.id, models: modes, overallAcceptance: 'not_verified: LLM replay cassette and menu scope remain pending' }
})
test.afterAll(async () => { if (!cleanup) return; try { if (changedUi) expect((await cleanup.post('/api/settings/import', { data: { settings: { ui: previousUi } } })).status()).toBe(200) } finally { await cleanup.dispose() } })
async function presentation(page: Page, language: 'ru' | 'en', mode: 'light' | 'dark', role: string) {
  await page.addInitScript(({ language, mode, role }) => {
    for (const [k, v] of Object.entries({ 'cx.lang': language, 'cx.ui.mode': mode, 'cx.ui.layout': 'v2', 'cx.ui.theme_pack': 'brand', 'cx.ui.attention': 'calm', 'cx.ui.role': role })) localStorage.setItem(k, v)
    if (role === 'product_manager') localStorage.setItem('cx.ui.productLine', 'deposits'); else localStorage.removeItem('cx.ui.productLine')
  }, { language, mode, role })
  await page.emulateMedia({ reducedMotion: 'reduce' })
}
async function readonly(page: Page, origin: string) {
  const forbidden: string[] = [], errors: string[] = [], scoped: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/*', route => { const req = route.request(), url = new URL(req.url()); if (url.origin !== origin || !['GET', 'HEAD'].includes(req.method()) || url.pathname === '/api/metrics/economics' || /^\/api\/incidents\/\d+\/economics$/.test(url.pathname)) { forbidden.push(req.method() + ' ' + url.pathname); return route.abort() } if (url.pathname.startsWith('/api/cabinet/') || url.pathname === '/api/csi/analytics' || url.pathname.startsWith('/api/branches/')) scoped.push(url.pathname + url.search); return route.continue() })
  return { forbidden, errors, scoped }
}
for (const language of ['ru', 'en'] as const) for (const mode of ['light', 'dark'] as const) {
  test(`T262 cabinet native legal/route/961/XLSX ${language}/${mode}`, async ({ page, request, baseURL }, info) => {
    const t = language === 'ru' ? ru : en
    await presentation(page, language, mode, 'product_manager'); const traffic = await readonly(page, baseURL!)
    const expected = await json(request, '/api/cabinet/overview', { product_line: 'deposits', run_id: K, period: 'week' }, 'product_manager')
    expect(expected.kpi.signals).toBe(2)
    await page.goto(`/cabinet/deposits?run_id=${K}&period=week`)
    const root = page.locator('[data-cabinet]'); await expect(root.locator('[data-block]')).toHaveCount(7)
    await expect(page.locator('html')).toHaveAttribute('data-mode', mode); await expect(page.getByRole('contentinfo')).toContainText(/mock/i)
    await expect(root.getByRole('combobox', { name: t.shell.role, exact: true })).toHaveValue('product_manager')
    await expect(root.getByRole('combobox', { name: t.cabinet.productLine, exact: true })).toHaveValue('deposits')
    const card = root.locator('[data-block="cabinet-signals"] ol > li').filter({ hasText: legal.public_id })
    await expect(card).toHaveCSS('border-left-width', '4px'); await expect(card).toContainText(t.cabinet.redWords)
    await card.getByRole('button', { name: t.cabinet.openSignal, exact: true }).click()
    const drawer = page.getByRole('dialog', { name: t.cabinet.signalDetails, exact: true })
    for (const word of legal.red_words) await expect(drawer).toContainText(word)
    await expect(drawer.locator('input,textarea')).toHaveCount(0); await page.keyboard.press('Escape')
    await page.screenshot({ path: info.outputPath(`T262-cabinet-${language}-${mode}.png`) })
    await root.getByRole('button', { name: t.cabinet.openCalculator, exact: true }).click()
    const calc = page.getByRole('dialog', { name: t.cabinet.calculator, exact: true })
    await expect(calc.getByLabel(t.cabinet.rate)).toHaveValue('deposit')
    await expect(calc.getByLabel(t.cabinet.rate).locator('option:checked')).toContainText('961')
    const preview = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/api/metrics/economics/preview' && u.searchParams.get('affected') === '1000000' && u.searchParams.get('rate_code') === 'deposit' })
    await calc.getByLabel(t.incidentEconomics.affected).fill('1000000'); const response = await preview; expect(response.status()).toBe(200); const money = await response.json(); expect(money.rate_rub).toBe(961)
    await expect(calc.locator('[aria-live]')).toHaveText(formatCompactRub(-money.potential_loss_rub, language)); await expect(calc.locator('[aria-live]')).toContainText(language === 'ru' ? 'млн ₽' : ' m ₽')
    await page.screenshot({ path: info.outputPath(`T262-calculator-${language}-${mode}.png`) }); await page.keyboard.press('Escape')
    await root.getByRole('button', { name: t.cabinet.report, exact: true }).click(); await expect(page).toHaveURL(new RegExp(`/cabinet/deposits/report\\?period=week&run_id=${K}$`))
    await expect(page.locator('[data-report-page]')).toHaveCount(3)
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: (language === 'ru' ? 'Скачать ' : 'Download ') + 'XLSX', exact: true }).click()])
    expect(download.suggestedFilename()).toBe('cabinet-report.xlsx'); const path = info.outputPath(`T262-report-${language}-${mode}.xlsx`); await download.saveAs(path); const bytes = await readFile(path); expect(bytes.subarray(0, 2).toString()).toBe('PK')
    await page.screenshot({ path: info.outputPath(`T262-report-${language}-${mode}.png`) }); await page.setViewportSize({ width: 360, height: 800 }); await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth), { timeout: 1000 }).toBeLessThanOrEqual(360)
    await page.goto(`/cabinet/deposits?run_id=${K}&period=week`); await expect(page.locator('[data-cabinet] [data-block]')).toHaveCount(7); await page.screenshot({ path: info.outputPath(`T262-cabinet-${language}-${mode}-mobile.png`) })
    expect(traffic.scoped.every(path => !path.startsWith('/api/cabinet/') || new URL(path, baseURL).searchParams.get('run_id') === String(K))).toBe(true)
    expect((await json(request, `/api/hitl/${legalHd.id}`)).decision).toBeNull(); expect(traffic.forbidden).toEqual([]); expect(traffic.errors).toEqual([])
    await info.attach('native-receipt.json', { body: JSON.stringify({ ...preparation, language, mode, previewRate: money.rate_rub, affectedScenarioAssumption: 1000000, xlsxSha256: createHash('sha256').update(bytes).digest('hex'), traffic }), contentType: 'application/json' })
  })
}
for (const language of ['ru', 'en'] as const) for (const mode of ['light', 'dark'] as const) {
  test(`T262 CSI native 301/300/2400 and closed branch ${language}/${mode}`, async ({ page, request, baseURL }, info) => {
    const t = language === 'ru' ? ru : en
    await presentation(page, language, mode, 'cx_lead'); const traffic = await readonly(page, baseURL!)
    const expected = await json(request, '/api/csi/analytics', { run_id: C, period: 'month', limit: 50, scatter_limit: 1000 })
    expect(expected.coverage.complaints).toBe(301); expect(expected.coverage.uncohorted).toBe(1); expect(expected.probabilities.sample_complaints).toBe(300); expect(expected.probabilities.sample_visits).toBe(2400); expect(expected.probabilities.complete_cohorts).toBe(10); expect(expected.top_branches).toHaveLength(10)
    await page.goto(`/csi?run_id=${C}&period=month`); const root = page.getByRole('main', { name: t.csi.title, exact: true })
    await expect(root.locator('[data-block]')).toHaveCount(9); await expect(root.getByRole('combobox', { name: t.csi.run, exact: true })).toHaveValue(String(C)); await expect(page.locator('html')).toHaveAttribute('data-mode', mode); await expect(page.getByRole('contentinfo')).toContainText(/mock/i)
    await expect(root.locator('[data-block]').first().locator('tbody tr')).toHaveCount(expected.complaints.items.length)
    for (const row of expected.complaints.items) await expect(root.locator('a').filter({ hasText: row.signal_ref }).first()).toHaveAttribute('href', `/trace/signal/${row.signal_ref}?run_id=${C}`)
    await page.screenshot({ path: info.outputPath(`T262-csi-${language}-${mode}.png`) })
    await root.locator('[data-block]').nth(3).scrollIntoViewIfNeeded(); await expect(root.locator('[data-block]').nth(3).locator('svg')).toBeVisible(); await expect(root.locator('[data-block]').nth(3).locator('tbody tr')).toHaveCount(expected.tenure.groups.length); await expect(root.locator('[data-block]').nth(5).locator('tbody tr')).toHaveCount(expected.top_branches.length); await page.screenshot({ path: info.outputPath(`T262-csi-charts-${language}-${mode}.png`) })
    const sample = root.locator('[data-block]').nth(6); await sample.scrollIntoViewIfNeeded(); await expect(sample).toContainText('300'); await expect(sample).toContainText(new Intl.NumberFormat(language).format(2400))
    await expect(root.locator('[data-block]').nth(7)).toContainText('Spearman'); await page.screenshot({ path: info.outputPath(`T262-csi-sample-${language}-${mode}.png`) })
    await page.setViewportSize({ width: 390, height: 844 }); await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth), { timeout: 1000 }).toBeLessThanOrEqual(390); await page.screenshot({ path: info.outputPath(`T262-csi-${language}-${mode}-mobile.png`) }); await page.setViewportSize({ width: 1440, height: 1000 })
    const branch = await json(request, '/api/branches/' + encodeURIComponent(plan.closed_branch_code), { run_id: C, period: 'week' })
    expect(branch.branch.branch_status).toBe('closed'); expect(branch.signals.total).toBeGreaterThan(0); expect(branch.csi.probabilities.sample_visits).toBeNull(); const quietLabel = t.branchMap['closedSignals_' + new Intl.PluralRules(language).select(branch.signals.total)].replace('{{count}}', String(branch.signals.total))
    await page.goto(`/workspace?tab=map&run_id=${C}`); await page.getByRole('button', { name: t.branchMap.toggle, exact: true }).click(); await expect(page.getByTestId('branch-layer')).toBeVisible()
    const mark = page.locator(`[data-branch-codes~="${plan.closed_branch_code}"]`); await expect(mark).toBeAttached(); await mark.click()
    const member = page.getByRole('button', { name: new RegExp('^' + plan.closed_branch_code + ' ·') }); if (await member.count()) { await expect(member).toContainText(quietLabel); await member.click() } else await expect(mark).toContainText(quietLabel)
    await expect(page.getByRole('heading', { name: plan.closed_branch_code, exact: true })).toBeVisible(); await expect(page.locator(`a.block[href="/trace/branch/${branch.branch.id}?run_id=${C}"]`)).toBeVisible()
    await expect(page.getByRole('heading', { name: t.branchMap.pressure, exact: true })).toBeVisible(); await page.screenshot({ path: info.outputPath(`T262-closed-branch-${language}-${mode}.png`), fullPage: true })
    expect(traffic.scoped.filter(path => path.startsWith('/api/csi/analytics') || /^\/api\/branches\//.test(path)).every(path => new URL(path, baseURL).searchParams.get('run_id') === String(C))).toBe(true)
    expect((await json(request, '/api/sim/state')).current_run_id).toBe(K); expect(traffic.forbidden).toEqual([]); expect(traffic.errors).toEqual([])
    await info.attach('native-receipt.json', { body: JSON.stringify({ ...preparation, language, mode, csi: { coverage: expected.coverage, probabilities: expected.probabilities, top10: expected.top_branches.map((b: { branch_id: number }) => b.branch_id) }, branch: { id: branch.branch.id, code: branch.branch.code, status: branch.branch.branch_status, directSignals: branch.signals.total }, traffic }), contentType: 'application/json' })
  })
}


test('T262 recorded Mock journey replay preserves pending human boundary; not LLM cassette proof', async ({ page, request, baseURL }, info) => {
  await presentation(page, 'en', 'dark', 'cx_lead'); const traffic = await readonly(page, baseURL!)
  const actual = await json(request, '/api/journey/' + legal.public_id, { run_id: K })
  expect(actual.stages).toHaveLength(8); expect(actual.stages.some((stage: { status: string }) => stage.status === 'waiting_human')).toBe(true)
  await page.goto(`/journey/${legal.public_id}?run_id=${K}&mode=replay`)
  const recording = page.getByRole('region', { name: en.journeyModes.replay, exact: true })
  await expect(recording).toBeVisible(); const next = recording.getByRole('button', { name: en.journeyModes.next, exact: true })
  const mockTitles = actual.stages.flatMap((stage: { events: { title_ru: string; badges: { llm_source?: string } }[] }) => stage.events.filter(event => event.badges.llm_source === 'mock').map(event => event.title_ru))
  expect(mockTitles.length).toBeGreaterThan(0)
  await expect(next).toBeVisible(); let frames = 0, mockFrames = 0
  while (await next.isEnabled()) {
    expect(frames).toBeLessThan(200); await next.click(); frames++
    const card = recording.locator('button.my-2')
    await expect(card).toHaveCount(1)
    if (await card.locator('span').filter({ hasText: /^mock$/ }).count()) {
      mockFrames++
      const shown = await card.locator('strong').innerText()
      expect(mockTitles.some((title: string) => shown.endsWith(title))).toBe(true)
    }
  }
  expect(mockFrames).toBeGreaterThan(0)
  await expect(recording.locator('p[role="status"]')).toContainText(en.journeyModes.finished)
  await expect(recording).toContainText(en.journeyUi.status.waiting_human)
  await expect(page.getByRole('contentinfo')).toContainText(/mock/i)
  expect((await json(request, `/api/hitl/${legalHd.id}`)).decision).toBeNull()
  await page.screenshot({ path: info.outputPath('T262-recorded-Mock-replay-pending.png') })
  expect(traffic.forbidden).toEqual([]); expect(traffic.errors).toEqual([])
  await info.attach('native-receipt.json', { body: JSON.stringify({ ...preparation, recordingFrames: frames, mockSourceFrames: mockFrames, mode: 'UI recording replay of actual Mock history; not provider replay cassette', traffic }), contentType: 'application/json' })
})
