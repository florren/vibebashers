import type { components } from '../src/shared/api/types'
import { expect, test } from '@playwright/test'

// Только синтетический локальный API transport; никаких обращений к LLM-провайдерам.
const LOCAL = 'http://127.0.0.1:19999/v1'
for (const theme of ['light', 'dark']) for (const lang of ['ru', 'en'] as const) {
  test(`T051 profile keys ${theme} ${lang}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1600 })
    await page.addInitScript(({ theme, lang }) => { localStorage.setItem('cx.ui.mode', theme); localStorage.setItem('cx.lang', lang) }, { theme, lang })
    const errors: string[] = [], remote: string[] = [], patches: Record<string, unknown>[] = [], checks: Record<string, unknown>[] = []
    let keyCreates = 0
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('request', (request) => { if (!['127.0.0.1', 'localhost'].includes(new URL(request.url()).hostname)) remote.push(new URL(request.url()).hostname) })
    const profiles = [
      { id: 1, code: 'fixture-local', provider: 'openai_compatible', model: 'fixture-model', base_url: LOCAL, api_key_id: 11, role: 'main', is_active: true },
      { id: 2, code: 'fixture-giga', provider: 'gigachat', model: 'fixture-model', base_url: null, api_key_id: 13, role: 'fast', is_active: true },
      { id: 3, code: 'fixture-inactive', provider: 'openai_compatible', model: 'fixture-model', base_url: LOCAL, api_key_id: 12, role: 'bench_only', is_active: false },
      { id: 4, code: 'fixture-missing', provider: 'openai_compatible', model: 'fixture-model', base_url: LOCAL, api_key_id: 99, role: 'bench_only', is_active: false },
    ]
    const keys: components['schemas']['LlmApiKey'][] = [
      { id: 11, label: 'Fixture local', provider: 'openai_compatible', key_hint: '••••', endpoint_url: LOCAL, is_active: true, tokens_used: 240, tokens_limit: 10000, requests_today: 3, rpd_limit: 40, balance_usd: 24.5 },
      { id: 12, label: 'Fixture inactive', provider: 'openai_compatible', key_hint: '••••', endpoint_url: LOCAL, is_active: false, tokens_used: 10000, tokens_limit: 10000, requests_today: 40, rpd_limit: 40 },
      { id: 13, label: 'Fixture Giga', provider: 'gigachat', key_hint: '••••', endpoint_url: 'https://example.test/giga', scope: 'GIGACHAT_API_PERS', is_active: true, tokens_used: 100, tokens_limit: 1000, requests_today: 1, rpd_limit: 20 },
    ]
    await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
      const path = new URL(route.request().url()).pathname, method = route.request().method()
      let body: unknown = {}, status = 200
      if (path === '/api/setup/status') body = { current_step: 1, completed: false, steps_done: [] }
      else if (path === '/api/setup') body = { llm: { main_profile_id: 1, fast_profile_id: 2 } }
      else if (path === '/api/settings/env') body = { items: [{ key: 'OPENROUTER_BASE_URL', value: LOCAL }, { key: 'GIGACHAT_SCOPE', value: 'GIGACHAT_API_PERS' }] }
      else if (path === '/api/settings/llm-profiles') body = profiles
      else if (path.endsWith('/llm-profiles/1') && method === 'PATCH') {
        const patch = route.request().postDataJSON(); patches.push(patch); Object.assign(profiles[0]!, patch)
      } else if (path === '/api/setup/test-llm') { checks.push(route.request().postDataJSON()); body = { ok: true, latency_ms: 2, model_reported: 'fixture-model' } }
      else if (path === '/api/settings/llm-keys' && method === 'POST') {
        const submitted = route.request().postDataJSON(); keyCreates++
        expect(Object.keys(submitted)).toEqual(expect.arrayContaining(['provider', 'label', 'key', 'endpoint_url']))
        expect(submitted).not.toHaveProperty('scope')
        const saved = { id: 15, label: 'Fixture new', provider: 'openai_compatible' as const, key_hint: '••••', endpoint_url: LOCAL, is_active: true, tokens_used: 0, requests_today: 0 }
        keys.push(saved); body = saved; status = 201
      } else if (path === '/api/settings/llm-keys') body = keys
      else if (path.includes('/llm-keys/') && method === 'DELETE') { body = { detail: 'Bound key' }; status = 409 }
      else if (path.startsWith('/api/refs/')) body = []
      await route.fulfill({ json: body, status })
    })
    const l = lang === 'ru' ? { save: 'Сохранить URL / ключ', check: 'Проверить', binding: 'API-ключ профиля fixture-local', keyLabel: 'Метка ключа', secret: 'Ключ (только запись)', endpoint: 'Endpoint ключа', add: 'Сохранить ключ', created: 'Ключ сохранён. Введённое значение очищено.', delete: 'Удалить ключ Fixture local' } : { save: 'Save URL / key', check: 'Check', binding: 'API key for fixture-local', keyLabel: 'Key label', secret: 'Key (write only)', endpoint: 'Key endpoint', add: 'Save key', created: 'Key saved. The entered value has been cleared.', delete: 'Delete key Fixture local' }
    await page.goto('/setup?step=1')
    const row = page.getByRole('row').filter({ hasText: 'fixture-local' })
    await expect(row.getByRole('combobox', { name: l.binding })).toHaveValue('11')
    await expect(page.getByRole('row').filter({ hasText: 'fixture-inactive' }).getByRole('button', { name: l.check, exact: true })).toBeDisabled()
    await expect(page.getByRole('row').filter({ hasText: 'fixture-missing' }).getByRole('combobox')).toHaveValue('99')
    expect(checks).toHaveLength(0)
    await row.getByRole('button', { name: l.save }).click()
    await expect.poll(() => patches.length).toBe(1); expect(patches[0]).not.toHaveProperty('api_key_id')
    await row.getByRole('button', { name: l.check, exact: true }).click()
    await expect.poll(() => checks.length).toBe(1); expect(checks[0]).toMatchObject({ api_key_id: 11, base_url: LOCAL })
    await row.getByRole('combobox', { name: l.binding }).selectOption('')
    await row.getByRole('button', { name: l.save }).click()
    await expect.poll(() => patches.length).toBe(2); expect(patches[1]).toHaveProperty('api_key_id', null)
    const canary = crypto.randomUUID()
    await page.getByLabel(l.keyLabel, { exact: true }).fill('Fixture new')
    await page.getByLabel(l.secret, { exact: true }).fill(canary)
    await page.getByRole('textbox', { name: new RegExp(`^${l.endpoint}`) }).fill(LOCAL)
    await page.getByRole('button', { name: l.add, exact: true }).click()
    await expect(page.getByText(l.created)).toBeVisible(); expect(keyCreates).toBe(1)
    await expect(page.getByLabel(l.secret, { exact: true })).toHaveValue('')
    expect(await page.locator('body').innerText()).not.toContain(canary)
    await row.getByRole('combobox', { name: l.binding }).selectOption('15')
    await row.getByRole('button', { name: l.save }).click()
    await expect.poll(() => patches.length).toBe(3); expect(patches[2]).toHaveProperty('api_key_id', 15)
    await row.getByRole('button', { name: l.check, exact: true }).click()
    await expect.poll(() => checks.length).toBe(2); expect(checks[1]).toMatchObject({ api_key_id: 15, base_url: LOCAL })
    await page.getByRole('button', { name: l.delete, exact: true }).click()
    await expect(page.getByText(lang === 'ru' ? 'Ключ привязан к профилю. Сначала явно снимите привязку и сохраните профиль.' : 'This key is bound to a profile. Explicitly unbind it and save the profile first.', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2)
    await page.screenshot({ path: info.outputPath(`profile-keys-${theme}-${lang}.png`), fullPage: true })
    expect(errors).toEqual([]); expect(remote).toEqual([])
  })
}
