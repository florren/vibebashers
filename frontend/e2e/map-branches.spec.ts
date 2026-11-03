import { expect, test, type Request, type APIRequestContext } from '@playwright/test'
import type { components } from '../src/shared/api/types'
type Detail = components['schemas']['BranchDetailResponse']
type Directory = components['schemas']['BranchDirectoryResponse']
type AgentList = components['schemas']['AgentRunList']
type Signals = components['schemas']['SignalList']


async function nativeItems<T>(request: APIRequestContext, path: string, scope: Record<string, string>): Promise<T[]> {
  let cursor: string | undefined
  const seen = new Set<string>(), rows: T[] = []
  do {
    const response = await request.get(path, { params: { ...scope, limit: 500, ...(cursor ? { cursor } : {}) } })
    expect(response.status()).toBe(200)
    const data: { items?: T[]; next_cursor?: string | null } = await response.json()
    if (!Array.isArray(data.items) || !Object.hasOwn(data, 'next_cursor') || data.next_cursor !== null && typeof data.next_cursor !== 'string') throw new Error(path + ': malformed native page')
    rows.push(...data.items); cursor = data.next_cursor ?? undefined
    if (cursor) { expect(seen.has(cursor), 'Cursor не должен образовывать цикл').toBe(false); seen.add(cursor) }
  } while (cursor)
  return rows
}

