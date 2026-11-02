import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api } from '@/shared/api/client'
import { useUiTheme } from '@/shared/theming/store'
import { useViewPreset } from '@/shared/layout/preset'
import { useDeviceMode } from '@/shared/layout/device-store'
import { useWs } from '@/shared/ws/client'
import { WorkspaceEntry } from '@/shared/layout/LayoutRoutes'
import { Shell } from '../Shell'
import { navigationFor, itemActive } from '../Sidebar/navigation'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
const clients: QueryClient[] = []
function Location() { const { pathname, search } = useLocation(); return <output data-testid="location">{pathname}{search}</output> }
function show(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client)
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Location /><Routes><Route element={<Shell />}>
    <Route index element={<WorkspaceEntry />} /><Route path="workspace" element={<><input aria-label="Draft" /><p>WORKSPACE</p></>} /><Route path="overview" element={<p>OVERVIEW</p>} />
    <Route path="engine" element={<p>ENGINE</p>} /><Route path="trace" element={<p>TRACE</p>} /><Route path="*" element={<p>DETAIL</p>} />
  </Route></Routes></MemoryRouter></QueryClientProvider>)
}
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear()
  useUiTheme.setState({ layout: 'legacy', attention: null, theme_pack: 'brand' }); useViewPreset.setState({ role: 'cx_lead', demonstrator: false }); useDeviceMode.setState({ mode: 'auto' })
  useWs.setState({ sim: null, status: 'closed', events: [] })
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/api/sim/state') return { current_run_id: 7, current_run_status: 'paused', sim_time: '2026-11-09T06:00:00Z', phase: 'morning' }
    if (path === '/api/demo/status') return { llm_mode: 'mock', stt_mode: 'transcript', current_run: { id: 7, label: 'Mock local run' } }
    if (path === '/api/health') return { status: 'ok', db: true, tgbot: 'disabled', llm: { mock: 'ok' } }
    if (path.startsWith('/api/refs')) return []
    return { items: [] }
  })
})
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals() })
it('legacy stays at the old index and retains its header navigation without sidebar', async () => {
  show('/?tab=signals&scope=current')
  await screen.findByRole('tab', { name: 'Сигналы' })
  expect(screen.getByTestId('location')).toHaveTextContent('/?tab=signals&scope=current')
  expect(screen.queryByRole('navigation', { name: 'Навигация' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Рабочее место' })).toBeVisible()
})
it('v2 redirects only the index, preserving all legacy tab query arguments', async () => {
  useUiTheme.setState({ layout: 'v2' }); show('/?tab=hitl&q=SIG-000001&scope=all')
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/workspace?tab=hitl&q=SIG-000001&scope=all'))
  expect(screen.getByRole('navigation', { name: 'Навигация' })).toBeVisible()
  expect(screen.getByRole('region', { name: 'Состояние системы' })).toBeVisible()
  expect(await screen.findByText('Агент · режим LLM:')).toBeVisible()
  expect(screen.getByText('#7 · Mock local run')).toBeVisible()
})
it('v2 bare index opens overview; direct engine and trace routes remain available', async () => {
  useUiTheme.setState({ layout: 'v2' }); show('/')
  await screen.findByText('OVERVIEW')
  fireEvent.click(screen.getByRole('link', { name: 'Под капотом' })); expect(await screen.findByText('ENGINE')).toBeVisible()
  fireEvent.click(screen.getByRole('link', { name: 'Поиск и след' })); expect(await screen.findByText('TRACE')).toBeVisible()
})
it('1–6 navigate operations; typing, modifiers and open dialogs cannot trigger navigation', async () => {
  useUiTheme.setState({ layout: 'v2' }); show('/workspace?tab=signals')
  const draft = screen.getByRole('textbox', { name: 'Draft' })
  fireEvent.keyDown(draft, { key: '3' }); expect(screen.getByTestId('location')).toHaveTextContent('tab=signals')
  fireEvent.keyDown(window, { key: '3', ctrlKey: true }); expect(screen.getByTestId('location')).toHaveTextContent('tab=signals')
  fireEvent.keyDown(window, { key: '6' }); await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('tab=map&map_mode=zones'))
  fireEvent.keyDown(window, { key: '?' }); expect(screen.getByRole('dialog', { name: 'Горячие клавиши' })).toBeVisible()
  fireEvent.keyDown(window, { key: '1' }); expect(screen.getByTestId('location')).toHaveTextContent('tab=map&map_mode=zones')
  fireEvent.keyDown(document, { key: 'Escape' }); await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  fireEvent.keyDown(window, { key: '1' }); expect(await screen.findByText('OVERVIEW')).toBeVisible()
})
it('role preset visibility changes navigation and attention without pretending to enforce access', async () => {
  useUiTheme.setState({ layout: 'v2' }); show('/workspace')
  fireEvent.change(screen.getByRole('combobox', { name: 'Пресет роли' }), { target: { value: 'product_manager' } })
  expect(screen.queryByRole('link', { name: 'Комплаенс' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Кабинет продукта' })).toBeVisible()
  expect(document.documentElement.dataset.attention).toBe('calm')
  fireEvent.click(screen.getByRole('checkbox', { name: 'Контекст демонстратора' }))
  expect(screen.getByRole('link', { name: 'Комплаенс' })).toBeVisible()
  expect(document.documentElement.dataset.attention).toBe('control_room')
  act(() => useUiTheme.getState().setAttention('calm'))
  expect(document.documentElement.dataset.attention).toBe('calm')
})
it('below 1024 sidebar opens as a keyboard accessible off-canvas panel', async () => {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query === '(max-width: 1023px)', addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  useUiTheme.setState({ layout: 'v2' }); show('/workspace')
  expect(screen.queryByRole('navigation', { name: 'Навигация' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Открыть навигацию' }))
  expect(screen.getByRole('dialog', { name: 'Навигация' })).toBeVisible()
  fireEvent.click(screen.getByRole('link', { name: 'Обзор' }))
  expect(await screen.findByText('OVERVIEW')).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
it('query-aware active links distinguish map from zones and preserve independent details', () => {
  const items = navigationFor('cx_lead')[0]!.items
  expect(items).toHaveLength(6)
  expect(itemActive(items[4]!, '/workspace', '?tab=map&map_mode=zones')).toBe(false)
  expect(itemActive(items[5]!, '/workspace', '?tab=map&map_mode=zones')).toBe(true)
  expect(itemActive(items[1]!, '/workspace', '?tab=signals&q=SIG-1')).toBe(true)
  expect(itemActive(items[1]!, '/incidents/5', '?tab=signals')).toBe(false)
})
