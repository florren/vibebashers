import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import type { LlmApiKey, LlmProfileT } from '@/shared/api/client'
import { SetupPage } from '../SetupPage'

const LOCAL = 'http://127.0.0.1:12345/v1'
let profile: LlmProfileT
let keys: LlmApiKey[]
let failCreate = false
let failCheck = false
let reflected: string
let calls: { url: string; method: string; body: Record<string, unknown> }[]
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/setup?step=1']}><SetupPage /></MemoryRouter></QueryClientProvider>)
  return client
}
const row = () => screen.getByText('local-profile').closest('tr')!
beforeEach(() => {
  profile = { id: 1, code: 'local-profile', provider: 'openai_compatible', model: 'fixture', role: 'bench_only', is_active: true, base_url: LOCAL, api_key_id: 11 }
  keys = [
    { id: 11, label: 'local-key', provider: 'openai_compatible', key_hint: '••••', is_active: true, endpoint_url: LOCAL, tokens_used: 20, tokens_limit: 100, requests_today: 2, rpd_limit: 10, usage_known: true, tokens_remaining: 80, requests_known: true, requests_remaining: 8 },
    { id: 12, label: 'inactive-key', provider: 'openai_compatible', key_hint: '••••', is_active: false, endpoint_url: LOCAL },
    { id: 13, label: 'giga-key', provider: 'gigachat', key_hint: '••••', is_active: true, endpoint_url: 'https://example.test/giga', scope: 'GIGACHAT_API_PERS' },
    { id: 14, label: 'other-endpoint', provider: 'openai_compatible', key_hint: '••••', is_active: true, endpoint_url: 'https://other.test/v1' },
  ]
  calls = []; failCreate = false; failCheck = false; reflected = crypto.randomUUID()
  vi.stubGlobal('fetch', vi.fn(async (input, init) => {
    const url = String(input), method = init?.method ?? 'GET', body = init?.body ? JSON.parse(String(init.body)) : {}
    calls.push({ url, method, body })
    if (url === '/api/setup/status') return response({ current_step: 1, steps_done: [], completed: false })
    if (url === '/api/setup') return response({ llm: {} })
    if (url === '/api/settings/env') return response({ items: [{ key: 'OPENROUTER_BASE_URL', value: LOCAL }, { key: 'GIGACHAT_SCOPE', value: 'GIGACHAT_API_PERS' }] })
    if (url === '/api/settings/llm-profiles') return response([profile])
    if (url.endsWith('/llm-profiles/1') && method === 'PATCH') { profile = { ...profile, ...body }; return response({}) }
    if (url === '/api/settings/llm-keys' && method === 'POST') {
      if (failCreate) return response({ detail: reflected }, 422)
      const item = { id: 15, provider: body.provider, label: body.label, key_hint: '••••', endpoint_url: body.endpoint_url || LOCAL, scope: body.scope, is_active: true }
      keys = [...keys, item]; return response(item, 201)
    }
    if (url === '/api/settings/llm-keys') return response(keys)
    if (url.includes('/llm-keys/') && method === 'DELETE') return response({ detail: reflected }, 409)
    if (url === '/api/setup/test-llm') return response(failCheck ? { ok: false, error: reflected, quota: { private: reflected } } : { ok: true, latency_ms: 3, model_reported: 'fixture' })
    return response({})
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('сохраняет binding при обычном PATCH, передаёт точный keyID в Check и не проверяет автоматически', async () => {
  mount(); await screen.findByText('local-profile'); await within(row()).findByDisplayValue(LOCAL)
  await waitFor(() => expect(within(row()).getByRole('combobox', { name: 'API-ключ профиля local-profile' })).toHaveValue('11'))
  expect(screen.getByText('Осталось: 80')).toBeInTheDocument()
  expect(calls.filter((call) => call.url.endsWith('/test-llm'))).toHaveLength(0)
  fireEvent.click(within(row()).getByText('Сохранить URL / ключ'))
  await waitFor(() => expect(calls.find((call) => call.method === 'PATCH')).toBeDefined())
  expect(calls.find((call) => call.method === 'PATCH')!.body).not.toHaveProperty('api_key_id')
  fireEvent.click(within(row()).getByText('Проверить'))
  await waitFor(() => expect(calls.find((call) => call.url.endsWith('/test-llm'))).toBeDefined())
  expect(calls.find((call) => call.url.endsWith('/test-llm'))!.body).toEqual({ provider: profile.provider, model: profile.model, base_url: LOCAL, api_key_id: 11 })
})
it('explicit unbind отправляет null, затем unchanged PATCH снова omits binding', async () => {
  mount(); await screen.findByText('local-profile'); await within(row()).findByDisplayValue(LOCAL)
  const select = within(row()).getByRole('combobox', { name: 'API-ключ профиля local-profile' })
  fireEvent.change(select, { target: { value: '' } })
  fireEvent.click(within(row()).getByText('Сохранить URL / ключ'))
  await waitFor(() => expect(profile.api_key_id).toBeNull())
  await waitFor(() => expect(within(row()).getByRole('combobox', { name: 'API-ключ профиля local-profile' })).toHaveValue(''))
  await waitFor(() => expect(calls.filter((call) => call.url === '/api/settings/llm-profiles')).toHaveLength(2))
  fireEvent.click(within(row()).getByText('Сохранить URL / ключ'))
  await waitFor(() => expect(calls.filter((call) => call.method === 'PATCH')).toHaveLength(2))
  expect(calls.filter((call) => call.method === 'PATCH')[0]!.body).toHaveProperty('api_key_id', null)
  expect(calls.filter((call) => call.method === 'PATCH')[1]!.body).not.toHaveProperty('api_key_id')
})
it.each([12, 99, 13, 14])('не очищает невалидный boundID %s и не переключается на env', async (id) => {
  profile.api_key_id = id
  mount(); await screen.findByText('local-profile'); await within(row()).findByDisplayValue(LOCAL)
  await waitFor(() => expect(within(row()).getByRole('combobox', { name: 'API-ключ профиля local-profile' })).toHaveValue(String(id)))
  expect(within(row()).getByText('Проверить')).toBeDisabled()
  expect(within(row()).getByText('Сохранить URL / ключ')).toBeDisabled()
  expect(within(row()).getByRole('alert')).toBeInTheDocument()
  expect(calls.filter((call) => call.method !== 'GET')).toHaveLength(0)
})
it('Giga URL unknown допускает server validation без подстановки endpoint ключа', async () => {
  profile = { ...profile, provider: 'gigachat', base_url: null, api_key_id: 13 }
  mount(); await screen.findByText(/URL профиля не задан/)
  expect(within(row()).getByText('Проверить')).toBeEnabled()
  fireEvent.click(within(row()).getByText('Проверить'))
  await waitFor(() => expect(calls.find((call) => call.url.endsWith('/test-llm'))).toBeDefined())
  expect(calls.find((call) => call.url.endsWith('/test-llm'))!.body).toEqual({ provider: 'gigachat', model: 'fixture', api_key_id: 13 })
})
it('создаёт ключ через generated DTO с endpoint/scope, очищает password и mutation cache после success', async () => {
  const client = mount(); await screen.findByText('Реестр API-ключей')
  fireEvent.change(screen.getByLabelText('Метка ключа'), { target: { value: 'new-label' } })
  fireEvent.change(screen.getByLabelText('Провайдер ключа'), { target: { value: 'gigachat' } })
  fireEvent.change(screen.getByLabelText('Ключ (только запись)'), { target: { value: reflected } })
  fireEvent.change(screen.getByLabelText('Endpoint ключа', { exact: false }), { target: { value: 'https://example.test/giga' } })
  fireEvent.change(screen.getByLabelText('OAuth scope', { exact: false }), { target: { value: 'GIGACHAT_API_PERS' } })
  fireEvent.click(screen.getByText('Сохранить ключ'))
  await screen.findByText('Ключ сохранён. Введённое значение очищено.')
  expect(screen.getByLabelText('Ключ (только запись)')).toHaveValue('')
  expect(document.body.textContent).not.toContain(reflected)
  await waitFor(() => expect(JSON.stringify(client.getMutationCache().getAll().map((mutation) => mutation.state.variables))).not.toContain(reflected))
  expect(calls.find((call) => call.url.endsWith('/llm-keys') && call.method === 'POST')!.body).toMatchObject({ provider: 'gigachat', key: reflected, endpoint_url: 'https://example.test/giga', scope: 'GIGACHAT_API_PERS' })
})
it('отражает DELETE409 и не выдаёт секрет из create/check error или opaque quota', async () => {
  failCreate = true; failCheck = true
  mount(); await screen.findByRole('button', { name: 'Удалить ключ local-key' })
  fireEvent.click(screen.getByRole('button', { name: 'Удалить ключ local-key' }))
  await screen.findByText(/Ключ привязан к профилю/)
  fireEvent.change(screen.getByLabelText('Метка ключа'), { target: { value: 'failed-label' } })
  fireEvent.change(screen.getByLabelText('Ключ (только запись)'), { target: { value: reflected } })
  fireEvent.click(screen.getByText('Сохранить ключ'))
  await screen.findByText(/Операция с ключом не выполнена/)
  fireEvent.click(within(row()).getByText('Проверить'))
  await screen.findByText(/Проверка не выполнена/)
  expect(document.body.textContent).not.toContain(reflected)
})
it('создаёт профиль с выбранным keyID и сохраняет несовместимый выбор при смене provider до явной правки', async () => {
  mount(); await screen.findByText('local-profile')
  fireEvent.change(screen.getByLabelText('code'), { target: { value: 'new-profile' } })
  fireEvent.change(screen.getByLabelText('Модель', { exact: true }), { target: { value: 'fixture' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'API-ключ нового профиля' }), { target: { value: '11' } })
  fireEvent.click(screen.getByText('Добавить профиль'))
  await waitFor(() => expect(calls.find((call) => call.url.endsWith('/llm-profiles') && call.method === 'POST')).toBeDefined())
  expect(calls.find((call) => call.url.endsWith('/llm-profiles') && call.method === 'POST')!.body).toHaveProperty('api_key_id', 11)
  fireEvent.change(screen.getByLabelText('Провайдер', { exact: true }), { target: { value: 'gigachat' } })
  expect(screen.getByRole('combobox', { name: 'API-ключ нового профиля' })).toHaveValue('11')
  expect(screen.getByLabelText('Основной URL', { exact: false })).toHaveValue('')
  expect(screen.getByText('Добавить профиль')).toBeDisabled()
})
