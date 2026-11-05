import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import type { SimState } from '@/shared/api/client'
import { useBaselineRestore } from '@/shared/api/hooks'
import { connectWs, useWs } from '@/shared/ws/client'
import { Header } from '../Header'

const layout = vi.hoisted(() => ({ mobile: false }))
vi.mock('@/shared/layout/device-store', async original => ({ ...await original<typeof import('@/shared/layout/device-store')>(), useMobileLayout: () => layout.mobile }))
vi.mock('@/shared/theme', () => ({ ThemeSelector: () => null }))
vi.mock('@/shared/layout/device', () => ({ DeviceSelector: () => null }))
vi.mock('@/shared/layout/RoleSelector', () => ({ RoleSelector: () => null }))
vi.mock('@/shared/components/GlobalSearch', () => ({ GlobalSearch: () => null }))
vi.mock('../JuryModal', () => ({ JuryModal: () => null }))

class FakeSocket {
  static latest: FakeSocket
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  send = vi.fn()
  constructor() { FakeSocket.latest = this }
  close() { this.onclose?.() }
  message(state: SimState, type = 'sim.tick') {
    this.onmessage?.({ data: JSON.stringify({ topic: 'sim', type, ts: '2026-11-05T04:00:00Z', data: state }) })
  }
}
const snapshot = (status: 'paused' | 'running' | null, id: number | null = 7): SimState => ({
  sim_time: '2026-11-09T06:00:00Z', day_no: 0, phase: 'morning', speed: 1,
  running: status === 'running', is_working_day: true, current_run_id: id, current_run_status: status,
}) as SimState
let state: SimState
let client: QueryClient
let disconnect: (() => void) | undefined
const actions: string[] = []
let conflict = false
let getState: (() => Promise<SimState>) | undefined
beforeEach(async () => {
  layout.mobile = false
  await i18n.changeLanguage('en')
  actions.length = 0
  conflict = false
  getState = undefined
  state = snapshot(null, null)
  useWs.setState({ sim: null, status: 'closed', events: [] })
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    let body: unknown = {}
    let status = 200
    if (url === '/api/sim/state') body = getState ? await getState() : state
    if (url === '/api/health') body = { tgbot: 'disabled' }
    if (url === '/api/sim/control') {
      const action = JSON.parse(String(init?.body)).action as string
      actions.push(action)
      if (conflict) { status = 409; body = { title: 'Conflict', detail: 'No current run to resume' } }
      else { state = snapshot(action === 'pause' ? 'paused' : 'running'); body = state }
    }
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  }))
})
afterEach(() => { cleanup(); disconnect?.(); disconnect = undefined; client.clear(); vi.unstubAllGlobals() })
function RestoreButton() {
  const restore = useBaselineRestore()
  return <button onClick={() => restore.mutate()}>Fixture baseline</button>
}
function show() {
  render(<QueryClientProvider client={client}><MemoryRouter><Header /><RestoreButton /></MemoryRouter></QueryClientProvider>)
  if (layout.mobile) fireEvent.click(screen.getByRole('button', { name: /menu/i }))
}
it('uses the refreshed baseline instead of the stale paused WS run and starts a new run', async () => {
  useWs.getState().setSim(snapshot('paused'))
  show()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  await screen.findByRole('button', { name: 'Pause' })
  expect(actions).toEqual(['start'])
  expect(useWs.getState().sim?.running).toBe(true)
  state = snapshot(null, null)
  fireEvent.click(screen.getByRole('button', { name: 'Fixture baseline' }))
  expect(await screen.findByRole('button', { name: 'Start' })).toBeEnabled()
  expect(useWs.getState().sim?.current_run_id).toBeNull()
})
it.each(['sim.tick', 'sim.control'])('tracks %s and acknowledged pause/resume without a stale live override', async type => {
  show()
  await screen.findByRole('button', { name: 'Start' })
  act(() => { disconnect = connectWs(client) })
  state = snapshot('running')
  act(() => FakeSocket.latest.message(state, type))
  fireEvent.click(await screen.findByRole('button', { name: 'Pause' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
  await screen.findByRole('button', { name: 'Pause' })
  expect(actions).toEqual(['pause', 'resume'])
  expect(client.getQueryData<SimState>(['sim-state'])?.running).toBe(true)
})
it('refreshes the global snapshot on reconnect after the run was reset elsewhere', async () => {
  state = snapshot('paused')
  show()
  await screen.findByRole('button', { name: 'Resume' })
  act(() => { disconnect = connectWs(client) })
  act(() => FakeSocket.latest.message(state))
  state = snapshot(null, null)
  act(() => FakeSocket.latest.onopen?.())
  await screen.findByRole('button', { name: 'Start' })
  expect(useWs.getState().sim?.current_run_id).toBeNull()
})
it.each([false, true])('shows rejected control and refreshes its state; mobile=%s', async mobile => {
  layout.mobile = mobile
  state = snapshot('paused')
  show()
  await screen.findByRole('button', { name: 'Resume' })
  conflict = true
  state = snapshot(null, null)
  fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
  expect(await screen.findByText('No current run to resume')).toBeInTheDocument()
  expect(screen.getByText(String(i18n.t('care.errors.request')))).toBeVisible()
  await screen.findByRole('button', { name: 'Start' })
  expect(actions).toEqual(['resume'])
  conflict = false
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  await screen.findByRole('button', { name: 'Pause' })
  await waitFor(() => expect(screen.queryByText('No current run to resume')).not.toBeInTheDocument())
})
it('a pending HTTP snapshot cannot overwrite a newer WS tick', async () => {
  show()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start' })).toBeEnabled())
  let finish: (state: SimState) => void = () => {}
  let markStarted: () => void = () => {}
  const started = new Promise<void>(resolve => { markStarted = resolve })
  getState = () => new Promise(resolve => { finish = resolve; markStarted() })
  act(() => { void client.invalidateQueries({ queryKey: ['sim-state'] }) })
  await started
  act(() => { disconnect = connectWs(client) })
  act(() => FakeSocket.latest.message(snapshot('running')))
  expect(client.getQueryData<SimState>(['sim-state'])?.running).toBe(true)
  await act(async () => { finish(snapshot(null, null)) })
  expect(await screen.findByRole('button', { name: 'Pause' })).toBeEnabled()
  expect(client.getQueryData<SimState>(['sim-state'])?.running).toBe(true)
  expect(useWs.getState().sim?.running).toBe(true)
})

it('keeps Start disabled until the initial authoritative snapshot arrives', async () => {
  let finish: (state: SimState) => void = () => {}
  getState = () => new Promise(resolve => { finish = resolve })
  show()
  expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  expect(actions).toEqual([])
  await act(async () => { finish(snapshot(null, null)) })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start' })).toBeEnabled())
})
