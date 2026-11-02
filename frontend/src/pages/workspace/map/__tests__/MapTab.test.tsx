import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api } from '@/shared/api/client'
import { useViewPreset } from '@/shared/layout/preset'
import { MapTab } from '../../MapTab'
import { analytics, closedBranch, detail } from './fixtures'
vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
vi.mock('@/pages/csi/Chart', () => ({ CsiChart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }))
let client: QueryClient
beforeEach(async () => {
  await i18n.changeLanguage('ru'); localStorage.clear(); useViewPreset.setState({ role: 'cx_lead' })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.spyOn(SVGSVGElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, top: 0, left: 0, right: 960, bottom: 540, width: 960, height: 540, toJSON: () => ({}) })
  vi.mocked(api).mockReset().mockImplementation(async path => {
    if (path === '/api/map/heat') return [{ region_code: '77', name_ru: 'Москва', lat: 55.75, lon: 37.62, signals: 0, critical: 0, incidents_open: 0, churn_risk_avg: 0, value: 0, intensity: 0 }]
    if (path === '/api/map/zones') return { items: [], no_geo_count: 0, thresholds: { yellow: .25, red: .5, critical_red: 3 } }
    if (path === '/api/branches') return { items: [closedBranch], next_cursor: null, scope: analytics.scope, directory: detail.directory }
    if (path.startsWith('/api/branches/VSP-')) return detail
    if (path === '/api/branches/analytics') return analytics
    if (path === '/api/cabinet/overview') return { product_lines: [{ code: 'deposits', name_ru: 'Вклады', name_en: 'Deposits' }] }
    if (path === '/api/refs/regions') return [{ code: '77', name_ru: 'Москва', name_en: 'Moscow' }]
    throw new Error('Unexpected read: ' + path)
  })
})
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks() })
const show = (route = '/?tab=map') => render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}><MapTab /></MemoryRouter></QueryClientProvider>)
it('defaults to current, fetches branch data only after one click and places branch shapes below signals', async () => {
  const { container } = show()
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/map/heat', expect.objectContaining({ query: expect.objectContaining({ run_id: 'current' }) })))
  expect(vi.mocked(api).mock.calls.some(([path]) => path.startsWith('/api/branches'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'ВСП' }))
  await screen.findByText('закрыто · 2 сигнала')
  const branch = container.querySelector('[data-testid="branch-layer"]')!, signals = container.querySelector('[data-testid="signal-layer"]')!
  expect(branch.compareDocumentPosition(signals) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByText('ВСП vs Сигналы')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'ВСП' }))
  expect(container.querySelector('[data-testid="branch-layer"]')).toBeNull()
})
it('explicit blank run never reaches any operational HTTP request as omitted/all', async () => {
  show('/?tab=map&run_id=')
  await screen.findAllByText(i18n.t('common.emptyRunScope'))
  expect(vi.mocked(api).mock.calls.some(([path]) => path.startsWith('/api/map'))).toBe(false)
})
it('manager directory and details use the same explicit binding and scope', async () => {
  localStorage.setItem('cx.ui.productLine', 'deposits'); useViewPreset.setState({ role: 'product_manager' })
  show('/?tab=map&run_id=19')
  fireEvent.click(screen.getByRole('button', { name: 'ВСП' }))
  await screen.findByText('закрыто · 2 сигнала')
  const calls = vi.mocked(api).mock.calls.filter(([path]) => path.startsWith('/api/branches'))
  expect(calls.length).toBeGreaterThan(1)
  for (const [, init] of calls) expect(init?.headers).toEqual({ 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'deposits' })
  await act(async () => useViewPreset.setState({ role: 'cx_lead' }))
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path, init]) => path === '/api/branches' && (init?.headers as Record<string,string>)['X-Cx-Role'] === 'cx_lead')).toBe(true))
})
