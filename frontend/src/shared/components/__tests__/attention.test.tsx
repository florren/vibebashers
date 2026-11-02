import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api, type IncidentBrief } from '@/shared/api/client'
import { useUiTheme } from '@/shared/theming/store'
import { useWs } from '@/shared/ws/client'
import { resolveAttention } from '@/shared/theming/attention'
import { assertBlockBudget, MOTION } from '@/shared/ui/motion'
import { UndoToast } from '../UndoToast'
import { useUndo } from '@/shared/ui/undo'
import { ConfirmAction } from '../ConfirmAction'
import { PriorityStrip } from '../PriorityStrip'
import { SlaWarning } from '../SlaWarning'
import { slaWarning } from '@/shared/ui/sla'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
const clients: QueryClient[] = []
function show(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client)
  return render(<QueryClientProvider client={client}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>)
}
beforeEach(() => {
  vi.clearAllMocks(); useUndo.setState({ entry: null }); useUiTheme.setState({ simTime: '2026-11-09T06:00:00Z' })
  useWs.setState({ sim: null, events: [] })
  vi.mocked(api).mockImplementation(async path => path === '/api/settings' ? { sla_warn_hours: 4 } : path === '/api/sim/state' ? { current_run_id: 11 } : { items: [] })
})
afterEach(() => { cleanup(); clients.splice(0).forEach(c => c.clear()); vi.useRealTimers() })
it('explicit attention wins; product_manager/cabinet stay calm, ops/demonstrator default control room', () => {
  expect(resolveAttention(null, 'brand', '/')).toBe('calm')
  expect(resolveAttention(null, 'ops', '/')).toBe('control_room')
  expect(resolveAttention(null, 'ops', '/cabinet/deposit')).toBe('calm')
  expect(resolveAttention(null, 'ops', '/', 'product_manager')).toBe('calm')
  expect(resolveAttention(null, 'brand', '/', 'demonstrator')).toBe('control_room')
  expect(resolveAttention('control_room', 'brand', '/cabinet')).toBe('control_room')
})
it('undo restores once before 8s, expires exactly at 8s and cannot run an expired callback', () => {
  vi.useFakeTimers(); const restore = vi.fn(); show(<UndoToast />)
  act(() => useUndo.getState().offer(restore)); fireEvent.click(screen.getByRole('button', { name: 'Отменить' })); expect(restore).toHaveBeenCalledTimes(1)
  act(() => useUndo.getState().undo()); expect(restore).toHaveBeenCalledTimes(1)
  act(() => useUndo.getState().offer(restore)); act(() => vi.advanceTimersByTime(8000))
  expect(screen.queryByRole('button', { name: 'Отменить' })).not.toBeInTheDocument()
  act(() => useUndo.getState().undo()); expect(restore).toHaveBeenCalledTimes(1)
})
it('a new local action replaces the old undo, dismissal never executes either callback', () => {
  const first = vi.fn(), second = vi.fn(); useUndo.getState().offer(first); useUndo.getState().offer(second); useUndo.getState().undo()
  expect(first).not.toHaveBeenCalled(); expect(second).toHaveBeenCalledOnce()
  useUndo.getState().offer(first); useUndo.getState().dismiss(); useUndo.getState().undo(); expect(first).not.toHaveBeenCalled()
})
it('confirmation names the consequence; cancel does not execute and confirm does exactly once', () => {
  const cancel = vi.fn(), confirm = vi.fn()
  show(<ConfirmAction open title="Решение" consequence="Сохранит решение на сервере; локально отменить нельзя." onCancel={cancel} onConfirm={confirm} />)
  expect(screen.getByRole('dialog', { name: 'Решение' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Вернуться' })); expect(cancel).toHaveBeenCalledOnce(); expect(confirm).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить действие' })); expect(confirm).toHaveBeenCalledOnce()
})
it('SLA uses sim clock and configurable absolute hours, includes 4h boundary and excludes closed or invalid clocks', () => {
  const now = '2026-11-09T06:00:00Z'
  expect(slaWarning('2026-11-09T10:00:00Z', now, 'new', undefined)).toBe(4)
  expect(slaWarning('2026-11-09T10:00:01Z', now, 'new', 4)).toBeNull()
  expect(slaWarning('2026-11-09T08:00:00Z', now, 'new', 1)).toBeNull()
  expect(slaWarning('2026-11-09T05:00:00Z', now, 'new', 4)).toBe(-1)
  for (const status of ['closed','resolved','rejected','duplicate']) expect(slaWarning(now, now, status, 4)).toBeNull()
  expect(slaWarning('bad', now, 'new', 4)).toBeNull(); expect(slaWarning(now, null, 'new', 4)).toBeNull()
  expect(slaWarning('2026-11-09T10:00:00Z', now, 'new', Infinity)).toBe(4)
})
it('SLA marker follows authoritative WS-derived simTime, not the device clock', async () => {
  show(<SlaWarning due="2026-11-09T10:00:00Z" status="new" />)
  expect(await screen.findByText('Срок через 4 ч')).toBeVisible()
  act(() => useUiTheme.setState({ simTime: '2026-11-09T11:00:00Z' })); expect(screen.getByText('Срок прошёл')).toBeVisible()
})
it('priorities contain at most 3 current-run entries and move only after manual selection', async () => {
  const rows = Array.from({ length: 4 }, (_, n) => ({ id: n + 1, public_id: `INC-00000${n+1}`, priority: n+1 } as IncidentBrief))
  vi.mocked(api).mockImplementation(async path => path === '/api/sim/state' ? { current_run_id: 11 } : path === '/api/settings' ? {} : { items: rows })
  show(<PriorityStrip />)
  expect(await screen.findByRole('link', { name: 'INC-000001 · P1' })).toHaveAttribute('href', '/incidents/1')
  expect(screen.getAllByRole('button', { name: /^Приоритет / })).toHaveLength(3)
  fireEvent.click(screen.getByRole('button', { name: 'Приоритет 3' })); expect(screen.getByRole('link', { name: 'INC-000003 · P3' })).toBeVisible()
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/incidents', expect.objectContaining({ query: expect.objectContaining({ run_id: 11, sort: 'priority', limit: 3 }) })))
  expect(screen.queryByText(/INC-000004/)).not.toBeInTheDocument()
})
it('calm block budget allows nine real blocks and rejects a tenth rather than hiding it', () => {
  const root = document.createElement('main'); root.innerHTML = '<section data-block></section>'.repeat(9)
  expect(() => assertBlockBudget(root)).not.toThrow(); root.append(document.createElement('section')); root.lastElementChild!.setAttribute('data-block','tenth')
  expect(() => assertBlockBudget(root)).toThrow('10/9')
  expect(MOTION.enterMs).toBeGreaterThanOrEqual(250); expect(MOTION.revealMs).toBeLessThanOrEqual(400); expect(MOTION.liftPx).toBe(2)
})


it('selected priority follows its real ID when the server reorders the same three items', async () => {
  let rows = [1,2,3].map(id => ({ id, public_id: `INC-00000${id}`, priority: id }))
  vi.mocked(api).mockImplementation(async path => path === '/api/sim/state' ? { current_run_id: 11 } : path === '/api/settings' ? {} : { items: rows })
  show(<PriorityStrip />)
  await screen.findByRole('link', { name: 'INC-000001 · P1' })
  fireEvent.click(screen.getByRole('button', { name: 'Приоритет 3' }))
  rows = [rows[2]!, rows[0]!, rows[1]!]
  await act(async () => { await clients[0]!.invalidateQueries({ queryKey: ['incidents'] }) })
  expect(screen.getByRole('link', { name: 'INC-000003 · P3' })).toBeVisible()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Приоритет 1' })).toHaveAttribute('aria-pressed', 'true'))
})
