import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi, expect, it, beforeEach } from 'vitest'
import i18n from '@/shared/i18n'
import { JourneyPage } from '..'
import type { Journey, TraceEvent } from '@/shared/api/trace'
import { getJourney } from '@/shared/api/trace'
import { loadSignal, loadRun, loadClient, loadEconomics, sendJourneyMessage } from '../api'
import { ApiError, type AgentStep } from '@/shared/api/client'
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
  useRefName: () => (code: string) => code,
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
  expect(await screen.findByRole('group', { name: 'Граф' })).toBeInTheDocument()
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
      meta: { journey_execution: { scenario_id: 'deposit_promo_rate', team_outcome: 'on_time', emulate_humans: true, auto_advance: true } },
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
it('сортирует клиентскую дорожку по instant с offsets и microseconds', async () => {
  const data = structuredClone(journey)
  const intake = data.stages.find(stage => stage.stage === 'intake')!
  intake.events[0]!.ts_real = '2026-11-03T12:00:00.123100+03:00'
  intake.events[0]!.brief_ru = 'Первый вопрос клиента'
  data.client_lane = [
    { channel_code: 'chat', kind: 'ack', text_ru: 'Первый ответ банка', delivered_at: '2026-11-03T09:00:00.123200Z' },
    { channel_code: 'client_reaction', kind: 'clarification', text_ru: 'Следующее сообщение клиента', delivered_at: '2026-11-03T09:00:00.123300Z' },
  ]
  vi.mocked(getJourney).mockResolvedValue(data)
  mount()
  const log = await screen.findByRole('log')
  await within(log).findByText('Первый ответ банка')
  const content = log.textContent!
  expect(content.indexOf('Первый вопрос клиента')).toBeLessThan(content.indexOf('Первый ответ банка'))
  expect(content.indexOf('Первый ответ банка')).toBeLessThan(content.indexOf('Следующее сообщение клиента'))
})
it('highlights WS node only from the selected run', async () => {
  vi.mocked(loadRun).mockResolvedValue({ id: 10, outcome: null, current_node: 'normalize', steps: [] })
  mount()
  await screen.findByText(/Обработка:/)
  act(() => useWs.getState().push({ topic: 'agent', type: 'step_started', ts: new Date().toISOString(), data: { run_id: 10, node: 'classify' } }))
  expect(screen.getByRole('group', { name: 'Граф' }).querySelector('.status-indicator')?.parentElement?.textContent).toContain('Классификация')
  act(() => useWs.getState().push({ topic: 'agent', type: 'step_started', ts: new Date().toISOString(), data: { run_id: 99, node: 'normalize' } }))
  expect(screen.getByRole('group', { name: 'Граф' }).querySelector('.status-indicator')?.parentElement?.textContent).toContain('Классификация')
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

it('does not attribute the composer client value to an unidentified pinned signal', async () => {
  vi.mocked(loadSignal).mockResolvedValue({ id: 1, client: null, agent_runs: [], incidents: [] })
  mount()
  await screen.findByText(/Запрошено решение/)
  fireEvent.change(screen.getByLabelText(/Клиент \(/), { target: { value: '7' } })
  expect(loadClient).not.toHaveBeenCalled()
  expect(screen.queryByText(/100\s*000/)).not.toBeInTheDocument()
})

it('pins the selected journey when automatic following is disabled and resumes latest on request', async () => {
  let latest = structuredClone(journey)
  vi.mocked(getJourney).mockImplementation(async (ref) => (ref ? structuredClone(journey) : latest))
  const qc = mount('/journey')
  await screen.findByRole('link', { name: 'Открыть след SIG-000001' })
  fireEvent.click(screen.getByLabelText('Автопереход к новым обращениям'))
  expect(await screen.findByRole('link', { name: 'Открыть след SIG-000001' })).toBeInTheDocument()
  expect(screen.getByLabelText('Автопереход к новым обращениям')).not.toBeChecked()
  latest = { ...structuredClone(journey), subject: { ...journey.subject, ref: 'SIG-000002' } }
  await act(() => qc.invalidateQueries({ queryKey: ['journey'] }))
  expect(await screen.findByRole('link', { name: 'Открыть след SIG-000001' })).toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Автопереход к новым обращениям'))
  expect(await screen.findByRole('link', { name: 'Открыть след SIG-000002' })).toBeInTheDocument()
})

it('shows the server dCLTV estimate for an anonymous customer instead of a fabricated CLV', async () => {
  vi.mocked(loadSignal).mockResolvedValue({ id: 1, client: null, agent_runs: [], incidents: [{ id: 20 }] })
  vi.mocked(loadEconomics).mockResolvedValue({ rate_code: 'bank_average', rate_rub: 4050, potential_loss_rub: 202.5, prevented_loss_rub: 0 })
  mount()
  expect(await screen.findByText(/4\s*050/)).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Оценка потери при уходе · ставка dCLTV' })).toBeInTheDocument()
  expect(loadClient).not.toHaveBeenCalled()
})

it('links the exact retry to bank events, keeps manual selection on refresh, and returns to live following', async () => {
  const data = structuredClone(journey)
  const attempt = (seq: number, run = 10): TraceEvent => ({
    ...event,
    id: `${run}:${seq}`,
    kind: 'classification',
    title_ru: `Классификация ${run}:${seq}`,
    links: { engine_step: `/engine/${run}?step=${seq}` },
  })
  data.stages[1]!.events = [attempt(2), attempt(3), attempt(3, 11)]
  data.stages[5]!.events = [
    { ...event, id: 'notification', kind: 'notification', title_ru: 'Принято командой', object_ref: { kind: 'notification', ref: 'NTF-000007' } },
  ]
  vi.mocked(getJourney).mockResolvedValue(data)
  const steps: AgentStep[] = [
    { seq: 2, node: 'classify', status: 'error' as const },
    {
      seq: 3,
      node: 'classify',
      status: 'ok' as const,
      output: { product: null, confidence: 0.93, summary: 'PRIVATE_PROMPT' },
      model: 'GigaChat-3-Ultra',
      latency_ms: 150,
      tool_calls: [{ name: 'notify_client', result: { notification_id: 7 } }],
    },
  ]
  vi.mocked(loadRun).mockImplementation(async (id) => ({
    id,
    kind: 'agent',
    outcome: id === 10 ? 'awaiting_human' : 'completed',
    current_node: 'wait_human',
    steps: id === 10 ? steps : [{ seq: 3, node: 'classify', status: 'ok' }],
  }))
  const qc = mount()
  const node = await screen.findByRole('button', { name: /Классификация · Завершён/ })
  fireEvent.keyDown(node, { key: 'Enter' })
  const bank = screen.getByRole('region', { name: 'Внутри банка' })
  expect(node).toHaveAttribute('aria-pressed', 'true')
  expect(bank.querySelectorAll('[data-related-step="true"]')).toHaveLength(2)
  expect(within(bank).getByRole('button', { name: /Принято командой/ })).toBeInTheDocument()
  expect(screen.getByText('93%')).toBeInTheDocument()
  expect(screen.queryByText('PRIVATE_PROMPT')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: /Выполнение шага/ }), { target: { value: '2' } })
  expect(bank.querySelectorAll('[data-related-step="true"]')).toHaveLength(1)
  expect(bank.querySelector('[data-related-step="true"]')).toHaveTextContent('Классификация 10:2')
  steps.push({ seq: 4, node: 'normalize', status: 'ok' })
  await act(() => qc.invalidateQueries({ queryKey: ['agent', 'journey'] }))
  expect(screen.getByRole('combobox', { name: /Выполнение шага/ })).toHaveValue('2')
  fireEvent.click(within(bank).getByRole('button', { name: /Классификация 11:3/ }))
  expect(await screen.findByRole('link', { name: /Под капотом · #11/ })).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: 'Запуск на графе' })).toHaveValue('11')
  fireEvent.click(within(bank).getByRole('button', { name: 'К текущему шагу' }))
  expect(bank.querySelectorAll('[data-related-step="true"]')).toHaveLength(0)
  expect(screen.queryByLabelText('Выбранный шаг')).not.toBeInTheDocument()
  expect(sendJourneyMessage).not.toHaveBeenCalled()
})

it('preserves an explicit run in follow/replay navigation and disables writes and economic computation', async () => {
  mount('/journey/SIG-000001?run_id=19')
  expect(await screen.findByText(/Запрошено решение/)).toBeInTheDocument()
  expect(getJourney).toHaveBeenCalledWith('SIG-000001', 'jury', false, '19')
  expect(loadEconomics).not.toHaveBeenCalled()
  expect(screen.queryByRole('textbox', { name: 'Сообщение клиента' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Отправить' })).not.toBeInTheDocument()
  expect(screen.getByText(/Контекст выбранного запуска: только просмотр/)).toBeInTheDocument()
  const replay = screen.getByRole('link', { name: 'Повтор' })
  expect(replay).toHaveAttribute('href', '/journey/SIG-000001?run_id=19&mode=replay')
  fireEvent.click(replay)
  expect(getJourney).toHaveBeenCalledWith('SIG-000001', 'any', false, '19')
  expect(sendJourneyMessage).not.toHaveBeenCalled()
})

it('does not load an unrelated signal agent run outside an explicit scoped trace', async () => {
  const scoped = structuredClone(journey)
  scoped.stages[0]!.events[0]!.links.engine_step = '/engine/10?seq=1'
  vi.mocked(getJourney).mockResolvedValue(scoped)
  vi.mocked(loadSignal).mockResolvedValue({ id: 1, agent_runs: [{ id: 99 }, { id: 10 }], incidents: [] })
  vi.mocked(loadRun).mockImplementation(async id => ({ id, outcome: 'completed', steps: [] }))
  mount('/journey/SIG-000001?run_id=19')
  await screen.findByRole('group', { name: 'Граф' })
  expect(loadRun).toHaveBeenCalledWith(10)
  expect(loadRun).not.toHaveBeenCalledWith(99)
})

it('submits the local selected profile with the typed message without creating a scenario first', async () => {
  mount('/journey')
  fireEvent.click(screen.getByText('Профиль ручного обращения Journey'))
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'failed' } })
  fireEvent.click(screen.getByLabelText('Агент отвечает за сотрудников'))
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Проверьте синтетический вклад' } })
  expect(sendJourneyMessage).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await screen.findByText('Дополнение к этому обращению')
  expect(sendJourneyMessage).toHaveBeenCalledTimes(1)
  expect(vi.mocked(sendJourneyMessage).mock.calls[0]?.[0]).toEqual(expect.objectContaining({
    text: 'Проверьте синтетический вклад', origin: 'jury', channel: 'chat',
    meta: { journey_execution: { scenario_id: 'deposit_promo_rate', team_outcome: 'failed', emulate_humans: false, auto_advance: true } },
  }))
})
it('uses a fresh idempotency key when the local execution profile changes after a failed request', async () => {
  vi.mocked(sendJourneyMessage).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(2)
  mount('/journey')
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Проверьте синтетический вклад' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await screen.findByText(/network/)
  fireEvent.click(screen.getByText('Профиль ручного обращения Journey'))
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'late' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await screen.findByText('Дополнение к этому обращению')
  const calls = vi.mocked(sendJourneyMessage).mock.calls
  expect(calls[0]?.[0].external_id).not.toBe(calls[1]?.[0].external_id)
  expect(calls[0]?.[0].meta?.journey_execution).toEqual(expect.objectContaining({ team_outcome: 'on_time' }))
  expect(calls[1]?.[0].meta?.journey_execution).toEqual(expect.objectContaining({ team_outcome: 'late' }))
})

it('keeps the locally sent subject when unpinned and preserves latest-current behavior for sim origin', async () => {
  const own = structuredClone(journey)
  own.subject.ref = 'SIG-000002'
  own.stages[0]!.events[0]!.object_ref = { kind: 'signal', ref: 'SIG-000002' }
  vi.mocked(getJourney).mockImplementation(async ref => structuredClone(ref === 'SIG-000002' ? own : journey))
  const qc = mount('/journey')
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Локальное обращение' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await screen.findByText('Дополнение к этому обращению')
  const autoFollow = screen.getByLabelText('Автопереход к новым обращениям')
  expect(autoFollow).not.toBeChecked()
  const beforeUnpin = vi.mocked(getJourney).mock.calls.length
  fireEvent.click(autoFollow)
  expect(autoFollow).toBeChecked()
  await act(async () => { await qc.invalidateQueries({ queryKey: ['journey'] }) })
  expect(vi.mocked(getJourney).mock.calls.length).toBeGreaterThan(beforeUnpin)
  await waitFor(() => expect(screen.getAllByText('SIG-000002').length).toBeGreaterThan(0))
  expect(vi.mocked(getJourney).mock.calls.slice(beforeUnpin).every(([ref]) => ref === 'SIG-000002')).toBe(true)
  expect(sendJourneyMessage).toHaveBeenCalledTimes(1)
  fireEvent.change(screen.getByLabelText('Следить за'), { target: { value: 'sim' } })
  await waitFor(() => expect(getJourney).toHaveBeenCalledWith(undefined, 'sim'))
  expect(sendJourneyMessage).toHaveBeenCalledTimes(1)
})
it('turns a profile change into a new root request while preserving the unsent text', async () => {
  mount('/journey')
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Исходный вклад' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  const followup = await screen.findByRole('button', { name: 'Дополнение к этому обращению' })
  expect(followup).toHaveAttribute('aria-pressed', 'true')
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Несохранённый текст для другого профиля' } })
  fireEvent.click(screen.getByText('Профиль ручного обращения Journey'))
  fireEvent.change(screen.getByLabelText('Работа команды'), { target: { value: 'failed' } })
  expect(screen.getByLabelText('Сообщение клиента')).toHaveValue('Несохранённый текст для другого профиля')
  expect(screen.getByRole('button', { name: 'Новое обращение' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await waitFor(() => expect(sendJourneyMessage).toHaveBeenCalledTimes(2))
  const sent = vi.mocked(sendJourneyMessage).mock.calls[1]![0]
  expect(sent.text).toBe('Несохранённый текст для другого профиля')
  expect(sent.meta).not.toHaveProperty('parent_signal_id')
  expect(sent.meta?.journey_execution).toEqual(expect.objectContaining({ team_outcome: 'failed' }))
})

it('inherits the reloaded parent profile by sending only parent lineage for a followup', async () => {
  // Сохранённое обращение могло иметь nondefault profile: UI default его не переопределяет.
  mount('/journey/SIG-000001')
  await screen.findByText(/Запрошено решение/)
  expect(screen.getByLabelText('Работа команды')).toHaveValue('on_time')
  fireEvent.click(screen.getByRole('button', { name: 'Дополнить выбранное обращение' }))
  fireEvent.change(screen.getByLabelText('Сообщение клиента'), { target: { value: 'Дополнение к сохранённому обращению' } })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить на обработку' }))
  await waitFor(() => expect(sendJourneyMessage).toHaveBeenCalledTimes(1))
  const sent = vi.mocked(sendJourneyMessage).mock.calls[0]![0]
  expect(sent.meta).toEqual({ parent_signal_id: 1 })
  expect(sent.meta).not.toHaveProperty('journey_execution')
  expect(sent.origin).toBe('jury')
})

it.each(['ru', 'en'])('shows the simulation date across days without changing conversation order in %s', async language => {
  const previousLanguage = i18n.language
  await i18n.changeLanguage(language)
  try {
    const data = structuredClone(journey)
    const question = data.stages.find(stage => stage.stage === 'intake')!.events[0]!
    question.brief_ru = 'Вопрос до многодневной обработки'
    question.ts_real = '2026-11-05T10:00:00.123100Z'
    question.ts_sim = '2026-11-09T09:48:00+03:00'
    const reply: Journey['client_lane'][number] = { channel_code: 'chat', kind: 'final', text_ru: 'Ответ после многодневной обработки', delivered_at: '2026-11-05T10:00:00.123200Z', delivered_sim: '2026-11-13T09:33:00+03:00' }
    data.client_lane = [reply]
    vi.mocked(getJourney).mockResolvedValue(data)
    mount()
    const log = await screen.findByRole('log')
    const replyText = await within(log).findByText(reply.text_ru)
    const questionArticle = within(log).getByText(question.brief_ru).closest('article')!
    const replyArticle = replyText.closest('article')!
    expect(questionArticle).toHaveTextContent(new Date(question.ts_sim).toLocaleString(language))
    expect(replyArticle).toHaveTextContent(new Date(reply.delivered_sim!).toLocaleString(language))
    expect(questionArticle).toHaveTextContent(new Date(question.ts_real).toLocaleTimeString(language))
    expect(replyArticle).toHaveTextContent(new Date(reply.delivered_at).toLocaleTimeString(language))
    expect(log.querySelectorAll('article')[0]).toBe(questionArticle)
    expect(log.querySelectorAll('article')[1]).toBe(replyArticle)
  } finally {
    await i18n.changeLanguage(previousLanguage)
  }
})
