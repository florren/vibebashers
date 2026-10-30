import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api } from '@/shared/api/client'
import { IncidentEconomics } from './IncidentEconomics'

vi.mock('@/shared/api/client', () => ({ api: vi.fn() }))
afterEach(cleanup)
it('показывает расчёт API, возврат и отрицательный чистый эффект', async () => {
  vi.mocked(api).mockResolvedValue({ formula_ru: '12 × 10 % × 50 % × 1052,53 = 631,52 ₽', potential_loss_rub: 631.52, prevented_loss_rub: 200, refund_amount_rub: 450, net_effect_rub: -250, retention_source: 'manual', rate_code: 'deposit', outcome_class: 'closed_in_sla' })
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><IncidentEconomics id={42} /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('12 × 10 % × 50 % × 1052,53 = 631,52 ₽')).toBeInTheDocument()
  expect(screen.getByText(/-250/)).toBeInTheDocument()
  expect(screen.getByText('Возврат клиенту')).toBeInTheDocument()
  expect(api).toHaveBeenCalledWith('/api/incidents/42/economics')
})