// Только disposable synthetic стенд: preparation меняет current и сохраняет прежнюю историю.
// Темы меняются только в browser GET; бизнес-ответы API не подменяются.
// Scenarios project имеет один worker и запускается после settings/read-only файлов.
test.describe.configure({ mode: 'serial' })
let preparation: { setup_duration_ms: number; previous_run_id: number | null; run_id: number; sim_time: string; owner: string; received: number; agent_runs: number; active: number; missing: number; duplicate: number; foreign: number; failed: number }
test.beforeAll(async ({ request, baseURL }) => {
  // Только preparation budget: на CI205/301 графов за60s, на host301/301 за~39s.
  // Отдельный конечный drain сохраняет все301/active0/failed0 assertions; UI остаётся30s.
  test.setTimeout(150_000)
  const owner = process.env.E2E_ISOLATED_SCENARIOS?.trim()
  if (!owner || !baseURL || !['localhost', '127.0.0.1'].includes(new URL(baseURL).hostname)) throw new Error('Нужны E2E_ISOLATED_SCENARIOS и собственный disposable localhost стенд; preparation не выполнялась')
  const beforeResponse = await request.get('/api/sim/state')
  expect(beforeResponse.status()).toBe(200)
  const before = await beforeResponse.json()
  expect(before.running, 'Чужой активный clock автоматически не останавливается').toBe(false)
  if (before.current_run_id != null) {
    const prior = await nativeItems<NonNullable<AgentList['items']>[number]>(request, '/api/agent/runs', { run_id: String(before.current_run_id) })
    expect(prior.filter(row => row.outcome == null)).toHaveLength(0)
  }
  // Native T262 preflight проверяет effective Mock всех ролей до любых эффектов.
  const setupStarted = Date.now()
  const response = await request.post('/api/scenarios/csi_and_branches/run', { data: { label: 'T250 Playwright isolated map branches', reset_mode: 'counters', seed: 42 } })
  expect(response.status(), 'Нужен effective Mock и доступная native CSI preparation; live/replay не подменяются').toBe(202)
  const result = await response.json(), run = result.run
  expect(run).toMatchObject({ kind: 'scenario', scenario_id: 'csi_and_branches', status: 'paused', reset_mode: 'counters' })
  expect(Number.isSafeInteger(run.id) && run.id > 0).toBe(true)
  const roles = run.settings_snapshot.llm_profiles.roles
  expect(Object.keys(roles).sort()).toEqual(['fast', 'main', 'twin'])
  expect(Object.values(roles).every(role => (role as { provider: string }).provider === 'mock')).toBe(true)
  const afterResponse = await request.get('/api/sim/state')
  expect(afterResponse.status()).toBe(200)
  const after = await afterResponse.json()
  expect(after.current_run_id).toBe(run.id); expect(after.running).toBe(false)
  expect(Date.parse(after.sim_time)).toBe(Date.parse(before.sim_time))
  // У настоящего image работают actors. До read-only фазы все301 received
  // проходят normal graph; awaiting_human/deferred не требуют human accept.
  let observed = { received: 0, agent_runs: 0, active: 0, missing: 0, duplicate: 0, foreign: 0, failed: 0 }
  await expect.poll(async () => {
    const source = await nativeItems<NonNullable<Signals['items']>[number]>(request, '/api/signals', { run_id: String(run.id) })
    const agents = await nativeItems<NonNullable<AgentList['items']>[number]>(request, '/api/agent/runs', { run_id: String(run.id), kind: 'agent' })
    const sourceIds = new Set(source.map(row => row.id)), agentIds = new Set(agents.map(row => row.signal_id))
    expect(source.every(row => Number.isSafeInteger(row.id) && row.id! > 0)).toBe(true)
    expect(agents.every(row => Number.isSafeInteger(row.signal_id) && row.signal_id! > 0 && row.kind === 'agent')).toBe(true)
    observed = {
      received: sourceIds.size, agent_runs: agentIds.size, active: agents.filter(row => row.outcome == null).length,
      missing: [...sourceIds].filter(id => !agentIds.has(id)).length,
      duplicate: source.length - sourceIds.size + agents.length - agentIds.size,
      foreign: [...agentIds].filter(id => !sourceIds.has(id!)).length,
      failed: agents.filter(row => row.outcome === 'failed').length,
    }
    return observed
  }, { timeout: 120_000 }).toEqual({ received: 301, agent_runs: 301, active: 0, missing: 0, duplicate: 0, foreign: 0, failed: 0 })
  const ready = await request.get('/api/sim/state')
  expect(ready.status()).toBe(200)
  const finalState = await ready.json()
  expect(finalState.current_run_id).toBe(run.id); expect(finalState.running).toBe(false)
  expect(Date.parse(finalState.sim_time)).toBe(Date.parse(before.sim_time))
  preparation = { setup_duration_ms: Date.now() - setupStarted, previous_run_id: before.current_run_id, run_id: run.id, sim_time: after.sim_time, owner, ...observed }
})
for (const language of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`ВСП: native counts, карточка и scope ${language} ${mode}`, async ({ browser, baseURL }, info) => {
    if (!baseURL) throw new Error('Нужен E2E_BASE_URL synthetic стенда')
    await info.attach('isolated-preparation.json', { body: JSON.stringify(preparation), contentType: 'application/json' })
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const forbidden: string[] = [], failures: string[] = [], pending = new Set<Request>()
    const details = new Map<string, Detail>(), directory = new Map<string, string | null | undefined>(), bodies: Promise<void>[] = []
    const responses: { url: string; status: number }[] = [], bodyErrors: string[] = []
    const trackBody = (body: Promise<void>, source: string) => {
      // Контекст сохраняем сразу; rejected promise остаётся в bodies и ниже
      // обязательно await: ошибка не превращается в успешный/пустой response.
      void body.catch(error => bodyErrors.push(source + ': ' + String(error)))
      bodies.push(body)
    }
    let directoryComplete = false
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
        responses.push({ url: path + new URL(response.url()).search, status: response.status() })
        if (response.status() >= 400) failures.push(response.status() + ' ' + path)
        if (path === '/api/branches' && response.ok()) trackBody(response.json().then((data: Directory) => {
          data.items.forEach(branch => directory.set(branch.code, branch.branch_status)); if (data.next_cursor == null) directoryComplete = true
        }), path + ' status=' + response.status())
        if (/^\/api\/branches\/(?!analytics$)[^/]+$/.test(path) && response.ok()) trackBody(response.json().then((detail: Detail) => { details.set(detail.branch.code, detail) }), path + ' status=' + response.status())
      })
      await page.goto('/workspace?tab=map')
      await expect(page).toHaveURL(/run_id=current/)
      const toggle = page.getByRole('button', { name: language === 'ru' ? 'ВСП' : 'Branches', exact: true })
      const started = Date.now(); await toggle.click()
      await expect(page.getByTestId('branch-layer')).toBeVisible()
      await expect(page.getByRole('heading', { name: language === 'ru' ? 'Динамика сети: 12 месяцев' : 'Network history: 12 months', exact: true })).toBeVisible()
      // Между партиями pending=0 — это не завершение всего fanout. Ждём native
      // последнюю directory page и detail для каждого реально закрытого ВСП.
      await expect.poll(() => bodyErrors.length > 0 || directoryComplete && [...directory].filter(([, status]) => status === 'closed').every(([code]) => details.has(code))).toBe(true)
      await expect.poll(() => pending.size).toBe(0); await Promise.all(bodies)
      const target = [...details.values()].find(row => row.branch.branch_status === 'closed' && row.signals.total > 0)
      expect(target, 'Нужен actual closed branch с direct signal, не city-zone proxy').toBeTruthy()
      info.annotations.push({ type: 'branches_all_reads_ms', description: String(Date.now() - started) })
      const code = target!.branch.code, run = String(target!.scope.run_ids![0])
      expect(run).toBe(String(preparation.run_id))
      await page.locator(`[data-branch-codes~="${code}"]`).click()
      const member = page.getByRole('button', { name: new RegExp('^' + code + ' ·') })
      if (await member.count()) {
        await expect(member).toContainText(String(target!.signals.total)); await member.click()
      }
      await expect(page.getByRole('heading', { name: code, exact: true })).toBeVisible()
      await expect(page.locator(`a.block[href="/trace/branch/${target!.branch.id}?run_id=${run}"]`)).toBeVisible()
      await expect(page.locator('a[href*="/trace/signal/"]').first()).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: info.outputPath('branch.png'), fullPage: true })
      await page.getByRole('button', { name: language === 'ru' ? 'Закрыть' : 'Close', exact: true }).click()
      await toggle.click(); await expect(page.getByTestId('branch-layer')).toHaveCount(0)
      expect(forbidden).toEqual([]); expect(failures).toEqual([])
    } finally {
      await context.unrouteAll({ behavior: 'wait' })
      await info.attach('native-network.json', { body: JSON.stringify({ responses, forbidden, failures, bodyErrors }), contentType: 'application/json' })
      await context.close()
    }
  })
}
