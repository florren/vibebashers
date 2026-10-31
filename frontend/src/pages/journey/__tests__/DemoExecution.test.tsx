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
  expect(screen.queryByText(/Команды и сотрудники на паузе/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить профиль обработки' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/demo/execution', expect.objectContaining({ method: 'POST', body: JSON.stringify({ mode: 'simulation', team_outcome: 'on_time', emulate_humans: true, auto_advance: true }) })))
  qc.clear()
})
