import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api } from '@/shared/api/client'
import { useWs } from '@/shared/ws/client'
import { FinancePage } from './FinancePage'

vi.mock('echarts', () => ({ init: () => ({ setOption: vi.fn(), dispose: vi.fn(), resize: vi.fn() }) }))
vi.mock('@/shared/api/client', async (original) => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
vi.mock('@/shared/api/hooks', () => ({
  useSimRuns: () => ({ data: { items: [{ id: 7, label: 'Run 7', status: 'running' }] } }),
  useSimState: () => ({ data: { current_run_id: 7 }, isSuccess: true }),
}))
const total = {
  run_id: 7, period: 'live', total_saved_rub: 366.77, refund_rub: 450, net_effect_rub: -83.23,
  incidents_resolved: 1, top_product_saved: 'Карта', missing_calculations: 0, stale_calculations: 0,
  scenario_saved_rub: 458.46, scenario_net_rub: 8.46, scenario_fine_rub: 0, scenario_with_fine_net_rub: 8.46,
  fine_cases: 0, next_offset: null,
  series: [{ time: '2026-10-29T10:00Z', saved_rub: 366.77, net_rub: -83.23 }],
  items: [{ incident_id: 1, public_id: 'INC-000001', incident_type: 'fee_refund', product_name: 'Карта', client_public_id: 'CL-000001', client_ltv_rub: 1000, status: 'resolved', resolved_sim: '2026-10-29T10:00Z', saved_rub: 366.77, refund_rub: 450, net_rub: -83.23 }],
}
const detail = { ...total.items[0], calculation: { formula_ru: '1 × 100 % × 100 % × 458,46 = 458,46 ₽', potential_loss_rub: 458.46, retention_factor: 0.8, retention_source: 'manual' }, scenario_base_rub: 458.46, fine_eligible: false, scenario_saved_rub: 458.46, scenario_net_rub: 8.46, scenario_fine_rub: 0, scenario_with_fine_net_rub: 8.46 }

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  useWs.setState({ sim: null, status: 'open' })
  vi.mocked(api).mockImplementation(async (path) => path.includes('/incident/') ? detail : total as never)
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })
function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><FinancePage /></MemoryRouter></QueryClientProvider>)
}

it('сравнивает три варианта, показывает отрицательный net и открывает формулу', async () => {
  mount()
  await screen.findByText('1 · Действующая модель dCLTV')
  expect(screen.getByText('решён')).toBeInTheDocument()
  expect(screen.getByText('2 · Вероятность оттока')).toBeInTheDocument()
  expect(screen.getByText('3 · Вероятность + условный штраф')).toBeInTheDocument()
  expect(screen.getAllByText(/-83,23\s₽/).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: 'INC-000001' }))
  const modal = await screen.findByRole('dialog')
  await within(modal).findByText('1 × 100 % × 100 % × 458,46 = 458,46 ₽')
  expect(within(modal).getByRole('link', { name: 'Открыть инцидент' })).toHaveAttribute('href', '/incidents/1')
})

it('передаёт период и сценарные допущения серверу', async () => {
  mount()
  await screen.findByText('1 · Действующая модель dCLTV')
  fireEvent.click(screen.getByRole('button', { name: 'Неделя' }))
  fireEvent.change(await screen.findByLabelText(/Вероятность оттока/), { target: { value: '50' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/v1/finance/impact/total', expect.objectContaining({ query: expect.objectContaining({ period: 'week', probability_percent: 50, run_id: 7 }) })))
})

it('не показывает предыдущие суммы при смене запуска', async () => {
  vi.mocked(api).mockImplementation(async (_path, options) => options?.query?.run_id === 8 ? { ...total, run_id: 8, items: [], series: [], incidents_resolved: 0, total_saved_rub: 0 } as never : total as never)
  mount()
  await screen.findByRole('button', { name: 'INC-000001' })
  act(() => useWs.setState({ sim: { current_run_id: 8 } as never }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'INC-000001' })).not.toBeInTheDocument())
  expect(await screen.findAllByText('В выбранном периоде нет решённых кейсов.')).toHaveLength(2)
})

it('показывает неполноту расчётов и требует корректные пользовательские даты', async () => {
  vi.mocked(api).mockResolvedValue({ ...total, missing_calculations: 2, stale_calculations: 3 } as never)
  mount()
  expect(await screen.findByRole('status')).toHaveTextContent('отсутствует для 2 кейсов, устарел для 3')
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать даты' }))
  expect(screen.getByRole('status')).toHaveTextContent('Укажите начало и конец периода')
  expect(screen.queryByText('1 · Действующая модель dCLTV')).not.toBeInTheDocument()
})
