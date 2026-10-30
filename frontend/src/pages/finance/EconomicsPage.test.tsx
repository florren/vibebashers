import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api } from '@/shared/api/client'
import { EconomicsPage } from './EconomicsPage'

vi.mock('@/shared/api/client', () => ({ api: vi.fn() }))
vi.mock('@/shared/api/hooks', () => ({ useEconomicsSettings: () => ({ data: undefined, dataUpdatedAt: 1 }), useRefs: () => ({ data: [{ code: 'deposit', name_ru: 'Вклад' }, { code: 'vip', name_ru: 'VIP' }] }) }))
vi.mock('@/pages/setup/SetupPage', () => ({ StepEconomics: () => <div>Ставки</div> }))
vi.mock('@/pages/workspace/DashboardTab', () => ({ DashboardTab: () => <div>Факт</div> }))
afterEach(cleanup)
it('показывает результат backend и пересчитывает изменение числа клиентов', async () => {
  vi.mocked(api).mockResolvedValue({ potential_loss_rub: 631.52, formula_ru: '12 × 10 % × 50 % × 1052,53 = 631,52 ₽' })
  render(<QueryClientProvider client={new QueryClient()}><EconomicsPage /></QueryClientProvider>)
  expect(await screen.findByText(/12 × 10 %/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Пострадавшие'), { target: { value: '24' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/metrics/economics/preview', expect.objectContaining({ query: expect.objectContaining({ affected: 24 }) })))
})
