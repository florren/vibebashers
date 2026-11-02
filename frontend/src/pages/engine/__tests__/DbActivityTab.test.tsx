import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DbActivityTab } from '../DbActivityTab'
import i18n from '@/shared/i18n'
import { TOPICS, WS_TOPIC_QUERY_KEYS, useWs } from '@/shared/ws/client'
import { dbActivity, dbCounters, dbRows } from '@/test/fixtures/dbActivity'

let requests: URL[]
let empty = false
let fail = false
let many = false
let records: Record<string, unknown>[] = dbRows
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
beforeEach(async () => {
  requests = []; empty = false; fail = false; many = false; records = dbRows
  await i18n.changeLanguage('ru')
  useWs.setState({ sim: null, status: 'open', events: [] })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost'); requests.push(url)
    if (url.pathname === '/api/sim/state') return json({ current_run_id: 7 })
    if (url.pathname === '/api/sim/runs') return json({ items: [{ id: 7, label: 'Текущий' }, { id: 6, label: 'Предыдущий' }] })
    if (fail) return json({ detail: 'read unavailable' }, 503)
    if (url.pathname.endsWith('/tables')) return json(dbCounters)
    if (url.pathname.endsWith('/rows')) return json(empty ? [] : records)
    if (url.pathname.endsWith('/activity')) return json(empty ? [] : many && !url.searchParams.has('cursor') ? Array.from({ length: 50 }, (_, i) => ({ ...dbActivity[0], id: 500 - i })) : dbActivity.filter(item => !url.searchParams.get('table') || item.table_name === url.searchParams.get('table')))
    return json({})
  }))
})
afterEach(() => { vi.unstubAllGlobals() })
function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const view = render(<QueryClientProvider client={qc}><DbActivityTab /></QueryClientProvider>)
  return { ...view, qc }
}
it('показывает серверные счётчики, audit chain и инспектор строки', async () => {
  mount()
  expect(await screen.findByText('120')).toBeVisible()
  const feed = screen.getByRole('list', { name: 'Лента изменений' })
  expect(within(feed).getAllByRole('button')).toHaveLength(4)
  fireEvent.click(screen.getByRole('button', { name: /SIG-000017/ }))
  expect(screen.getByRole('region', { name: 'Инспектор JSON' })).toHaveTextContent('external_contact')
  expect(requests.filter(url => url.pathname.includes('/db/')).every(url => url.searchParams.get('run_id') === 'current')).toBe(true)
})
it('фильтрует table/run на сервере и меняет инспектируемую таблицу', async () => {
  mount(); await screen.findByText('120')
  fireEvent.change(screen.getByLabelText('Таблица'), { target: { value: 'incidents' } })
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/activity') && url.searchParams.get('table') === 'incidents')).toBe(true))
  fireEvent.change(screen.getByLabelText('Область запусков'), { target: { value: 'all' } })
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/tables') && url.searchParams.get('run_id') === 'all')).toBe(true))
  expect(screen.queryByRole('region', { name: 'Инспектор JSON' })).not.toBeInTheDocument()
})
it('загружает более ранние реальные страницы с cursor', async () => {
  many = true; mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Более ранние изменения' }))
  await waitFor(() => expect(requests.some(url => url.searchParams.get('cursor') === '451')).toBe(true))
})
it('не выдумывает события и строки при пустом ответе', async () => {
  empty = true; mount()
  expect(await screen.findByText('Изменений в выбранной области пока нет')).toBeVisible()
  expect(screen.getByText('В этой области нет строк')).toBeVisible()
})
it('показывает ошибку и повторяет read по кнопке', async () => {
  fail = true; mount()
  expect((await screen.findAllByText(/read unavailable/)).length).toBeGreaterThan(0)
  fail = false; fireEvent.click(screen.getByRole('button', { name: 'Обновить' }))
  expect(await screen.findByText('120')).toBeVisible()
})
it('pause удерживает снимок при WS invalidation; refresh работает вручную', async () => {
  const { qc } = mount(); await screen.findByText('120')
  fireEvent.click(screen.getByRole('button', { name: 'Приостановить обновление' }))
  const before = requests.length
  await act(async () => { await qc.invalidateQueries({ queryKey: ['db'] }) })
  expect(requests).toHaveLength(before)
  fireEvent.click(screen.getByRole('button', { name: 'Обновить' }))
  await waitFor(() => expect(requests.length).toBeGreaterThan(before))
  expect(TOPICS).toContain('db'); expect(WS_TOPIC_QUERY_KEYS.db).toEqual([['db']])
})
it('локализует экран и честно обозначает polling без WS', async () => {
  await i18n.changeLanguage('en'); useWs.setState({ status: 'closed' }); mount()
  expect(await screen.findByText('Polling · WebSocket unavailable')).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Database activity' })).toBeVisible()
  expect(screen.getByLabelText('Run scope')).toHaveValue('current')
})

it('различает строки incident_signals с составным primary key', async () => {
  records = [{ incident_id: 11, signal_id: 7 }, { incident_id: 11, signal_id: 8 }]
  mount(); await screen.findByText('120')
  fireEvent.change(screen.getByLabelText('Таблица'), { target: { value: 'incident_signals' } })
  expect(await screen.findByRole('button', { name: /#11\/7/ })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /#11\/8/ }))
  expect(screen.getByRole('region', { name: 'Инспектор JSON' })).toHaveTextContent('"signal_id": 8')
})
