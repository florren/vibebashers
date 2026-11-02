import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api } from '@/shared/api/client'
import { CabinetCalculator } from '../CabinetCalculator'
import { overview } from './fixtures'

vi.mock('@/shared/api/hooks', () => ({ useEconomicsSettings: () => ({ data: { detractor_share: .1, no_return_share: .5, rates: [{ code: 'deposit', name_ru: 'Вклады', name_en: 'Deposits', rate_rub: 961 }, { code: 'credit_card', name_ru: 'Кредитные карты', name_en: 'Credit cards', rate_rub: 305 }, { code: 'id_service', name_ru: 'ID-сервис', name_en: 'ID service', rate_rub: .405 }] }, dataUpdatedAt: 1, isPending: false, isError: false }) }))
vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
let client: QueryClient
beforeEach(async () => {
  await i18n.changeLanguage('ru')
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(api).mockReset().mockImplementation(async (_path, options) => {
    const affected = options?.query?.affected
    return { rate_code: options?.query?.rate_code, affected_count: affected, potential_loss_rub: affected === 0 ? 0 : affected === 20 ? 1200.01 : 123.45, rate_rub: 961, premium_addon_rub: 0, detractor_share: .1, no_return_share: .5 }
  })
})
afterEach(() => { cleanup(); client.clear() })
function show(region: typeof overview.regions[number] | undefined) {
  const view = (r: typeof region, line = overview.product_lines[0]) => <QueryClientProvider client={client}><CabinetCalculator line={line} region={r} scopeKey="run1/deposits/month" /></QueryClientProvider>
  return { ...render(view(region)), view }
}
it('uses the server amount, not a local copy, and invalid input removes the old result', async () => {
  const { container, rerender, view } = show(undefined)
  expect(container.querySelector('[aria-live]')).toHaveTextContent('—')
  expect(api).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Ставка dCLTV')).toHaveValue('deposit')
  rerender(view(overview.regions[0]))
  await waitFor(() => expect(container.querySelector('[aria-live]')).toHaveTextContent('−123,45'))
  expect(screen.getByLabelText('Пострадавшие')).toHaveValue(2)
  expect(api).toHaveBeenCalledWith('/api/metrics/economics/preview', expect.objectContaining({ query: { affected: 2, rate_code: 'deposit', detractor_share: .1, no_return_share: .5 }, signal: expect.any(AbortSignal) }))
  fireEvent.change(screen.getByLabelText('Пострадавшие'), { target: { value: '20' } })
  await waitFor(() => expect(container.querySelector('[aria-live]')).toHaveTextContent(/−1\s200,01/))
  fireEvent.change(screen.getByLabelText('Пострадавшие'), { target: { value: '-1' } })
  expect(container.querySelector('[aria-live]')).toHaveTextContent('—')
})
it('reselects the actual catalog rate on direction change', () => {
  const { rerender, view } = show(undefined)
  rerender(view(undefined, { ...overview.product_lines[0]!, code: 'credit_cards', rate_code: 'credit_card' }))
  expect(screen.getByLabelText('Ставка dCLTV')).toHaveValue('credit_card')
})
it('keeps anonymous coverage unknown without a request but sends a genuinely empty cohort as zero', async () => {
  const { container, rerender, view } = show({ ...overview.regions[0]!, affected_clients: null, identified_clients: 1, identified_signals: 1 })
  expect(screen.getByLabelText('Пострадавшие')).toHaveValue(null)
  expect(container.querySelector('[aria-live]')).toHaveTextContent('—')
  expect(screen.getByText(/Неполный охват клиентов/)).toHaveTextContent('1 из 2 сигналов')
  expect(api).not.toHaveBeenCalled()
  rerender(view({ ...overview.regions[0]!, signals: 0, affected_clients: 0, identified_clients: 0, identified_signals: 0 }))
  await waitFor(() => expect(container.querySelector('[aria-live]')).toHaveTextContent(/^0\s₽$/))
  expect(api).toHaveBeenCalledWith('/api/metrics/economics/preview', expect.objectContaining({ query: expect.objectContaining({ affected: 0 }) }))
})
it('surfaces server rejection and never substitutes a fabricated amount', async () => {
  vi.mocked(api).mockRejectedValue(new Error('Explicit rate rejected'))
  const { container } = show(overview.regions[0])
  await screen.findByText(i18n.t('care.errors.unknown'))
  expect(container.querySelector('[aria-live]')).toHaveTextContent('—')
})

it('hides a cached result when a same-input server refetch fails', async () => {
  const { container } = show(overview.regions[0])
  await waitFor(() => expect(container.querySelector('[aria-live]')).toHaveTextContent('−123,45'))
  vi.mocked(api).mockRejectedValue(new Error('Server temporarily unavailable'))
  await client.invalidateQueries({ queryKey: ['economics-preview'] })
  await screen.findByText(i18n.t('care.errors.unknown'))
  expect(container.querySelector('[aria-live]')).toHaveTextContent('—')
})

it('shows existing three-decimal catalog rates without rounding their inputs to cents', () => {
  show(undefined)
  expect(screen.getByRole('option', { name: /ID-сервис/ })).toHaveTextContent(/0,405/)
})
