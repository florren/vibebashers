import { useState } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api } from '@/shared/api/client'
import { DemoExecution, DEFAULT_JOURNEY_OPTIONS, type JourneyOptions } from '../DemoExecution'

vi.mock('@/shared/api/client', async original => ({ ...(await original<typeof import('@/shared/api/client')>()), api: vi.fn() }))
let qc: QueryClient
beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('ru')
  qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  vi.mocked(api).mockResolvedValue([
    { id: 'deposit_promo_rate', title_ru: 'Вклад', title_en: 'Deposit' },
    { id: 'qr_fee_public_review', title_ru: 'Комиссия', title_en: 'Fee' },
    { id: 'customer_journey', title_ru: 'Служебный Journey', title_en: 'Internal Journey' },
    { id: 'search_and_trace', title_ru: 'Служебный Trace', title_en: 'Internal Trace' },
  ] as never)
})
afterEach(() => { cleanup(); qc.clear() })
function mount(value = DEFAULT_JOURNEY_OPTIONS) {
  const onChange = vi.fn()
  function Controlled() {
    const [draft, setDraft] = useState(value)
    return <DemoExecution value={draft} onChange={next => { onChange(next); setDraft(next) }} />
  }
  render(<QueryClientProvider client={qc}><Controlled /></QueryClientProvider>)
  fireEvent.click(screen.getByText(String(i18n.t('journeyProfile.title'))))
  return onChange
}
function expectReadOnly() {
  expect(api).toHaveBeenCalled()
  expect(vi.mocked(api).mock.calls.every(([path, init]) => path === '/api/scenarios' && (!init?.method || init.method === 'GET'))).toBe(true)
}
it('keeps the default profile local and never starts or saves a global execution', async () => {
  const onChange = mount()
  await screen.findByRole('option', { name: 'Вклад' })
  expect(screen.getByLabelText(String(i18n.t('demoExecution.scenario')))).toHaveValue('deposit_promo_rate')
  expect(screen.getByLabelText('Работа команды')).toHaveValue('on_time')
  expect(screen.getByLabelText('Агент отвечает за сотрудников')).toBeChecked()
  expect(screen.getByLabelText('Ускорять ручные обращения до итогового ответа')).toBeChecked()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(onChange).not.toHaveBeenCalled()
  expect(api).toHaveBeenCalledTimes(1)
  expectReadOnly()
})
it.each(['on_time', 'late', 'no_work', 'failed'] as const)('updates only the local draft with outcome %s', async outcome => {
  const onChange = mount()
  await screen.findByRole('option', { name: 'Комиссия' })
  fireEvent.change(screen.getByLabelText(String(i18n.t('demoExecution.scenario'))), { target: { value: 'qr_fee_public_review' } })
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: outcome } })
  fireEvent.click(screen.getByLabelText('Агент отвечает за сотрудников'))
  fireEvent.click(screen.getByLabelText('Ускорять ручные обращения до итогового ответа'))
  expect(onChange).toHaveBeenLastCalledWith({ scenario_id: 'qr_fee_public_review', team_outcome: outcome, emulate_humans: false, auto_advance: false })
  expect(screen.getByLabelText('Работа команды')).toHaveValue(outcome)
  expectReadOnly()
})
it('does not offer recovery as a first-attempt outcome', async () => {
  mount()
  await screen.findByRole('option', { name: 'Вклад' })
  expect(screen.queryByRole('option', { name: i18n.t('demoExecution.outcomes.recovered') })).not.toBeInTheDocument()
  expectReadOnly()
})
it('preserves the local draft across a scenario-list refresh', async () => {
  mount()
  await screen.findByRole('option', { name: 'Вклад' })
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'failed' } })
  await act(async () => { await qc.invalidateQueries({ queryKey: ['demo-scenarios'] }) })
  expect(screen.getByLabelText('Работа команды')).toHaveValue('failed')
  expect(screen.getByLabelText('Агент отвечает за сотрудников')).toBeChecked()
  expectReadOnly()
})
it('supports explicit no-scenario null without changing other local options', async () => {
  const value: JourneyOptions = { ...DEFAULT_JOURNEY_OPTIONS, team_outcome: 'late', emulate_humans: false }
  const onChange = mount(value)
  await screen.findByRole('option', { name: 'Вклад' })
  fireEvent.change(screen.getByLabelText(String(i18n.t('demoExecution.scenario'))), { target: { value: '' } })
  expect(onChange).toHaveBeenLastCalledWith({ ...value, scenario_id: null })
  expect(screen.getByLabelText(String(i18n.t('demoExecution.scenario')))).toHaveValue('')
  expectReadOnly()
})
it.each(['ru', 'en'])('localizes and excludes internal scenarios in %s', async language => {
  await i18n.changeLanguage(language)
  mount()
  await screen.findByRole('option', { name: language === 'en' ? 'Deposit' : 'Вклад' })
  const values = screen.getAllByRole('option').map(option => (option as HTMLOptionElement).value)
  expect(values).not.toContain('customer_journey')
  expect(values).not.toContain('search_and_trace')
  expectReadOnly()
})
it('shows scenario-list errors without writes or discarding the controlled draft', async () => {
  vi.mocked(api).mockRejectedValue(new Error('Список недоступен'))
  mount({ ...DEFAULT_JOURNEY_OPTIONS, team_outcome: 'failed' })
  expect(await screen.findByText('Список недоступен')).toBeInTheDocument()
  expect(screen.getByLabelText('Работа команды')).toHaveValue('failed')
  expectReadOnly()
})
it('does not write even without an onChange callback', async () => {
  render(<QueryClientProvider client={qc}><DemoExecution /></QueryClientProvider>)
  fireEvent.click(screen.getByText(String(i18n.t('journeyProfile.title'))))
  await screen.findByRole('option', { name: 'Вклад' })
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'failed' } })
  expectReadOnly()
})
