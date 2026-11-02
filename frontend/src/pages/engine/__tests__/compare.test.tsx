import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { CompareTab } from '../CompareTab'
import { comparisonFields, sourceOf, stable } from '../compareModel'
import { compareProfiles, compareResponse, compareTrace, mockClassification, selectedClassification } from '@/test/fixtures/compare'

let result = structuredClone(compareResponse), status = 200, model = 'replay:recorded-test-model', traceError = false
let calls: { path: string; body?: Record<string, unknown> }[], hold: (() => void) | null
const clients: QueryClient[] = []
const json = (value: unknown, code = 200) => new Response(JSON.stringify(value), { status: code, headers: { 'Content-Type': 'application/json' } })
beforeEach(async () => {
  await i18n.changeLanguage('ru'); result = structuredClone(compareResponse); status = 200; model = 'replay:recorded-test-model'; traceError = false; hold = null; calls = []
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (path === '/api/settings/llm-profiles') return json(compareProfiles)
    if (path === '/api/refs/channels') return json([{ code: 'chat', name_ru: 'Чат', name_en: 'Chat' }, { code: 'social', name_ru: 'Соцсети', name_en: 'Social' }])
    if (path.startsWith('/api/agent/runs/')) return traceError ? json({ detail: 'trace unavailable' }, 503) : json(compareTrace(Number(path.split('/').at(-1)), path.endsWith('301') ? model : undefined, path.endsWith('301') && model.startsWith('mock:') ? 'fallback' : 'ok'))
    if (path === '/api/agent/compare') { if (hold) await new Promise<void>(resolve => { hold = resolve }); return json(status === 200 ? result : { detail: status === 429 ? 'Не больше 20 запросов жюри в минуту' : 'provider unavailable' }, status) }
    throw new Error(`Unexpected API: ${path}`)
  }))
})
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; vi.unstubAllGlobals() })
function show() { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client); return render(<QueryClientProvider client={client}><MemoryRouter><CompareTab /></MemoryRouter></QueryClientProvider>) }
function enter(text = 'Верните комиссию за перевод') { fireEvent.change(screen.getByRole('textbox', { name: 'Текст обращения' }), { target: { value: text } }) }
function send() { fireEvent.click(screen.getByRole('button', { name: 'Сравнить' })) }

