import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/shared/theme', () => ({
  useTheme: (sel?: (s: { theme: 'light'; toggle: () => void }) => unknown) => {
    const st = { theme: 'light' as const, toggle: vi.fn() }
    return sel ? sel(st) : st
  },
  applyTheme: vi.fn(),
}))

import { App } from '@/app/App'
import en from '@/shared/i18n/en.json'
import i18n from '@/shared/i18n'
import ru from '@/shared/i18n/ru.json'
import { Shell } from '@/widgets/Shell'
import { ClaimPage } from '@/pages/claim/ClaimPage'

class MockWebSocket {
  static OPEN = 1
  readyState = MockWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor() {
    queueMicrotask(() => this.onopen?.())
  }
}

function leaves(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => leaves(item, prefix ? `${prefix}.${key}` : key))
}

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

describe('claim', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/sim/state')) return jsonRes({ running: false, current_run_status: 'none', speed: 1 })
      if (url.includes('/api/demo/status')) return jsonRes({})
      if (url.includes('/api/public/captcha')) return jsonRes({ id: 'cap-1', question: '2 + 3 = ?' })
      if (url.includes('/api/refs/regions')) return jsonRes([{ code: '01', name_ru: 'Республика Адыгея' }])
      if (url.includes('/api/refs/products')) return jsonRes([{ code: 'debit_card', name_ru: 'Дебетовая карта' }])
      if (url.includes('/api/refs/cities')) return jsonRes([{ id: 2, region_code: '01', name_ru: 'Майкоп' }])
      if (url.includes('/api/refs/')) return jsonRes([])
      if (url.includes('/api/clients')) return jsonRes([])
      return jsonRes({})
    }))
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    window.history.pushState({}, '', '/claim')
  })

  it('ключи en совпадают с блоком claim и nav.claim', () => {
    const ruBlock = { nav: { claim: ru.nav.claim }, claim: ru.claim }
    expect(leaves(en).sort()).toEqual(leaves(ruBlock).sort())
    for (const value of leaves(en).map((key) => key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], en))) {
      expect(typeof value).toBe('string')
      expect(String(value).trim().length).toBeGreaterThan(0)
    }
  })

  it('открывает /claim с текстом из словаря и ссылкой nav.claim', async () => {
    render(<App />)
    expect(await screen.findByRole('heading', { name: i18n.t('claim.title') })).toBeInTheDocument()
    expect(screen.queryByText('claim.title')).toBeNull()
    expect(screen.getByText(i18n.t('claim.fictionalHint'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: i18n.t('nav.claim') })).toHaveAttribute('href', '/claim')
  })

  it('маршрут /claim рендерит форму внутри оболочки', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/claim']}>
          <Routes>
            <Route element={<Shell />}>
              <Route path="claim" element={<ClaimPage />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('heading', { name: i18n.t('claim.title') })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: i18n.t('nav.claim') })).toHaveAttribute('href', '/claim')
  })
})
