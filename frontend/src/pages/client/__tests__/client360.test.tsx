import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Client360Page } from '../Client360Page'
import { ClientProfileLink } from '@/shared/components/ClientProfileLink'
import { client360Fixture as profile, client360Refs } from '@/test/fixtures/client360'
import i18n from '@/shared/i18n'
import en from '@/shared/i18n/en.json'
import ru from '@/shared/i18n/ru.json'
import { ClientState } from '@/shared/contracts/enums'
import { useWs } from '@/shared/ws/client'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
let profileRequests: string[]
function fetchFixture(profileValue: unknown = profile) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    if (url.pathname.includes('/360')) { profileRequests.push(url.search); return json(profileValue) }
    if (url.pathname === '/api/sim/state') return json({ current_run_id: 42 })
    if (url.pathname === '/api/sim/runs') return json({ items: [{ id: 42, label: 'Проверка клиента' }] })
    if (url.pathname.startsWith('/api/refs/')) return json(client360Refs[url.pathname.split('/').at(-1)!] ?? [])
    return json({})
  })
}
function mount(path = '/clients/17?run_id=42', source = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[source ? '/' : path]}><Routes>
    <Route path="/" element={<ClientProfileLink id={17} runId={42} />} />
    <Route path="/clients/:id" element={<Client360Page />} />
  </Routes></MemoryRouter></QueryClientProvider>)
  return qc
}

beforeEach(async () => {
  await i18n.changeLanguage('ru')
  useWs.setState({ sim: null })
  profileRequests = []
  vi.stubGlobal('fetch', fetchFixture())
})