it('пять примеров заполняют только вход; active bench_only доступен, inactive скрыт', async () => {
  show(); await screen.findByRole('option', { name: /bench_only_allowed/ })
  expect(screen.queryByRole('option', { name: /inactive/ })).not.toBeInTheDocument()
  const examples = screen.getByRole('region', { name: 'Сложные примеры' })
  expect(within(examples).getAllByRole('button')).toHaveLength(5)
  for (const button of within(examples).getAllByRole('button')) { fireEvent.click(button); expect((screen.getByRole('textbox', { name: 'Текст обращения' }) as HTMLTextAreaElement).value.length).toBeGreaterThan(3) }
  expect(calls.some(call => call.path === '/api/agent/compare')).toBe(false)
  fireEvent.change(screen.getByRole('combobox', { name: 'Профиль для сравнения' }), { target: { value: '9' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Канал' }), { target: { value: 'social' } })
  fireEvent.change(screen.getByRole('textbox', { name: 'Клиент (ID)' }), { target: { value: '42' } }); send()
  await screen.findByRole('region', { name: 'Результаты сравнения' })
  expect(calls.find(call => call.path === '/api/agent/compare')?.body).toMatchObject({ channel_code: 'social', client_id: 42, llm_profile_id: 9 })
})
it('показывает реальные diff, rationale, проценты и оба trace; requested model не считается фактическим', async () => {
  show(); enter(); send()
  await screen.findByText('replay:recorded-test-model')
  expect(screen.getByText('Различий в полях API: 2')).toBeVisible()
  expect(screen.getByText(selectedClassification.rationale_ru)).toBeVisible()
  expect(screen.getByText(mockClassification.rationale_ru)).toBeVisible()
  expect(screen.getByRole('link', { name: 'Открыть прогон #301' })).toHaveAttribute('href', '/engine/301')
  expect(screen.getByRole('link', { name: 'Открыть прогон #302' })).toHaveAttribute('href', '/engine/302')
  const table = screen.getByRole('table', { name: 'Сравнение полей классификации' })
  expect(within(table).getByRole('row', { name: /Риск ухода/ })).toHaveTextContent('82%')
  expect(within(table).getByRole('row', { name: /Уверенность/ })).toHaveTextContent('91%')
  expect(screen.queryByText('requested-test-profile')).not.toBeInTheDocument()
  const body = calls.find(call => call.path === '/api/agent/compare')!.body!
  expect(body).not.toHaveProperty('llm_profile_id'); expect(body).not.toHaveProperty('client_id')
})
it('совпадение не объявляется ценностью модели; источник legacy неизвестен', async () => {
  result = { ...result, mock: result.llm, diff: [] }; model = 'GigaChat-legacy'
  show(); enter(); send(); await screen.findByText('GigaChat-legacy')
  expect(screen.getByText(/не доказывает превосходство/)).toBeVisible()
  expect(within(screen.getByRole('article', { name: 'Выбранный профиль' })).getByText('Источник неизвестен')).toBeVisible()
  expect(screen.queryByText('Различается')).not.toBeInTheDocument()
})
it('mock fallback честно помечен независимо от выбранного профиля', async () => {
  model = 'mock:mock-rules-v1'; show(); enter(); send()
  await waitFor(() => expect(within(screen.getByRole('article', { name: 'Выбранный профиль' })).getByText('Резервный mock')).toBeVisible())
  expect(screen.queryByText('Live')).not.toBeInTheDocument()
  expect(within(screen.getByRole('article', { name: 'Mock — правила' })).queryByText('Резервный mock')).not.toBeInTheDocument()
})
it('границы 3..5000 и positive safe client ID проверяются до запроса', () => {
  show(); enter('аа'); expect(screen.getByRole('button', { name: 'Сравнить' })).toBeDisabled()
  enter('а'.repeat(5000)); expect(screen.getByRole('textbox', { name: 'Текст обращения' })).toHaveAttribute('maxlength', '5000')
  const client = screen.getByRole('textbox', { name: 'Клиент (ID)' })
  for (const value of ['0', '-1', '1.5', '9007199254740992']) { fireEvent.change(client, { target: { value } }); expect(screen.getByRole('button', { name: 'Сравнить' })).toBeDisabled() }
  fireEvent.change(client, { target: { value: '' } }); expect(screen.getByRole('button', { name: 'Сравнить' })).toBeEnabled()
  expect(calls.some(call => call.path === '/api/agent/compare')).toBe(false)
})
it('pending не отправляется повторно, WS/cache invalidation не повторяет действие', async () => {
  hold = () => {}; show(); enter(); send(); await screen.findByRole('status')
  expect(screen.getByRole('button', { name: 'Сравнивается…' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Сравнивается…' })); await clients[0]!.invalidateQueries()
  expect(calls.filter(call => call.path === '/api/agent/compare')).toHaveLength(1)
  hold!(); await screen.findByRole('region', { name: 'Результаты сравнения' })
})
it('429 и сбойtrace видны, ошибка не запускает автоматический повтор', async () => {
  status = 429; show(); enter(); send(); await screen.findByText('Ошибка: Не больше 20 запросов жюри в минуту')
  expect(calls.filter(call => call.path === '/api/agent/compare')).toHaveLength(1)
  expect(screen.queryByRole('region', { name: 'Результаты сравнения' })).not.toBeInTheDocument()
  status = 200; traceError = true; send(); await screen.findByRole('region', { name: 'Результаты сравнения' })
  await waitFor(() => expect(screen.getAllByText('Ошибка: trace unavailable')).toHaveLength(2))
  expect(screen.getByText(selectedClassification.summary_ru)).toBeVisible()
})
it('пустой HTTP200 не маскируется как классификация', async () => {
  result = {}; show(); enter(); send(); await screen.findByText('Ошибка: API не вернул обе классификации.')
  expect(screen.queryByRole('region', { name: 'Результаты сравнения' })).not.toBeInTheDocument()
})
it('английская форма сохраняет язык ответа и очищает старый результат при новом входе', async () => {
  await i18n.changeLanguage('en'); show(); fireEvent.change(screen.getByRole('textbox', { name: 'Message text' }), { target: { value: 'Transfer failed again' } }); fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
  await screen.findByRole('region', { name: 'Comparison results' }); expect(screen.getByText(selectedClassification.rationale_ru)).toBeVisible()
  fireEvent.change(screen.getByRole('textbox', { name: 'Message text' }), { target: { value: 'Another message' } }); expect(screen.queryByRole('region', { name: 'Comparison results' })).not.toBeInTheDocument()
})
it('структурные сравнения и source используют записанные значения', () => {
  expect(stable({ b: 2, a: 1 })).toBe(stable({ a: 1, b: 2 }))
  expect(comparisonFields(selectedClassification, { ...selectedClassification, problem_summary: { suggested_team: 'team_deposits', severity: 'medium', problem: selectedClassification.problem_summary.problem } }).every(field => !field.changed)).toBe(true)
  expect(sourceOf('replay:Recorded')).toBe('replay'); expect(sourceOf('gigachat:Actual')).toBe('live'); expect(sourceOf('openai_compatible:Actual')).toBe('live'); expect(sourceOf('requested_model')).toBe('unknown')
})
