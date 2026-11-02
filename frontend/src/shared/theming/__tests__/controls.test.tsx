import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api } from '@/shared/api/client'
import { CircadianControls } from '../CircadianControls'
import { NightDigest } from '../NightDigest'
import { useUiTheme } from '../store'
import { useWs } from '@/shared/ws/client'
import { DEFAULT_CIRCADIAN } from '../circadian'

vi.mock('@/shared/api/client', () => ({ api: vi.fn() }))
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  useWs.setState({ sim: null, events: [], seq: 0 })
  document.documentElement.dataset.circadian = 'true'
  document.documentElement.dataset.phase = 'night'
  useUiTheme.setState({ mode: 'circadian', circadian: { ...DEFAULT_CIRCADIAN } })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('requests geolocation only on explicit click; saves local coordinates without API calls', () => {
  const getCurrentPosition = vi.fn((success) => success({ coords: { latitude: 40, longitude: 30 } }))
  vi.stubGlobal('navigator', { geolocation: { getCurrentPosition } })
  render(<CircadianControls />)
  expect(getCurrentPosition).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText(/Разрешить геолокацию/))
  expect(getCurrentPosition).toHaveBeenCalledTimes(1)
  expect(JSON.parse(localStorage.getItem('cx.ui.location')!)).toEqual({ latitude: 40, longitude: 30 })
  expect(api).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Использовать Москву'))
  expect(localStorage.getItem('cx.ui.location')).toBeNull()
})
it('shows permission denial and preserves previous location', () => {
  localStorage.setItem('cx.ui.location', '{"latitude":50,"longitude":20}')
  vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: (_ok: unknown, error: () => void) => error() } })
  render(<CircadianControls />)
  fireEvent.click(screen.getByText(/Разрешить геолокацию/))
  expect(screen.getByRole('alert')).toHaveTextContent('Геолокация недоступна')
  expect(localStorage.getItem('cx.ui.location')).toBe('{"latitude":50,"longitude":20}')
})
it('manual fixed phase wins until explicitly changed and persists', () => {
  render(<CircadianControls />)
  fireEvent.change(screen.getByLabelText('Источник времени'), { target: { value: 'fixed' } })
  fireEvent.change(screen.getByLabelText('Фаза'), { target: { value: 'night' } })
  expect(useUiTheme.getState().circadian).toEqual({ source: 'fixed', fixed_phase: 'night' })
  useUiTheme.getState().setSimTime('2026-06-21T12:00:00+03:00')
  expect(document.documentElement.dataset.phase).toBe('night')
  expect(JSON.parse(localStorage.getItem('cx.ui.circadian')!)).toEqual({ source: 'fixed', fixed_phase: 'night' })
})
const mountDigest = (route = '/signals') => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return { ...render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}><NightDigest /></MemoryRouter></QueryClientProvider>), client }
}
it('loads current high-priority signals only, keeps raw text/PII out of the digest', async () => {
  vi.mocked(api).mockResolvedValue({ items: [{ id: 1, public_id: 'SIG-000001', text: 'PRIVATE RAW TEXT' }] })
  mountDigest()
  await screen.findByText('SIG-000001')
  expect(api).toHaveBeenCalledWith('/api/signals', { query: { run_id: 'current', criticality: 'high', limit: 10 } })
  expect(screen.queryByText('PRIVATE RAW TEXT')).not.toBeInTheDocument()
  expect(screen.getByTestId('night-decoration')).toHaveAttribute('aria-hidden', 'true')
  await act(async () => { document.documentElement.dataset.phase = 'noon' })
  await waitFor(() => expect(screen.queryByTestId('night-digest')).not.toBeInTheDocument())
})
for (const route of ['/manager', '/compliance', '/compliance/session/42']) it(`preserves live alerts at ${route} without querying digest`, () => {
  mountDigest(route)
  expect(screen.queryByTestId('night-digest')).not.toBeInTheDocument()
  expect(api).not.toHaveBeenCalled()
})
it('does not query or decorate manual dark mode', () => {
  document.documentElement.dataset.circadian = 'false'
  mountDigest()
  expect(screen.queryByTestId('night-decoration')).not.toBeInTheDocument()
  expect(api).not.toHaveBeenCalled()
})

it('drops stale current-run results after a real runs event and caches only public IDs', async () => {
  let finishOld!: (value: unknown) => void
  vi.mocked(api).mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve })).mockResolvedValue({ items: [{ id: 2, public_id: 'SIG-000002', text: 'PRIVATE RAW TEXT' }] })
  const { client } = mountDigest()
  await waitFor(() => expect(api).toHaveBeenCalledTimes(1))
  await act(async () => { useWs.getState().push({ topic: 'runs', type: 'started', ts: '2026-11-09T06:00:00Z', data: {} }) })
  await screen.findByText('SIG-000002')
  await act(async () => { finishOld({ items: [{ id: 1, public_id: 'SIG-000001' }] }) })
  expect(screen.queryByText('SIG-000001')).not.toBeInTheDocument()
  expect(screen.queryByText('PRIVATE RAW TEXT')).not.toBeInTheDocument()
  expect(api).toHaveBeenCalledTimes(2)
  expect(JSON.stringify(client.getQueryCache().getAll().map((q) => q.state.data))).not.toContain('PRIVATE RAW TEXT')
})
