import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api } from '@/shared/api/client'
import { KpiStrip } from './KpiStrip'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
vi.mock('@/shared/layout/device-store', () => ({ useMobileLayout: () => false }))
afterEach(cleanup)

it('показывает всю очередь HITL текущего запуска вместо первой страницы из 50 записей', async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/api/hitl/queue') return { items: Array.from({ length: 50 }, (_, id) => ({ id })), total: 128, next_cursor: '50' } as never
    return {} as never
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><KpiStrip runId={7} /></QueryClientProvider>)
  try {
    const label = screen.getByText('Ждут человека')
    expect(await within(label.parentElement!).findByText('128')).toBeInTheDocument()
    expect(api).toHaveBeenCalledWith('/api/hitl/queue', { query: { run_id: 7 } })
  } finally {
    view.unmount()
    client.clear()
  }
})
