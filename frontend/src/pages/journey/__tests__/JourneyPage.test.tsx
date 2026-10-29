import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi, expect, it, beforeEach } from 'vitest'
import '@/shared/i18n'
import { JourneyPage } from '..'
import type { Journey, TraceEvent } from '@/shared/api/trace'
import { getJourney } from '@/shared/api/trace'
import { loadSignal, loadRun, loadClient, loadEconomics, sendJourneyMessage } from '../api'
import { ApiError } from '@/shared/api/client'
import { useWs } from '@/shared/ws/client'
import { elapsedSeconds } from '../timing'

const stages = ['intake', 'understanding', 'identity', 'rules', 'decision', 'action', 'execution', 'client_outcome'] as const
const event: TraceEvent = {
  id: 'e',
  kind: 'human_request',
  phase: 'after',
  ts_sim: '2026-11-10T10:00:00Z',
  ts_real: '2026-10-29T10:00:00Z',
  actor: { kind: 'human', label_ru: 'Человек' },
  title_ru: 'Запрошено решение',
  brief_ru: 'Нужна проверка',
  key_facts: [],
  badges: { llm_source: 'live' },
  links: {},
  importance: 'key',
  run_id: 'SR-1',
}
const journey: Journey = {
  subject: { kind: 'signal', ref: 'SIG-000001', title_ru: 'Тест' },
  stages: stages.map((stage) => ({
    stage,
    status: stage === 'decision' ? 'waiting_human' : 'pending',
    events:
      stage === 'decision'
        ? [event]
        : stage === 'intake'
          ? [
              {
                ...event,
                id: 'in',
                kind: 'signal_created',
                title_ru: 'Сигнал принят',
                brief_ru: 'Тестовое сообщение',
                object_ref: { kind: 'signal', ref: 'SIG-000001' },
              },
            ]
          : [],
  })),
  client_lane: [],
  summary: { outcome_ru: 'Обработка продолжается', llm_source: 'live' },
}
vi.mock('@/shared/api/trace', () => ({ getJourney: vi.fn() }))
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  loadSignal: vi.fn(),
  loadRun: vi.fn(),
  loadClient: vi.fn(),
  loadEconomics: vi.fn(),
  sendJourneyMessage: vi.fn(),
}))
vi.mock('@/shared/api/hooks', () => ({
  useClients: () => ({ data: [{ id: 7, display_name: 'Тестовый клиент', public_id: 'CL-000007', segment_code: 'vip' }] }),
  useAgentGraph: () => ({
    data: {
      version: 'test',
      nodes: [
        { id: 'normalize', kind: 'llm' },
        { id: 'classify', kind: 'llm' },
      ],
      edges: [{ from: 'normalize', to: 'classify' }],
    },
  }),
  useHitlItem: () => ({ data: undefined }),
}))
vi.mock('@/pages/workspace/HitlQueue', () => ({ HitlCard: () => null }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getJourney).mockResolvedValue(structuredClone(journey))
  vi.mocked(loadSignal).mockResolvedValue({ id: 1, client: { id: 7 }, agent_runs: [{ id: 10 }], incidents: [{ id: 20 }] })
  vi.mocked(loadRun).mockResolvedValue({ id: 10, outcome: 'awaiting_human', current_node: 'wait_human', steps: [] })
  vi.mocked(loadClient).mockResolvedValue({ id: 7, display_name: 'Тестовый клиент', clv_estimate_rub: 100000 })
  vi.mocked(loadEconomics).mockResolvedValue({ potential_loss_rub: 48.05, prevented_loss_rub: 0, formula_ru: '1 × 10% × 50% × 961' })
  vi.mocked(sendJourneyMessage).mockResolvedValue(2)
  useWs.setState({ status: 'open', events: [] })
})
function mount(path = '/journey/SIG-000001') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/journey/:ref?" element={<JourneyPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return qc
}
it('renders eight selectable stages, a human timer, graph and separate server CLV/dCLTV', async () => {
  mount()
  expect(await screen.findByText(/Запрошено решение/)).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Внутри банка' })).getAllByRole('listitem')).toHaveLength(8)
  expect(screen.getByRole('timer')).toHaveTextContent('Ожидаем решения человека:')
  expect(screen.getByRole('img')).toBeInTheDocument()
  expect(await screen.findByText(/100\s*000/)).toBeInTheDocument()
  expect(screen.getByText('1 × 10% × 50% × 961')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /1\. Поступление/ }))
  expect(screen.getByText(/Сигнал принят/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Показывать активную стадию' }))
  expect(screen.getByText(/Запрошено решение/)).toBeInTheDocument()
})
it('does not mix simulated and real clocks or epoch timestamps', () => {
  const events = [event, { ...event, ts_sim: null, ts_real: '2026-10-29T10:00:05Z' }]
  expect(elapsedSeconds(events, 'ts_sim')).toBe(0)
  expect(elapsedSeconds(events, 'ts_real')).toBe(5)
  expect(elapsedSeconds([{ ...event, ts_real: '1970-01-01T00:00:00Z', ts_sim: null }], 'ts_real')).toBeNull()
})
it('sends through ingest and pins that exact signal before waiting for the agent', async () => {
  mount('/journey')
  fireEvent.change(screen.getByLabelText(/Клиент \(/), { target: { value: '7' } })
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Проверьте мой вклад' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await screen.findByText('Дополнение к этому обращению')
  expect(vi.mocked(sendJourneyMessage).mock.calls[0]?.[0]).toEqual(
    expect.objectContaining({
      text: 'Проверьте мой вклад',
      client: { client_id: 7 },
      origin: 'jury',
      channel: 'chat',
      external_id: expect.stringMatching(/^journey-/),
    }),
  )
  expect(vi.mocked(getJourney).mock.calls.some(([ref]) => ref === 'SIG-000002')).toBe(true)
})
it('updates the customer lane only from delivered messages', async () => {
  const qc = mount()
  await screen.findByText('Клиент пока не получил ответ — требуется решение человека.')
  vi.mocked(getJourney).mockResolvedValue({
    ...journey,
    client_lane: [{ channel_code: 'chat', kind: 'ack', text_ru: 'Обращение принято банком', delivered_at: '2026-10-29T10:00:02Z' }],
  })
  await act(() => qc.invalidateQueries({ queryKey: ['journey'] }))
  expect(await screen.findByText('Обращение принято банком')).toBeInTheDocument()
})
it('highlights WS node only from the selected run', async () => {
  vi.mocked(loadRun).mockResolvedValue({ id: 10, outcome: null, current_node: 'normalize', steps: [] })
  mount()
  await screen.findByText(/Обработка:/)
  act(() =>
    useWs.getState().push({ topic: 'agent', type: 'step_started', ts: new Date().toISOString(), data: { run_id: 10, node: 'classify' } }),
  )
  expect(screen.getByRole('img').querySelector('.animate-pulse')?.parentElement?.textContent).toContain('classify')
  act(() =>
    useWs.getState().push({ topic: 'agent', type: 'step_started', ts: new Date().toISOString(), data: { run_id: 99, node: 'normalize' } }),
  )
  expect(screen.getByRole('img').querySelector('.animate-pulse')?.parentElement?.textContent).toContain('classify')
})
it('keeps composer available for an empty journey without fictitious monetary zeros', async () => {
  vi.mocked(getJourney).mockRejectedValue(new ApiError(404, null, 'not found'))
  mount('/journey')
  expect(await screen.findByRole('button', { name: 'Отправить на обработку' })).toBeInTheDocument()
  expect(screen.queryByText(/0,00/)).not.toBeInTheDocument()
})

it('prefers the request agent over a newer twin and lets the viewer inspect both', async () => {
  vi.mocked(loadSignal).mockResolvedValue({
    id: 1,
    agent_runs: [
      { id: 10, kind: 'agent' },
      { id: 11, kind: 'client_twin' },
    ],
  })
  vi.mocked(loadRun).mockImplementation(async (id) => ({
    id,
    kind: id === 11 ? 'client_twin' : 'agent',
    outcome: id === 11 ? 'completed' : 'awaiting_human',
    current_node: id === 11 ? 'twin_react' : 'wait_human',
    steps: id === 11 ? [{ seq: 1, node: 'twin_react', model: 'GigaChat-3-Pro', status: 'ok' }] : [],
  }))
  mount()
  expect(await screen.findByRole('link', { name: /Под капотом · #10/ })).toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: 'Запуск на графе' }), { target: { value: '11' } })
  expect(await screen.findByRole('link', { name: /Под капотом · #11/ })).toBeInTheDocument()
  expect(screen.getByText(/GigaChat-3-Pro/)).toBeInTheDocument()
})

it('reuses the ingest idempotency key when retrying the same message after a network error', async () => {
  vi.mocked(sendJourneyMessage).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(2)
  mount('/journey')
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Проверьте мой вклад' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await screen.findByText(/network/)
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await screen.findByText('Дополнение к этому обращению')
  expect(vi.mocked(sendJourneyMessage).mock.calls[0]?.[0].external_id).toBe(vi.mocked(sendJourneyMessage).mock.calls[1]?.[0].external_id)
})

it('follows a related child agent via recorded engine links even without synthetic run events', async () => {
  const data = structuredClone(journey)
  data.stages[4]!.events[0]!.links.engine_step = '/engine/12?step=8'
  vi.mocked(getJourney).mockResolvedValue(data)
  vi.mocked(loadSignal).mockResolvedValue({
    id: 1,
    agent_runs: [
      { id: 10, kind: 'agent' },
      { id: 11, kind: 'client_twin' },
    ],
  })
  vi.mocked(loadRun).mockImplementation(async (id) => ({
    id,
    kind: id === 11 ? 'client_twin' : 'agent',
    outcome: id === 12 ? 'awaiting_human' : 'completed',
    steps: [],
  }))
  mount()
  expect(await screen.findByRole('link', { name: /Под капотом · #12/ })).toBeInTheDocument()
})
