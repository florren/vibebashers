import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi, expect, it } from 'vitest'
import '@/shared/i18n'
import { JourneyPage } from '..'
import type { Journey } from '@/shared/api/trace'

const stages = ['intake', 'understanding', 'identity', 'rules', 'decision', 'action', 'execution', 'client_outcome'] as const
const journey: Journey = {
  subject: { kind: 'signal', ref: 'SIG-1', title_ru: 'Тест' },
  stages: stages.map((stage) => ({
    stage,
    status: stage === 'decision' ? 'waiting_human' : 'pending',
    events:
      stage === 'decision'
        ? [
            {
              id: 'e',
              kind: 'human_request',
              phase: 'after',
              ts_sim: null,
              ts_real: '2026-10-01T10:00:00Z',
              actor: { kind: 'human', label_ru: 'Человек' },
              title_ru: 'Запрошено решение',
              brief_ru: 'Нужна проверка',
              key_facts: [],
              badges: { llm_source: 'mock' },
              links: {},
              importance: 'key',
              run_id: 'SR-1',
            },
          ]
        : [],
  })),
  client_lane: [],
  summary: { outcome_ru: 'Обработка продолжается', llm_source: 'mock' },
}
vi.mock('@/shared/api/trace', () => ({ getJourney: vi.fn(async () => journey) }))
it('renders eight stages, expands waiting stage, timer, customer placeholder and summary', async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/journey/SIG-1']}>
        <Routes>
          <Route path="/journey/:ref" element={<JourneyPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText(/Запрошено решение/)).toBeInTheDocument()
  expect(screen.getAllByRole('listitem')).toHaveLength(8)
  expect(screen.getByRole('timer')).toHaveTextContent('Ожидаем решения человека:')
  expect(screen.getByText(/Запрошено решение/).closest('details')).toHaveAttribute('open')
  expect(screen.getByText('Здесь появится дорожка клиента.')).toBeInTheDocument()
  expect(screen.getByText('Обработка продолжается')).toBeInTheDocument()
})
