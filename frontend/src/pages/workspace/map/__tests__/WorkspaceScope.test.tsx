import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkspacePage } from '../../WorkspacePage'
const mounted = vi.hoisted(() => ({ legacy: vi.fn(), scoped: vi.fn() }))
vi.mock('@/widgets/KpiStrip', () => ({ KpiStrip: () => { mounted.legacy(); return <div>legacy KPI</div> } }))
vi.mock('@/shared/layout/ScopedRunBoundary', () => ({ ScopedRunBoundary: ({ requested }: { requested: string }) => { mounted.scoped(requested); return <div>scoped {requested}</div> } }))
function Location() { return <span>{useLocation().search}</span> }
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('fixes Map current in URL before mounting legacy KPI or scoped queries', async () => {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/workspace?tab=map&map_mode=zones']}><WorkspacePage /><Location /></MemoryRouter></QueryClientProvider>)
  await screen.findByText('scoped current')
  expect(mounted.legacy).not.toHaveBeenCalled()
  expect(mounted.scoped).toHaveBeenCalledWith('current')
  expect(screen.getByText('?tab=map&map_mode=zones&run_id=current')).toBeInTheDocument()
})
it.each(['all', '', 'bad'])('preserves explicit scope %s for server validation without mounting legacy KPI', async scope => {
  render(<MemoryRouter initialEntries={['/workspace?tab=map&run_id=' + scope]}><WorkspacePage /></MemoryRouter>)
  expect(mounted.scoped).toHaveBeenCalledWith(scope)
  expect(mounted.legacy).not.toHaveBeenCalled()
})
