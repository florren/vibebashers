import { expect, test, type Page } from '@playwright/test'
import { compareProfiles, compareResponse, compareTrace, selectedClassification } from '../src/test/fixtures/compare'

/** Только page-local UI fixtures. Реальные API/DB и MockProvider проверяются отдельно. */
async function setup(page: Page, lang = 'ru', theme = 'light') {
  await page.addInitScript(({ lang, theme }) => { localStorage.setItem('cx.lang', lang); localStorage.setItem('cx.ui.mode', theme) }, { lang, theme })
  const state = { calls: [] as Record<string, unknown>[], response: structuredClone(compareResponse), status: 200, model: 'replay:recorded-test-model', hold: null as (() => void) | null, pending: false }
  await page.routeWebSocket('**/ws/stream', ws => { ws.onMessage(() => {}) })
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/agent/compare') {
      state.calls.push(route.request().postDataJSON() as Record<string, unknown>)
      if (state.pending) await new Promise<void>(resolve => { state.hold = resolve })
      return route.fulfill({ status: state.status, json: state.status === 200 ? state.response : { detail: 'Shared jury limit: 20 requests/min', status: state.status } })
    }
    if (path === '/api/settings/llm-profiles') return route.fulfill({ json: compareProfiles })
    if (path === '/api/refs/channels') return route.fulfill({ json: [{ code: 'chat', name_ru: 'Чат', name_en: 'Chat' }] })
    if (/^\/api\/agent\/runs\/\d+$/.test(path)) return route.fulfill({ json: compareTrace(Number(path.split('/').at(-1)), path.endsWith('301') ? state.model : undefined, path.endsWith('301') && state.model.startsWith('mock:') ? 'fallback' : 'ok') })
    return route.fulfill({ json: path === '/api/sim/state' ? { current_run_id: 1, running: false, sim_time: '2026-11-01T11:00:00Z', current_run_status: 'paused' } : path.startsWith('/api/refs/') ? [] : {} })
  })
  return state
}
for (const lang of ['ru', 'en']) for (const theme of ['light', 'dark']) {
  test(`agent compare ${lang} ${theme}: form results diff and mobile`, async ({ page }) => {
    const state = await setup(page, lang, theme)
    await page.goto('/engine?tab=compare')
    const root = page.getByTestId('agent-compare')
    await expect(root.getByRole('heading', { name: lang === 'ru' ? 'ИИ против правил' : 'AI versus rules', exact: true })).toBeVisible()
    await root.getByRole('button', { name: lang === 'ru' ? 'Сарказм' : 'Sarcasm', exact: true }).click()
    expect(state.calls).toHaveLength(0)
    const profile = root.getByRole('combobox', { name: lang === 'ru' ? 'Профиль для сравнения' : 'Comparison profile', exact: true })
    await expect(profile.getByRole('option', { name: /inactive/ })).toHaveCount(0)
    await profile.selectOption('9')
    await page.screenshot({ path: `../docs/screenshots/compare/compare-form-${lang}-${theme}.png`, animations: 'disabled' })
    await root.getByRole('button', { name: lang === 'ru' ? 'Сравнить' : 'Compare', exact: true }).click()
    const results = root.getByRole('region', { name: lang === 'ru' ? 'Результаты сравнения' : 'Comparison results', exact: true })
    await expect(results).toContainText('replay:recorded-test-model')
    expect(state.calls).toHaveLength(1); expect(state.calls[0]?.llm_profile_id).toBe(9)
    await expect(results).toContainText(selectedClassification.rationale_ru)
    await expect(results.getByRole('link', { name: /301/ })).toHaveAttribute('href', '/engine/301')
    await results.evaluate(node => node.scrollIntoView({ block: 'start' }))
    await page.screenshot({ path: `../docs/screenshots/compare/compare-results-${lang}-${theme}.png`, animations: 'disabled' })
    await page.setViewportSize({ width: 390, height: 844 })
    await results.evaluate(node => node.scrollIntoView({ block: 'start' }))
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2)
    await page.screenshot({ path: `../docs/screenshots/compare/compare-mobile-${lang}-${theme}.png`, animations: 'disabled' })
  })
}
test('agent compare equality, unknown legacy source and honest fallback', async ({ page }) => {
  const state = await setup(page); state.response.mock = state.response.llm; state.response.diff = []; state.model = 'GigaChat-legacy'
  await page.goto('/engine?tab=compare')
  const root = page.getByTestId('agent-compare'), text = root.getByRole('textbox', { name: 'Текст обращения' })
  await text.fill('Проверка совпадения результатов')
  await root.getByRole('button', { name: 'Сравнить', exact: true }).click()
  const results = root.getByRole('region', { name: 'Результаты сравнения' })
  await expect(results).toContainText('Это не доказывает превосходство модели.')
  await expect(results.getByRole('article', { name: 'Выбранный профиль', exact: true })).toContainText('Источник неизвестен')
  state.model = 'mock:mock-rules-v1'
  await text.fill('Новый вход для проверки резерва')
  await expect(results).toBeHidden()
  await root.getByRole('button', { name: 'Сравнить', exact: true }).click()
  await expect(results.getByRole('article', { name: 'Выбранный профиль', exact: true })).toContainText('Резервный mock')
  await expect(results.getByRole('article', { name: 'Выбранный профиль', exact: true })).not.toContainText('Live')
  await expect(results.getByRole('article', { name: 'Mock — правила', exact: true })).not.toContainText('Резервный mock')
})
test('agent compare validates input, blocks duplicate pending and exposes 429', async ({ page }) => {
  const state = await setup(page); state.pending = true
  await page.goto('/engine?tab=compare')
  const root = page.getByTestId('agent-compare'), text = root.getByRole('textbox', { name: 'Текст обращения' }), submit = root.getByRole('button', { name: 'Сравнить', exact: true })
  await text.fill('аа'); await expect(submit).toBeDisabled()
  await text.fill('а'.repeat(5000)); await expect(text).toHaveAttribute('maxlength', '5000')
  const client = root.getByRole('textbox', { name: 'Клиент (ID)' })
  await client.fill('-1'); await expect(submit).toBeDisabled(); await client.fill('')
  await submit.click()
  await expect(root.getByRole('button', { name: 'Сравнивается…', exact: true })).toBeDisabled()
  await expect.poll(() => state.hold != null).toBe(true); expect(state.calls).toHaveLength(1)
  state.status = 429; state.hold!()
  await expect(root).toContainText('Shared jury limit: 20 requests/min')
  await expect(root.getByRole('region', { name: 'Результаты сравнения' })).toBeHidden()
  expect(state.calls).toHaveLength(1)
})
