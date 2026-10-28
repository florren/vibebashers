import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { vi, expect, it } from 'vitest'
import '@/shared/i18n'
import { GlobalSearch } from '../GlobalSearch'
import { IdLink } from '../IdLink'

vi.mock('@/shared/api/trace', () => ({
  searchObjects: vi.fn(async () => ({
    query: '1',
    parsed: { mode: 'id', kind: 'number' },
    hits: [
      { kind: 'signal', ref: 'SIG-000001', title_ru: 'Первый сигнал', run_id: 'SR-0001', trace_href: '/trace/signal/SIG-000001' },
      { kind: 'incident', ref: 'INC-000001', title_ru: 'Инцидент', run_id: 'SR-0001', trace_href: '/trace/incident/INC-000001' },
    ],
    counts_by_kind: { signal: 1, incident: 1 },
    took_ms: 1,
  })),
}))
function Location() {
  return <output>{useLocation().pathname}</output>
}
it('opens with Ctrl+K, selects ambiguous candidate using keyboard and navigates', async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <GlobalSearch />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
  const input = screen.getByRole('combobox')
  expect(input).toHaveFocus()
  fireEvent.change(input, { target: { value: '1' } })
  expect(await screen.findByText('Номер подходит нескольким объектам — выберите нужный тип.')).toBeInTheDocument()
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('/trace/incident/INC-000001'))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
it('opens with slash outside inputs and Escape restores focus', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <GlobalSearch />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.keyDown(window, { key: '/' })
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
it('IdLink navigates to the trace and reports clipboard failure', async () => {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
  })
  render(
    <MemoryRouter>
      <IdLink kind="signal" value="SIG-000001" />
    </MemoryRouter>,
  )
  expect(screen.getByRole('link')).toHaveAttribute('href', '/trace/signal/SIG-000001')
  fireEvent.click(screen.getByRole('button'))
  expect(await screen.findByText('Не удалось скопировать')).toBeInTheDocument()
})
