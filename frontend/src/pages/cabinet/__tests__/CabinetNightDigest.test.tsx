import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api } from '@/shared/api/client'
import { CabinetNightDigest } from '../CabinetNightDigest'
import { signal } from './fixtures'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
let client: QueryClient
beforeEach(async () => {
  await i18n.changeLanguage('ru'); client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  document.documentElement.dataset.circadian = 'true'; document.documentElement.dataset.phase = 'night'
  vi.mocked(api).mockReset().mockResolvedValue({ items: [signal, { ...signal, id: 8, public_id: 'SIG-000008', criticality: 'low' }], total: 2, next_offset: null })
})
afterEach(() => { cleanup(); client.clear(); delete document.documentElement.dataset.circadian; delete document.documentElement.dataset.phase })
function show() {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/cabinet/deposits?run_id=17&period=month']}><CabinetNightDigest scope={{ product_line: 'deposits', run_id: '17', period: 'month' }} headers={{ 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'deposits' }} /></MemoryRouter></QueryClientProvider>)
}
it('uses only the explicit cabinet scope for night and keeps the seven-block container independent', async () => {
  const { container } = show()
  await screen.findByText('SIG-000007')
  expect(screen.queryByText('SIG-000008')).not.toBeInTheDocument()
  expect(api).toHaveBeenCalledWith('/api/cabinet/signals', expect.objectContaining({ query: { product_line: 'deposits', run_id: '17', period: 'month', sort: 'level', direction: 'desc', limit: 10 }, headers: { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'deposits' } }))
  expect(vi.mocked(api).mock.calls.every(([path]) => path === '/api/cabinet/signals')).toBe(true)
  expect(screen.getByText('SIG-000007')).toHaveAttribute('href', '/trace/signal/SIG-000007?run_id=17')
  expect(screen.getByTestId('night-decoration')).toHaveAttribute('aria-hidden', 'true')
  expect(container.querySelector('[data-block]')).toBeNull()
  act(() => { document.documentElement.dataset.phase = 'morning' })
  await waitFor(() => expect(screen.queryByTestId('cabinet-night-digest')).not.toBeInTheDocument())
})
it('does not fetch any digest until circadian night is actually active', () => {
  document.documentElement.dataset.circadian = 'false'
  show()
  expect(api).not.toHaveBeenCalled()
  expect(screen.queryByTestId('night-decoration')).not.toBeInTheDocument()
})
