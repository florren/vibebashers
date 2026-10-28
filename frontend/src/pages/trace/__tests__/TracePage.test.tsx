import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi, expect, it } from 'vitest'
import '@/shared/i18n'
import { TracePage } from '..'
import type { Trace, TraceEvent } from '@/shared/api/trace'
import { eventIcon } from '../components/eventIcon'

const event: TraceEvent = {
  id: 'EVT-1',
  kind: 'refund',
  phase: 'after',
  ts_real: '2026-10-01T10:00:00Z',
  ts_sim: null,
  actor: { kind: 'agent', label_ru: 'Агент' },
  title_ru: 'Возврат выполнен',
  brief_ru: 'Комиссия возвращена',
  key_facts: [],
  badges: { amount_rub: 450, llm_source: 'replay' },
  links: { trace: '/trace/ledger/LED-1' },
  importance: 'key',
  run_id: 'SR-0001',
}
const trace: Trace = {
  subject: { kind: 'signal', ref: 'SIG-000001', title_ru: 'Комиссия' },
  before: [],
  after: [event, { ...event, id: 'EVT-2', importance: 'detail', title_ru: 'Подробность' }],
  edges: [],
  groups: [{ kind: 'signal_created', count: 120, sample_refs: ['SIG-000002'] }],
  pending: [{ kind_ru: 'Ожидаем человека', due_sim: null }],
  terminal: { reached: true, outcome_ru: 'Готово' },
  stats: { before_count: 0, after_count: 2, build_ms: 1 },
}
vi.mock('@/shared/api/trace', () => ({
  getTrace: vi.fn(async () => trace),
  searchObjects: vi.fn(async () => ({ query: '', parsed: { mode: 'text' }, hits: [], counts_by_kind: {}, took_ms: 0 })),
}))
it('renders zones, key filter, fanout, pending and event details', async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/trace/signal/SIG-000001']}>
        <Routes>
          <Route path="/trace/:kind/:ref" element={<TracePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText(/Возврат выполнен/)).toBeInTheDocument()
  expect(screen.queryByText(/Подробность/)).not.toBeInTheDocument()
  expect(screen.getByText('Ожидаем человека', { exact: false })).toBeInTheDocument()
  expect(screen.getByText('+120', { exact: false })).toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Только ключевые события'))
  expect(screen.getByText(/Подробность/)).toBeInTheDocument()
  fireEvent.click(screen.getByText(/Возврат выполнен/))
  expect(await screen.findByRole('dialog', { name: 'Событие' })).toBeInTheDocument()
  expect(screen.getByText('Центрировать на нём')).toHaveAttribute('href', '/trace/ledger/LED-1')
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})
it('formats all demo event families through the exhaustive contract switch', () => {
  for (const kind of ['signal_created', 'incident_created', 'human_decision', 'notification', 'refund', 'decision'] as const)
    expect(eventIcon(kind)).toBeTruthy()
})
