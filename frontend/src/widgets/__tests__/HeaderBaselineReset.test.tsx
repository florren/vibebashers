import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { useWs } from '@/shared/ws/client'
import { Header } from '../Header'

const layout = vi.hoisted(() => ({ mobile: false }))
vi.mock('@/shared/layout/device-store', async original => ({ ...await original<typeof import('@/shared/layout/device-store')>(), useMobileLayout: () => layout.mobile }))
vi.mock('@/shared/theme', () => ({ ThemeSelector: () => null }))
vi.mock('@/shared/layout/device', () => ({ DeviceSelector: () => null }))
vi.mock('@/shared/layout/RoleSelector', () => ({ RoleSelector: () => null }))
vi.mock('@/shared/components/GlobalSearch', () => ({ GlobalSearch: () => null }))
vi.mock('../JuryModal', () => ({ JuryModal: () => null }))

let client: QueryClient
let restore: () => Promise<Response>
let time: string
const writes: string[] = []
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
beforeEach(async () => {
  await i18n.changeLanguage('en')
  layout.mobile = false
  writes.length = 0
  time = '2026-11-14T03:14:30Z'
  restore = async () => json({ job_id: 'baseline-job' }, 202)
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  useWs.setState({ sim: null, status: 'closed', events: [] })
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      writes.push(url)
      if (url === '/api/sim/baseline/restore') return restore()
    }
    if (url === '/api/sim/state') return json({ sim_time: time, day_no: 5, phase: 'night', speed: 10, running: false, is_working_day: false, current_run_id: 7, current_run_status: 'stopped' })
    return json({ tgbot: 'disabled' })
  }))
})
afterEach(() => { cleanup(); client.clear(); vi.unstubAllGlobals() })
async function show(mobile = false) {
  layout.mobile = mobile
  render(<QueryClientProvider client={client}><MemoryRouter><Header /></MemoryRouter></QueryClientProvider>)
  if (mobile) fireEvent.click(screen.getByRole('button', { name: /menu/i }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Restore starting data and time' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Restore starting data and time' }))
  return within(screen.getByRole('dialog', { name: 'Restore starting state?' }))
}
it.each([false, true])('requires confirmation and cancel never calls the API; mobile=%s', async mobile => {
  const dialog = await show(mobile)
  expect(dialog.getByText(/human decisions.*will be deleted/)).toBeVisible()
  expect(writes).toEqual([])
  fireEvent.click(dialog.getByRole('button', { name: 'Go back' }))
  expect(screen.queryByRole('dialog', { name: 'Restore starting state?' })).not.toBeInTheDocument()
  expect(writes).toEqual([])
})
it.each([false, true])('uses native baseline restore once, refreshes all snapshots and never starts a run; mobile=%s', async mobile => {
  let finish: (response: Response) => void = () => {}
  restore = () => new Promise(resolve => { finish = resolve })
  client.setQueryData(['signals', 7], { items: ['stale'] })
  const dialog = await show(mobile)
  const confirm = dialog.getByRole('button', { name: 'Restore starting data and time' })
  fireEvent.click(confirm)
  await waitFor(() => expect(writes).toEqual(['/api/sim/baseline/restore']))
  expect(confirm).toBeDisabled()
  expect(dialog.getByRole('button', { name: 'Go back' })).toBeDisabled()
  expect(dialog.getByRole('status')).toHaveTextContent('Restoring the initial state')
  fireEvent.click(confirm)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.getByRole('dialog', { name: 'Restore starting state?' })).toBeVisible()
  if (!mobile) expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled()
  time = '2026-11-09T06:00:00Z'
  await act(async () => { finish(json({ job_id: 'baseline-job' }, 202)) })
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Restore starting state?' })).not.toBeInTheDocument())
  expect(screen.getByRole('status')).toHaveTextContent('Initial state restored')
  expect(client.getQueryData<{ sim_time: string }>(['sim-state'])?.sim_time).toBe(time)
  expect(client.getQueryState(['signals', 7])?.isInvalidated).toBe(true)
  expect(writes).toEqual(['/api/sim/baseline/restore'])
})
it('shows rejected restore, keeps the current time and allows an explicit retry', async () => {
  restore = async () => json({ detail: 'Baseline snapshot is unavailable' }, 409)
  const dialog = await show()
  fireEvent.click(dialog.getByRole('button', { name: 'Restore starting data and time' }))
  await dialog.findByText('Baseline snapshot is unavailable')
  fireEvent.click(dialog.getByText(String(i18n.t('care.details'))))
  expect(dialog.getByText('Baseline snapshot is unavailable')).toBeVisible()
  expect(screen.queryByText(/Initial state restored/)).not.toBeInTheDocument()
  expect(client.getQueryData<{ sim_time: string }>(['sim-state'])?.sim_time).toBe('2026-11-14T03:14:30Z')
  expect(dialog.getByRole('button', { name: 'Restore starting data and time' })).toBeEnabled()
  fireEvent.click(dialog.getByRole('button', { name: 'Go back' }))
  expect(writes).toEqual(['/api/sim/baseline/restore'])
})
