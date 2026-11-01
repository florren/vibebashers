import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api } from '@/shared/api/client'
import { DemoExecution } from '../DemoExecution'

vi.mock('@/shared/api/client', async original => ({ ...(await original<typeof import('@/shared/api/client')>()), api: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
it('starts explicit employee simulation with selected outcome and stops it', async () => {
  let enabled = false
  vi.mocked(api).mockImplementation(async (path, init) => {
    if (path === '/api/scenarios') return [{ id: 'deposit_promo_rate', title_ru: 'Вклад', title_en: 'Deposit' }] as never
    if (init?.method === 'POST') enabled = true
    if (init?.method === 'DELETE') enabled = false
    return { subject_ref: "SIG-000002", run_id: 2, configuration: { enabled, mode: 'demo', status: enabled ? 'running' : 'stopped', team_outcome: 'failed' }, incidents: [] } as never
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const onStarted = vi.fn()
  render(<QueryClientProvider client={qc}><DemoExecution onStarted={onStarted} /></QueryClientProvider>)
  fireEvent.click(screen.getByText(/Эмуляция команд/))
  const start = await screen.findByRole('button', { name: 'Запустить отдельный сценарий' })
  await waitFor(() => expect(start).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'failed' } })
  fireEvent.click(start)
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/demo/execution', expect.objectContaining({ method: 'POST', body: JSON.stringify({ mode: 'demo', scenario_id: 'deposit_promo_rate', team_outcome: 'failed', emulate_humans: true, auto_advance: true }) })))
  await waitFor(() => expect(onStarted).toHaveBeenCalledWith('SIG-000002'))
  fireEvent.click(await screen.findByRole('button', { name: 'Остановить эмуляцию' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/demo/execution', { method: 'DELETE' }))
  qc.clear()
})

it('applies the shared employee profile while paused without creating a scenario', async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/api/scenarios') return [{ id: 'deposit_promo_rate', title_ru: 'Вклад' }] as never
    return { run_id: 4, configuration: { mode: 'simulation', enabled: true, status: 'paused', team_outcome: 'on_time' }, incidents: [] } as never
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const onStarted = vi.fn()
  render(<QueryClientProvider client={qc}><DemoExecution onStarted={onStarted} /></QueryClientProvider>)
  fireEvent.click(screen.getByText(/Эмуляция команд/))
  await screen.findByText(/Команды и сотрудники на паузе/)
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'late' } })
  fireEvent.click(screen.getByLabelText('Агент отвечает за сотрудников'))
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить профиль обработки' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/demo/execution', expect.objectContaining({ method: 'POST', body: JSON.stringify({ mode: 'simulation', team_outcome: 'late', emulate_humans: false, auto_advance: false }) })))
  expect(onStarted).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Запустить отдельный сценарий' })).toBeEnabled()
  qc.clear()
})

it('loads and saves the fast manual profile without starting a scenario', async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/api/scenarios') return [] as never
    return { run_id: 4, configuration: { mode: 'simulation', enabled: true, status: 'paused', team_outcome: 'on_time', auto_advance: true, emulate_humans: true }, incidents: [] } as never
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}><DemoExecution /></QueryClientProvider>)
  fireEvent.click(screen.getByText(/Эмуляция команд/))
  await waitFor(() => expect(screen.getByLabelText('Ускорять ручные обращения до итогового ответа')).toBeChecked())
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить профиль обработки' })).toBeEnabled())
  expect(screen.queryByText(/Команды и сотрудники на паузе/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить профиль обработки' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/demo/execution', expect.objectContaining({ method: 'POST', body: JSON.stringify({ mode: 'simulation', team_outcome: 'on_time', emulate_humans: true, auto_advance: true }) })))
  qc.clear()
})

it('keeps a selected outcome as a draft until the profile is saved and then follows saved state', async () => {
  let applied = 'on_time'
  const state = () => ({ run_id: 4, configuration: { mode: 'simulation', enabled: true, status: 'paused', team_outcome: applied, auto_advance: true, emulate_humans: true }, incidents: [] })
  vi.mocked(api).mockImplementation(async (path, init) => {
    if (path === '/api/scenarios') return [] as never
    if (init?.method === 'POST') applied = JSON.parse(String(init.body)).team_outcome
    return state() as never
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}><DemoExecution /></QueryClientProvider>)
  fireEvent.click(screen.getByText(/Эмуляция команд/))
  await screen.findByText(/Сохранённый профиль ручных обращений/)
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'failed' } })
  expect(screen.getByText(/Выбранные параметры ещё не применены/)).toBeInTheDocument()
  expect(screen.getByText(/Сохранённый профиль ручных обращений/)).toHaveTextContent('Успех в срок')
  expect(api).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: 'POST' }))
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить профиль обработки' }))
  await waitFor(() => expect(screen.queryByText(/Выбранные параметры ещё не применены/)).not.toBeInTheDocument())
  expect(screen.getByText(/Сохранённый профиль ручных обращений/)).toHaveTextContent('Попытка не устранила проблему')
  expect(screen.getByLabelText('Работа команды')).toHaveValue('failed')
  applied = 'on_time'
  qc.setQueryData(['demo-execution'], state())
  await waitFor(() => expect(screen.getByLabelText('Работа команды')).toHaveValue('on_time'))
  qc.clear()
})

it('does not mark a draft as applied when saving fails', async () => {
  vi.mocked(api).mockImplementation(async (path, init) => {
    if (path === '/api/scenarios') return [] as never
    if (init?.method === 'POST') throw new Error('Сохранение недоступно')
    return { run_id: 4, configuration: { mode: 'simulation', enabled: true, status: 'paused', team_outcome: 'on_time', auto_advance: true, emulate_humans: true }, incidents: [] } as never
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}><DemoExecution /></QueryClientProvider>)
  fireEvent.click(screen.getByText(/Эмуляция команд/))
  await screen.findByText(/Сохранённый профиль ручных обращений/)
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'failed' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить профиль обработки' }))
  await screen.findByText(/Сохранение недоступно/)
  expect(screen.getByText(/Выбранные параметры ещё не применены/)).toBeInTheDocument()
  expect(screen.getByText(/Сохранённый профиль ручных обращений/)).toHaveTextContent('Успех в срок')
  qc.clear()
})

it('resumes only the selected escalated incident without changing the saved profile', async () => {
  let recoverable = true
  vi.mocked(api).mockImplementation(async (path, init) => {
    if (path === '/api/scenarios') return [] as never
    if (path === '/api/demo/incidents/153/recover' && init?.method === 'POST') recoverable = false
    return { run_id: 2, configuration: { mode: 'simulation', enabled: true, status: 'paused', team_outcome: 'failed', auto_advance: true }, incidents: [{ id: 153, public_id: 'INC-000153', status: 'escalated', can_recover: recoverable }] } as never
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}><DemoExecution /></QueryClientProvider>)
  fireEvent.click(screen.getByText(/Эмуляция команд/))
  fireEvent.click(await screen.findByRole('button', { name: 'Продолжить INC-000153 после эскалации' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/demo/incidents/153/recover', { method: 'POST' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: /Продолжить INC-000153/ })).not.toBeInTheDocument())
  expect(api).not.toHaveBeenCalledWith('/api/demo/execution', expect.objectContaining({ method: 'POST' }))
  qc.clear()
})
