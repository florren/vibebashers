import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api, post, type HitlItem, type Signal } from '@/shared/api/client'
import { HitlQueue } from './HitlQueue'
import { SignalsFeed } from './SignalsFeed'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn(), post: vi.fn() }))
const signal: Signal = { id: 88489, public_id: 'SIG-088489', text: 'Снова неверный тариф', channel_code: 'chat', status: 'deferred', incident_refs: ['INC-000826'] }
let item: HitlItem
beforeEach(() => {
  item = { id: 1351, public_id: 'HD-001351', signal, incident: { id: 826, public_id: 'INC-000826', status: 'escalated' }, related_incidents: [{ id: 826, public_id: 'INC-000826', status: 'escalated' }], escalations: [{ kind: 'escalation', ref: 'ESC-000085' }], reason: 'repeat_negative', can_resume: false, process_outcome: 'deferred', decision: null, agent_proposal: { kind: 'escalation' } }
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path.startsWith('/api/refs')) return [] as never
    if (path === '/api/signals') return { items: options?.query?.cursor ? [{ ...signal, id: 1, public_id: 'SIG-000001', status: 'closed' }] : [signal], next_cursor: options?.query?.cursor ? null : '88489' } as never
    if (path === '/api/hitl/queue') return { items: item.decision === 'accept' && !options?.query?.q ? [] : [item], next_cursor: null } as never
    if (path.endsWith('/feedback')) return { items: [], next_cursor: null } as never
    if (path === '/api/hitl/1351') return item as never
    throw new Error(path)
  })
  vi.mocked(post).mockResolvedValue({ id: 1, human_decision_id: 1351 } as never)
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })
function mount(ui: React.ReactNode, path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>)
  return qc
}

it('ищет SIG во всех запусках, показывает связь INC и догружает старые сигналы', async () => {
  mount(<SignalsFeed runId={11} onOpen={vi.fn()} />)
  expect(await screen.findByText(/SIG-088489 → INC-000826/)).toBeInTheDocument()
  expect(api).toHaveBeenCalledWith('/api/signals', expect.objectContaining({ query: expect.objectContaining({ run_id: 'all', cursor: null }) }))
  fireEvent.change(screen.getByLabelText('Поиск сигнала: код или текст'), { target: { value: 'SIG-088489' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/signals', expect.objectContaining({ query: expect.objectContaining({ q: 'SIG-088489', run_id: 'all' }) })))
  fireEvent.click(await screen.findByRole('button', { name: 'Показать ещё' }))
  expect(await screen.findByText(/SIG-000001/)).toBeInTheDocument()
  expect(screen.getByText('закрыт', { selector: 'span' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'ошибка' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'ждём клиента' })).toBeInTheDocument()
})

it('находит связанный INC по SIG и другим кодам в HITL', async () => {
  mount(<HitlQueue runId={11} onOpenSignal={vi.fn()} />, '/?tab=hitl&q=SIG-088489')
  expect(await screen.findByLabelText('Происхождение обращения')).toHaveTextContent('SIG-088489')
  expect(screen.getByLabelText('Происхождение обращения')).toHaveTextContent('INC-000826')
  expect(screen.getByLabelText('Происхождение обращения')).toHaveTextContent('ESC-000085')
  for (const q of ['SIG-088489','INC-000826','ESC-000085']) {
    fireEvent.change(screen.getByLabelText('Поиск связанных сущностей'), { target: { value: q } })
    await waitFor(() => expect(api).toHaveBeenCalledWith('/api/hitl/queue', expect.objectContaining({ query: expect.objectContaining({ q, run_id: 'all' }) })))
  }
  expect(await screen.findByText('Информация оператора')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Изменить' })).not.toBeInTheDocument()
})

it('не теряет карточку и черновик после продолжения процесса и принимает позднюю информацию идемпотентно', async () => {
  let seq = 0
  vi.stubGlobal('crypto', { randomUUID: () => `FEEDBACK-${++seq}` })
  const qc = mount(<HitlQueue runId={11} onOpenSignal={vi.fn()} />)
  const input = await screen.findByLabelText('Дополнительная информация')
  fireEvent.change(input, { target: { value: 'Уточнение по тарифу' } })
  await waitFor(() => expect(qc.getQueryState(['hitl', 'one', 1351])?.status).toBe('success'))
  item = { ...item, decision: 'accept', decided_by: 'operator' }
  await act(async () => { await qc.invalidateQueries({ queryKey: ['hitl'] }) })
  expect(screen.getByLabelText('Дополнительная информация')).toHaveValue('Уточнение по тарифу')
  expect(screen.getByLabelText('Происхождение обращения')).toHaveTextContent('SIG-088489')
  fireEvent.click(screen.getByRole('button', { name: 'Передать информацию' }))
  await screen.findByText('Информация сохранена в истории запроса.')
  fireEvent.click(screen.getByRole('button', { name: 'Передать информацию' }))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  expect(vi.mocked(post).mock.calls[0]?.[1]).toEqual(vi.mocked(post).mock.calls[1]?.[1])
  expect(post).toHaveBeenCalledWith('/api/hitl/1351/feedback', { comment: 'Уточнение по тарифу', idempotency_key: 'FEEDBACK-1' })
  expect(vi.mocked(post).mock.calls.every(([path]) => path.endsWith('/feedback'))).toBe(true)
})

it('переносит набранный комментарий в доступный журнал при автоматическом продолжении', async () => {
  item = { ...item, can_resume: true, process_outcome: 'awaiting_human', agent_proposal: undefined }
  const qc = mount(<HitlQueue runId={11} onOpenSignal={vi.fn()} />)
  fireEvent.change(await screen.findByLabelText('Комментарий'), { target: { value: 'Черновик до таймаута' } })
  await waitFor(() => expect(qc.getQueryState(['hitl', 'one', 1351])?.status).toBe('success'))
  item = { ...item, can_resume: false, decision: 'modify', decided_by: 'timeout', automatic_decision: true, process_outcome: 'deferred' }
  await act(async () => { await qc.invalidateQueries({ queryKey: ['hitl'] }) })
  expect(screen.getByLabelText('Дополнительная информация')).toHaveValue('Черновик до таймаута')
  expect(await screen.findByText(/Автоматическое продолжение по таймауту/)).toBeInTheDocument()
})


it('показывает связанный INC даже без запроса HITL', async () => {
  vi.mocked(api).mockImplementation(async () => ({ items: [], next_cursor: null, related_entities: [{ kind: 'signal', ref: 'SIG-088489' }, { kind: 'incident', ref: 'INC-000826' }] }) as never)
  mount(<HitlQueue runId={11} onOpenSignal={vi.fn()} />, '/?tab=hitl&q=SIG-088489')
  const related = await screen.findByLabelText('Связанные сущности')
  expect(related).toHaveTextContent('SIG-088489')
  expect(related).toHaveTextContent('INC-000826')
})