describe('Client360', () => {
  it('shows real profile sections, failed operation/fault link and account closure', async () => {
    mount()
    expect(await screen.findByRole('heading', { name: 'Клиент 360 · Ирина Т.' })).toBeVisible()
    expect(screen.getByRole('meter', { name: 'Текущий риск ухода' })).toHaveAttribute('value', '78')
    const failed = screen.getByRole('row', { name: /Ошибка/ })
    expect(failed.querySelector('a[href="/trace/fault/9"]')).toBeInTheDocument()
    expect(within(failed).getByText('PROC-ERROR')).toBeVisible()
    expect(within(failed).getByText(/450,5/)).toBeVisible()
    expect(within(failed).getByText('20.10.2026 09:00')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Инцидент закрытия счёта · INC-000011' })).toHaveAttribute('href', '/incidents/11')
    expect(await screen.findByText('Бонусные баллы')).toBeVisible()
    expect(screen.getByText('Выполнен')).toBeVisible()
    expect(screen.getByText(profile.psychotype.communication_hint_ru)).toBeVisible()
    expect(screen.getByText('+7 900 ***-**-**')).toBeVisible()
    expect(screen.queryByText(/психотип/i)).not.toBeInTheDocument()
    expect(profileRequests).toEqual(['?run_id=42&ops_hours=72'])
  })

  it('uses the prefetched cache immediately without another profile request', async () => {
    const qc = mount('/', true)
    await waitFor(() => expect(profileRequests).toHaveLength(1))
    await waitFor(() => expect(screen.getByRole('link', { name: 'Клиент 360' })).toHaveAttribute('href', '/clients/17?run_id=42'))
    await waitFor(() => expect(qc.getQueryData(['client360', 17, '42', 72, null])).toBeDefined())
    fireEvent.click(screen.getByRole('link', { name: 'Клиент 360' }))
    expect(screen.getByRole('heading', { name: 'Клиент 360 · Ирина Т.' })).toBeVisible()
    expect(screen.queryByLabelText('Загружаем профиль клиента')).not.toBeInTheDocument()
    expect(profileRequests).toHaveLength(1)
  })

  it('keeps scopes/windows in separate cache keys and defaults to current', async () => {
    mount('/clients/17')
    await screen.findByRole('heading', { name: 'Клиент 360 · Ирина Т.' })
    expect(profileRequests).toEqual(['?run_id=current&ops_hours=72'])
    fireEvent.change(screen.getByRole('combobox', { name: 'История' }), { target: { value: 'all' } })
    await waitFor(() => expect(profileRequests.at(-1)).toBe('?run_id=all&ops_hours=72'))
    fireEvent.change(screen.getByRole('combobox', { name: 'Операции за' }), { target: { value: '24' } })
    await waitFor(() => expect(profileRequests.at(-1)).toBe('?run_id=all&ops_hours=24'))
    fireEvent.change(screen.getByRole('combobox', { name: 'История' }), { target: { value: 'current' } })
    await waitFor(() => expect(profileRequests.at(-1)).toBe('?run_id=current&ops_hours=24'))
  })

  it('localizes guidance/statuses and covers every generated client state', async () => {
    await i18n.changeLanguage('en')
    mount()
    expect(await screen.findByRole('heading', { name: 'Client 360 · Ирина Т.' })).toBeVisible()
    expect(screen.getByText(en.client360.hints.anxious)).toBeVisible()
    expect(screen.getByText('Failed')).toBeVisible()
    expect(await screen.findByText('Bonus points')).toBeVisible()
    expect(Object.keys(ru.client360).sort()).toEqual(Object.keys(en.client360).sort())
    for (const state of Object.values(ClientState)) expect(i18n.exists(`client360.states.${state}`)).toBe(true)
  })

  it('shows empty histories and a real zero care/risk instead of invented data', async () => {
    vi.stubGlobal('fetch', fetchFixture({ ...profile, is_active: true, churn_risk: 0, current_state: { state: 'calm', care_score: 0 }, products: [], operations: [], signals: [], incidents: [], gifts: [], state_history: [] }))
    mount()
    expect(await screen.findByText('В выбранном окне операций нет')).toBeVisible()
    expect(screen.getByRole('meter', { name: 'Текущий риск ухода' })).toHaveAttribute('value', '0')
    expect(screen.getByText(/^0\s*%$/)).toBeVisible()
    expect(screen.getByText('Подтверждённых или назначенных подарков нет')).toBeVisible()
    expect(screen.queryByRole('link', { name: /Инцидент закрытия счёта/ })).not.toBeInTheDocument()
  })

  it('preserves a valid custom API window and never fabricates a closure outside the selected run', async () => {
    vi.stubGlobal('fetch', fetchFixture({ ...profile, incidents: [] }))
    mount('/clients/17?run_id=42&ops_hours=48')
    expect(await screen.findByText('Инцидент закрытия счёта не найден в выбранной истории.')).toBeVisible()
    expect(screen.getByRole('combobox', { name: 'Операции за' })).toHaveValue('48')
    expect(profileRequests).toEqual(['?run_id=42&ops_hours=48'])
    expect(screen.queryByRole('link', { name: 'Инцидент закрытия счёта · INC-000011' })).not.toBeInTheDocument()
  })

  it('does not query invalid client ids', () => {
    mount('/clients/invalid')
    expect(screen.getByRole('heading', { name: 'Клиент или выбранный запуск не найден' })).toBeVisible()
    expect(profileRequests).toHaveLength(0)
  })

  it('shows a missing client/run response without a misleading profile', async () => {
    const normal = fetchFixture()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/360') ? json({ title: 'Не найдено', detail: 'server lookup detail' }, 404) : normal(input)))
    mount()
    expect(await screen.findByRole('heading', { name: 'Клиент или выбранный запуск не найден' })).toBeVisible()
    expect(screen.queryByText('server lookup detail')).not.toBeInTheDocument()
    expect(screen.queryByRole('meter')).not.toBeInTheDocument()
  })

  it('retries a failed API load explicitly', async () => {
    const normal = fetchFixture()
    let failed = false
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/360') && !failed) { failed = true; return json({ title: 'Сервис недоступен' }, 503) }
      return normal(input)
    }))
    mount()
    expect(await screen.findByRole('alert')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('heading', { name: 'Клиент 360 · Ирина Т.' })).toBeVisible()
  })
})
