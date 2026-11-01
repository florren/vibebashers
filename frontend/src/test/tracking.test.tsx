import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TrackingPage } from '@/pages/claim/TrackingPage'
import i18n from '@/shared/i18n'

const TOKEN = 'a'.repeat(32)
const TRACK = `/api/public/track/${TOKEN}`
const history = {
  public_id: 'SIG-000123', status_label_ru: 'В работе', can_append: false, question_from_agent: null,
  timeline: [{ step: 'received', done: true, at_sim: '2026-11-01T10:00:00Z' }, { step: 'team_working', done: true }],
  notifications: [{ id: 1, body: 'Мы проверяем ваше обращение', status: 'sent' }],
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
function renderTrack(token = TOKEN) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/track/${token}`]}><Routes><Route path="track/:token" element={<TrackingPage />} /></Routes></MemoryRouter></QueryClientProvider>)
}

describe('public tracking', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('ru')
    focusManager.setFocused(true)
    vi.stubGlobal('fetch', vi.fn(async () => json(history)))
  })
  afterEach(() => {
    vi.useRealTimers()
    focusManager.setFocused(undefined)
  })

  it('shows understandable progress and only delivered messages', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ ...history, notifications: [...history.notifications, { id: 2, body: 'Неотправленный черновик', status: 'queued' }] }))
    renderTrack()
    expect(await screen.findByText('SIG-000123')).toBeVisible()
    expect(screen.getByText(i18n.t('tracking.steps.team_working'))).toBeVisible()
    expect(screen.getByText('Мы проверяем ваше обращение')).toBeVisible()
    expect(screen.queryByText('Неотправленный черновик')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('localizes progress without exposing backend labels or errors', async () => {
    await i18n.changeLanguage('en')
    renderTrack()
    expect(await screen.findByText('Specialists are working on a solution')).toBeVisible()
    expect(screen.queryByText('В работе')).not.toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(TRACK, expect.objectContaining({ headers: expect.objectContaining({ 'Accept-Language': 'en' }) }))
  })

  it('handles an unknown capability without echoing it', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ detail: `private: ${TOKEN}` }, 404))
    renderTrack()
    expect(await screen.findByRole('heading', { name: i18n.t('tracking.notFound') })).toBeVisible()
    expect(screen.queryByText(new RegExp(TOKEN))).not.toBeInTheDocument()
  })

  it('does not query malformed tokens', () => {
    renderTrack('short')
    expect(screen.getByRole('heading', { name: i18n.t('tracking.notFound') })).toBeVisible()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('retries a failed load without exposing technical errors', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json({ detail: 'team_secret / SQL error' }, 503))
    renderTrack()
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('tracking.loadError'))
    expect(screen.queryByText(/team_secret/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: i18n.t('tracking.retry') }))
    expect(await screen.findByText('SIG-000123')).toBeVisible()
  })

  it('keeps an update and its idempotency key after failure, then refreshes on success', async () => {
    const keys: string[] = []
    let posts = 0
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      if (init?.method === 'POST') {
        keys.push(init.headers['Idempotency-Key'])
        expect(JSON.parse(init.body).text).toBe('Сумма операции 450 рублей')
        posts++
        return posts === 1 ? json({ detail: 'temporary' }, 503) : new Response(null, { status: 202 })
      }
      return json({ ...history, can_append: posts < 2, question_from_agent: 'Уточните сумму операции' })
    }))
    renderTrack()
    const input = await screen.findByRole('textbox', { name: i18n.t('tracking.reply') })
    expect(screen.getByText('Уточните сумму операции')).toBeVisible()
    fireEvent.change(input, { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: i18n.t('tracking.send') })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'Сумма операции 450 рублей' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('tracking.send') }))
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('tracking.appendError'))
    expect(input).toHaveValue('Сумма операции 450 рублей')
    fireEvent.click(screen.getByRole('button', { name: i18n.t('tracking.send') }))
    await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument())
    expect(keys[0]).toMatch(/^[a-f0-9-]{36}$/)
    expect(keys[1]).toBe(keys[0])
    expect(screen.getByRole('status')).toHaveTextContent(i18n.t('tracking.appended'))
  })

  it('polls every ten seconds while visible', async () => {
    vi.useFakeTimers()
    renderTrack()
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(fetch).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(9999) })
    expect(fetch).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})
