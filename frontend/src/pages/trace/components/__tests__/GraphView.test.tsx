import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { getTrace, getTraceRelations } from '@/shared/api/trace'
import { TracePage } from '../..'
import { fanFixture, traceFixture } from './fixtures'

vi.mock('@/shared/api/trace', () => ({ getTrace: vi.fn(), getTraceRelations: vi.fn(), searchObjects: vi.fn(async () => ({ hits: [] })) }))
function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output> }
function mount(url = '/trace/incident/INC-000001?mode=graph') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[url]}><Routes><Route path="/trace/:kind/:ref" element={<><TracePage /><Location /></>} /></Routes></MemoryRouter></QueryClientProvider>)
}
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0))
  HTMLElement.prototype.scrollTo = function (options) {
    if (typeof options === 'object') { this.scrollLeft = options.left ?? 0; this.scrollTop = options.top ?? 0 }
  }
  vi.mocked(getTrace).mockImplementation(async (kind, ref) => kind === 'incident' ? traceFixture() : { ...traceFixture(), subject: { kind, ref, title_ru: ref }, groups: [] })
  vi.mocked(getTraceRelations).mockImplementation(async (_kind, _ref, query) => fanFixture(query.cursor ? Number(query.cursor.split('-').at(-1)) : 0))
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })

it('defaults graph to current, retains columns, supports explicit all and numeric run scope', async () => {
  mount()
  expect(await screen.findByTestId('trace-graph')).toBeInTheDocument()
  expect(getTrace).toHaveBeenLastCalledWith('incident', 'INC-000001', { run_id: 'current', include: 'key' })
  const scope = screen.getByRole('textbox', { name: 'Запуск' })
  fireEvent.change(scope, { target: { value: 'all' } }); fireEvent.click(screen.getByRole('button', { name: 'Применить' }))
  await waitFor(() => expect(getTrace).toHaveBeenLastCalledWith('incident', 'INC-000001', { run_id: 'all', include: 'key' }))
  expect(screen.getByTestId('location')).toHaveTextContent('run_id=all')
  fireEvent.change(screen.getByRole('textbox', { name: 'Запуск' }), { target: { value: '27' } }); fireEvent.click(screen.getByRole('button', { name: 'Применить' }))
  await waitFor(() => expect(getTrace).toHaveBeenLastCalledWith('incident', 'INC-000001', { run_id: '27', include: 'key' }))
  fireEvent.click(screen.getByRole('button', { name: 'Колонки' }))
  await waitFor(() => expect(screen.queryByTestId('trace-graph')).not.toBeInTheDocument())
  expect(screen.getByRole('checkbox', { name: 'Только ключевые события' })).toBeChecked()
  expect(getTrace).toHaveBeenLastCalledWith('incident', 'INC-000001', { run_id: '27' })
})
it('retains legacy default all and safely ignores unknown modes', async () => {
  mount('/trace/incident/INC-000001?mode=unknown')
  expect(await screen.findByText('Инцидент проверки графа', { selector: 'h3' })).toBeInTheDocument()
  expect(getTrace).toHaveBeenCalledWith('incident', 'INC-000001', { run_id: 'all' })
  expect(screen.queryByTestId('trace-graph')).not.toBeInTheDocument()
})
it('pages through all 1001 real-shaped DTO members without retaining all pages in DOM', async () => {
  mount('/trace/incident/INC-000001?mode=graph&run_id=27')
  fireEvent.click(await screen.findByRole('button', { name: /1001/ }))
  expect(await screen.findByText('События 1–50 из 1001')).toBeInTheDocument()
  expect(getTraceRelations).toHaveBeenLastCalledWith('incident', 'INC-000001', { direction: 'after', event_kind: 'notification', run_id: '27', limit: 50 })
  for (let page = 1; page <= 20; page++) {
    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }))
    await screen.findByText(`События ${page * 50 + 1}–${Math.min(page * 50 + 50, 1001)} из 1001`)
  }
  expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'NTF-001001' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'NTF-000951' })).not.toBeInTheDocument()
  expect(getTraceRelations).toHaveBeenCalledTimes(21)
  fireEvent.click(screen.getByRole('button', { name: 'Предыдущая страница' }))
  expect(await screen.findByText('События 951–1000 из 1001')).toBeInTheDocument()
// 21 sequential page renders share CPU with the full suite; browser pan has its own strict budget.
}, 15000)
it('keyboard selects, announces inspector data and centers real trace links with preserved URL scope', async () => {
  mount('/trace/incident/INC-000001?mode=graph&run_id=27')
  const subject = await screen.findByRole('button', { name: /Инцидент: Инцидент проверки графа/ })
  fireEvent.keyDown(subject, { key: 'End' })
  await waitFor(() => expect(screen.getByRole('button', { name: /Сообщение: Сообщение 4/ })).toHaveFocus())
  expect(screen.getByTestId('location')).toHaveTextContent('focus=EVT-notification%3A4')
  fireEvent.keyDown(screen.getByRole('button', { name: /Сообщение: Сообщение 4/ }), { key: 'Enter' })
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/trace/notification/NTF-000004?mode=graph&run_id=27'))
})
it('shows pagination errors without inventing members and refuses expansion of legacy groups', async () => {
  vi.mocked(getTraceRelations).mockRejectedValue(new Error('synthetic transport failure'))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /1001/ }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось раскрыть группу')
  expect(screen.queryByRole('button', { name: 'Следующая страница' })).not.toBeInTheDocument()
  cleanup()
  vi.mocked(getTrace).mockResolvedValue({ ...traceFixture(), groups: [{ kind: 'notification', count: 1001, sample_refs: ['NTF-000001'] }] })
  mount()
  expect(await screen.findByRole('button', { name: /1001/ })).toBeDisabled()
  expect(screen.getByText(/Для старой группы доступны только примеры/)).toBeInTheDocument()
})
