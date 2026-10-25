import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/shared/i18n'
import { SetupPage } from '@/pages/setup/SetupPage'

const GIGACHAT_PROFILE = {
  id: 1,
  code: 'gigachat-main',
  provider: 'gigachat',
  model: 'GigaChat',
  role: 'main',
  base_url: 'https://gigachat.devices.sberbank.ru/api/v1',
  is_active: true,
}

const NEW_BASE_URL = 'https://gigachat.devices.sberbank.ru/api/v2'

function qcWrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/setup?step=1']}>
        <Routes>
          <Route path="/setup" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

describe('setup-llm', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('подписи из ru.json; PATCH base_url и «Проверить» с тем же URL', async () => {
    const calls: { url: string; method: string; body?: unknown }[] = []
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url.includes('/api/setup/status')) return jsonRes({ current_step: 1, steps_done: [], completed: false })
      if (url.includes('/api/setup') && method === 'GET') return jsonRes({ llm: {} })
      if (url.includes('/api/settings/env')) return jsonRes({ items: [] })
      if (url.includes('/api/settings/llm-profiles') && method === 'GET') return jsonRes([GIGACHAT_PROFILE])
      if (url.match(/\/api\/settings\/llm-profiles\/\d+$/) && method === 'PATCH') return jsonRes({})
      if (url.includes('/api/setup/test-llm') && method === 'POST') return jsonRes({ ok: true, latency_ms: 42 })
      return jsonRes({})
    })

    render(qcWrap(<SetupPage />))
    await screen.findByText(i18n.t('setup.llm.profiles'))
    await screen.findByDisplayValue(GIGACHAT_PROFILE.base_url)

    expect(screen.getAllByText(i18n.t('setup.llm.baseUrl')).length).toBeGreaterThanOrEqual(1)

    const row = screen.getByText('gigachat-main').closest('tr')
    expect(row).toBeTruthy()
    const urlInput = within(row!).getByDisplayValue(GIGACHAT_PROFILE.base_url)
    fireEvent.change(urlInput, { target: { value: NEW_BASE_URL } })
    fireEvent.click(within(row!).getByText(i18n.t('setup.llm.saveUrl')))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH' && c.url.includes('/api/settings/llm-profiles/1'))).toBe(true),
    )
    const patch = calls.find((c) => c.method === 'PATCH' && c.url.includes('/api/settings/llm-profiles/1'))
    expect(patch?.body).toMatchObject({ base_url: NEW_BASE_URL })

    fireEvent.click(within(row!).getByText(i18n.t('setup.llm.test')))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/api/setup/test-llm'))).toBe(true))
    const testCall = calls.find((c) => c.url.includes('/api/setup/test-llm'))
    expect(testCall?.body).toEqual({
      provider: 'gigachat',
      model: 'GigaChat',
      base_url: NEW_BASE_URL,
    })
  })
})
