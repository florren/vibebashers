import { act, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { getJourney } from '@/shared/api/trace'
import { RecordedJourney } from '../RecordedJourney'
import { recording } from './recordings'

vi.mock('@/shared/api/trace', () => ({ getJourney: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.useRealTimers())
function mount(mode: 'presenter' | 'replay', scenario: 1 | 8 | 11) {
  vi.mocked(getJourney).mockResolvedValue(recording(scenario))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RecordedJourney mode={mode} reference={`SIG-${scenario}`} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return qc
}
it.each([1, 8, 11] as const)('replays scenario %i with pause, rewind, pace and frozen server reads', async (scenario) => {
  const qc = mount('replay', scenario)
  await screen.findByRole('button', { name: 'Воспроизвести' })
  expect(screen.queryByText('Ответ банка')).not.toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  vi.useFakeTimers()
  fireEvent.click(screen.getByRole('button', { name: 'Воспроизвести' }))
  await act(() => vi.advanceTimersByTimeAsync(0))
  expect(screen.getByText(`Сценарий ${scenario}`)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Пауза' }))
  await act(() => vi.advanceTimersByTimeAsync(100000))
  expect(screen.queryByText('Ответ банка')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Вперёд' }))
  fireEvent.click(screen.getByRole('button', { name: 'Вперёд' }))
  expect(screen.getByText('Ответ банка')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
  expect(screen.queryByText('Ответ банка')).not.toBeInTheDocument()
  await act(() => qc.invalidateQueries({ queryKey: ['journey'] }))
  expect(getJourney).toHaveBeenCalledTimes(1)
  expect(getJourney).toHaveBeenCalledWith(`SIG-${scenario}`, 'any', false)
  fireEvent.click(screen.getByRole('button', { name: 'В начало' }))
  fireEvent.change(screen.getByLabelText('Темп'), { target: { value: 'real' } })
  fireEvent.click(screen.getByRole('button', { name: 'Воспроизвести' }))
  await act(() => vi.advanceTimersByTimeAsync(0))
  await act(() => vi.advanceTimersByTimeAsync(59999))
  expect(screen.queryByText('Фактический исход')).not.toBeInTheDocument()
  await act(() => vi.advanceTimersByTimeAsync(1))
  expect(screen.getByText('Фактический исход')).toBeInTheDocument()
})
it.each([1, 8, 11] as const)('presents scenario %i notes, keyboard navigation and block timer without technical controls', async (scenario) => {
  mount('presenter', scenario)
  expect(await screen.findByText(`Тезис сценария ${scenario}`)).toBeInTheDocument()
  expect(getJourney).toHaveBeenCalledWith(`SIG-${scenario}`, 'any', true)
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByText('mock')).not.toBeInTheDocument()
  fireEvent.keyDown(window, { key: 'ArrowRight' })
  expect(screen.getByRole('heading', { name: 'Понимание' })).toBeInTheDocument()
  fireEvent.keyDown(window, { key: 'ArrowLeft' })
  expect(screen.getByRole('heading', { name: 'Поступление' })).toBeInTheDocument()
  fireEvent.keyDown(window, { key: '?' })
  expect(screen.getByRole('note')).toHaveTextContent('Пробел')
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
  vi.useFakeTimers()
  fireEvent.click(screen.getByRole('button', { name: 'Запустить таймер' }))
  act(() => vi.advanceTimersByTime(65000))
  expect(screen.getByRole('timer')).toHaveTextContent('01:05')
  fireEvent.click(screen.getByRole('button', { name: 'Остановить таймер' }))
  act(() => vi.advanceTimersByTime(5000))
  expect(screen.getByRole('timer')).toHaveTextContent('01:05')
  fireEvent.click(screen.getByRole('button', { name: 'Сбросить таймер' }))
  expect(screen.getByRole('timer')).toHaveTextContent('00:00')
})

it('takes a fresh snapshot when the recording is reopened after leaving the mode', async () => {
  vi.mocked(getJourney).mockResolvedValue(recording(8))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = () => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RecordedJourney mode="presenter" reference="SIG-8" />
      </MemoryRouter>
    </QueryClientProvider>
  )
  const first = render(view())
  await screen.findByText('Тезис сценария 8')
  first.unmount()
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
  const updated = recording(8)
  updated.stages[0]!.events[0]!.brief_ru = 'Обновлённая запись'
  vi.mocked(getJourney).mockResolvedValue(updated)
  render(view())
  expect(await screen.findByText('Обновлённая запись')).toBeInTheDocument()
  expect(getJourney).toHaveBeenCalledTimes(2)
})

it('resumes the remaining real interval after pause instead of restarting its clock', async () => {
  mount('replay', 8)
  await screen.findByRole('button', { name: 'Воспроизвести' })
  vi.useFakeTimers()
  fireEvent.change(screen.getByLabelText('Темп'), { target: { value: 'real' } })
  fireEvent.click(screen.getByRole('button', { name: 'Воспроизвести' }))
  await act(() => vi.advanceTimersByTimeAsync(0))
  await act(() => vi.advanceTimersByTimeAsync(30000))
  fireEvent.click(screen.getByRole('button', { name: 'Пауза' }))
  await act(() => vi.advanceTimersByTimeAsync(90000))
  fireEvent.click(screen.getByRole('button', { name: 'Воспроизвести' }))
  await act(() => vi.advanceTimersByTimeAsync(29999))
  expect(screen.queryByText('Фактический исход')).not.toBeInTheDocument()
  await act(() => vi.advanceTimersByTimeAsync(1))
  expect(screen.getByText('Фактический исход')).toBeInTheDocument()
})
