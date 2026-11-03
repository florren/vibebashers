import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useSearchParams } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { NotificationsTab } from '@/pages/workspace/NotificationsTab'
import i18n from '@/shared/i18n'

beforeEach(async () => { await i18n.changeLanguage('ru') })
afterEach(() => { vi.unstubAllGlobals() })

it.each(['ru', 'en'])('показывает unknown отдельно от sent/failed (%s)', async (lang) => {
  await i18n.changeLanguage(lang)
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [{
    id: 1, recipient_type: 'client', channel_code: 'telegram_bot', status: 'unknown',
    body: 'Synthetic uncertain delivery', sent_at: null, sent_sim: null, external_ref: null,
  }], total: 1 }), { headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('fetch', fetcher)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><NotificationsTab runId={42} /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText(i18n.t('notifStatus.unknown'))).toBeVisible()
  expect(screen.getByText('Synthetic uncertain delivery')).toBeVisible()
  expect(screen.queryByText(i18n.t('notifStatus.sent'))).toBeNull()
  expect(screen.queryByText(i18n.t('notifStatus.failed'))).toBeNull()
  expect(fetcher).toHaveBeenCalledOnce()
  qc.clear()
})

function FilterNavigation() {
  const [params, setParams] = useSearchParams()
  return <><button onClick={() => setParams({ tab: 'notifications', client_id: '18', run_id: '42' })}>Другой клиент</button><output data-testid="location">{params.toString()}</output></>
}

function filteredTab(search: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={['/workspace?' + search]}><FilterNavigation /><NotificationsTab runId={42} /></MemoryRouter></QueryClientProvider>)
  return { ...result, qc }
}
const response = (body: string, id: number) => new Response(JSON.stringify({ items: [{ id, client_id: id, recipient_type: 'client', channel_code: 'email', status: 'sent', body }]}), { headers: { 'content-type': 'application/json' } })

it('передаёт выбранного клиента вместе с run scope и сохраняет его при смене recipient type', async () => {
  const calls: URL[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => { calls.push(new URL(String(input), 'http://localhost')); return response('Только клиент17', 17) }))
  const { qc } = filteredTab('tab=notifications&client_id=17&run_id=42')
  await screen.findByText('Только клиент17')
  expect(calls[0]?.searchParams.get('client_id')).toBe('17')
  expect(calls[0]?.searchParams.get('run_id')).toBe('42')
  fireEvent.click(screen.getByRole('button', { name: 'Клиенту' }))
  await waitFor(() => expect(calls.at(-1)?.searchParams.get('recipient_type')).toBe('client'))
  expect(calls.at(-1)?.searchParams.get('client_id')).toBe('17')
  qc.clear()
})

it('снимает только client filter, сохраняя вкладку и run scope', async () => {
  const calls: URL[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => { calls.push(new URL(String(input), 'http://localhost')); return response('Уведомление', 17) }))
  const { qc } = filteredTab('tab=notifications&client_id=17&run_id=42')
  await screen.findByText('Уведомление')
  fireEvent.click(screen.getByRole('button', { name: 'Снять фильтр по клиенту' }))
  await waitFor(() => expect(calls.at(-1)?.searchParams.has('client_id')).toBe(false))
  expect(screen.getByTestId('location')).toHaveTextContent('tab=notifications&run_id=42')
  expect(calls.at(-1)?.searchParams.get('run_id')).toBe('42')
  qc.clear()
})

it('не показывает уведомления прежнего клиента, пока новый запрос не завершён', async () => {
  let finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const id = new URL(String(input), 'http://localhost').searchParams.get('client_id')
    return id === '18' ? new Promise<Response>(resolve => { finish = resolve }) : response('Прежний клиент17', 17)
  }))
  const { qc } = filteredTab('tab=notifications&client_id=17&run_id=42')
  await screen.findByText('Прежний клиент17')
  fireEvent.click(screen.getByRole('button', { name: 'Другой клиент' }))
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  expect(screen.queryByText('Прежний клиент17')).not.toBeInTheDocument()
  finish(response('Новый клиент18', 18))
  expect(await screen.findByText('Новый клиент18')).toBeVisible()
  expect(screen.queryByText('Прежний клиент17')).not.toBeInTheDocument()
  qc.clear()
})

it.each(['', '0', '-1', '17abc', '1.5', '9007199254740992'])('некорректный client_id=%s не запускает общую выдачу', async raw => {
  const fetcher = vi.fn(async () => response('Чужая выдача', 18))
  vi.stubGlobal('fetch', fetcher)
  const { qc } = filteredTab('tab=notifications&run_id=42&client_id=' + encodeURIComponent(raw))
  expect(await screen.findByRole('alert')).toHaveTextContent('Некорректный идентификатор клиента')
  expect(fetcher).not.toHaveBeenCalled()
  expect(screen.queryByText('Чужая выдача')).not.toBeInTheDocument()
  qc.clear()
})
