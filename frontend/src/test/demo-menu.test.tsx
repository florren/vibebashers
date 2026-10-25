import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/shared/theme', () => ({
  useTheme: (sel?: (s: { theme: 'light'; toggle: () => void }) => unknown) => {
    const st = { theme: 'light' as const, toggle: vi.fn() }
    return sel ? sel(st) : st
  },
  applyTheme: vi.fn(),
}))

import i18n from '@/shared/i18n'
import { connectWs, WS_TOPIC_QUERY_KEYS } from '@/shared/ws/client'
import { DemoMenu, LONG_PRESS_MS, useDemoMenu } from '@/widgets/DemoMenu'
import { Shell } from '@/widgets/Shell'

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []
  readyState = MockWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor() {
    MockWebSocket.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }
}

function qcWrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function installFetch(extra?: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    if (url.includes('/api/sim/state')) return jsonRes({ running: false, current_run_status: 'none', speed: 1 })
    if (url.includes('/api/sim/runs')) return jsonRes({ items: [] })
    if (url.includes('/api/refs/')) return jsonRes([])
    const custom = extra?.(url, init)
    if (custom) return custom
    return jsonRes({})
  })
}

describe('demo-menu', () => {
  beforeEach(() => {
    useDemoMenu.setState({ open: false })
    MockWebSocket.instances = []
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    installFetch()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('топик demo инвалидирует query key demo-status', async () => {
    expect(WS_TOPIC_QUERY_KEYS.demo).toEqual([['demo-status']])
    vi.useFakeTimers()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const stop = connectWs(qc)
    expect(MockWebSocket.instances).toHaveLength(1)
    const ws = MockWebSocket.instances[0]!
    ws.onmessage?.({
      data: JSON.stringify({ topic: 'demo', type: 'demo.failover', ts: new Date().toISOString(), data: {} }),
    })
    expect(invalidate).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(250)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['demo-status'] })
    stop()
  })

  it('подписи из словаря; dialog после Ctrl+Shift+R', async () => {
    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ llm_mode: 'live', badge_ru: null })
      return undefined
    })
    render(qcWrap(<DemoMenu />))
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.keyDown(window, { key: 'R', ctrlKey: true, shiftKey: true })
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('demoMenu.title'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('demoMenu.llmReplay'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('demoMenu.scenario8'))).toBeInTheDocument()
  })

  it('failover и три play с нужными телами', async () => {
    const calls: { url: string; body?: unknown }[] = []
    installFetch((url, init) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url.includes('/api/demo/status')) return jsonRes({ llm_mode: 'mock' })
      if (url.includes('/api/demo/failover')) return jsonRes({ llm_mode: 'replay' })
      if (url.includes('/api/demo/play/')) return jsonRes({}, 202)
      if (url.includes('/api/sim/baseline/restore')) return jsonRes({}, 202)
      return undefined
    })
    render(qcWrap(<DemoMenu />))
    useDemoMenu.setState({ open: true })
    await screen.findByRole('dialog')

    fireEvent.click(screen.getByText(i18n.t('demoMenu.llmReplay')))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/api/demo/failover') && c.body)).toBe(true))
    expect(calls.find((c) => c.url.includes('/api/demo/failover'))?.body).toEqual({ component: 'llm', to: 'replay' })

    fireEvent.click(screen.getByText(i18n.t('demoMenu.scenario8')))
    await waitFor(() => expect(calls.some((c) => c.url.includes('qr_fee_public_review'))).toBe(true))
    expect(calls.find((c) => c.url.includes('qr_fee_public_review'))?.body).toEqual({ asset_kind: 'post', reset: 'none' })

    fireEvent.click(screen.getByText(i18n.t('demoMenu.scenario9')))
    await waitFor(() => expect(calls.some((c) => c.url.includes('branch_misselling'))).toBe(true))
    expect(calls.find((c) => c.url.includes('branch_misselling'))?.body).toEqual({ asset_kind: 'transcript', reset: 'none' })

    fireEvent.click(screen.getByText(i18n.t('demoMenu.scenario10')))
    await waitFor(() => expect(calls.some((c) => c.url.includes('retail_transcript_red_phrases'))).toBe(true))
    expect(calls.find((c) => c.url.includes('retail_transcript_red_phrases'))?.body).toEqual({
      asset_kind: 'transcript',
      reset: 'none',
    })

    fireEvent.click(screen.getByText(i18n.t('demoMenu.baselineRestore')))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/api/sim/baseline/restore'))).toBe(true))
    const baseline = calls.find((c) => c.url.includes('/api/sim/baseline/restore'))
    expect(baseline?.body).toBeUndefined()
  })

  it('501 показывает Problem', async () => {
    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ llm_mode: 'live' })
      if (url.includes('/api/demo/failover')) return jsonRes({ title: 'Не реализовано', status: 501, card: 'T-195' }, 501)
      return undefined
    })
    render(qcWrap(<DemoMenu />))
    useDemoMenu.setState({ open: true })
    await screen.findByRole('dialog')
    fireEvent.click(screen.getByText(i18n.t('demoMenu.llmMock')))
    expect(await screen.findByText(/T-195/)).toBeInTheDocument()
  })

  it('long-press в Shell: раньше порога open false и нет dialog; дольше — dialog в DOM', async () => {
    vi.useFakeTimers()
    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ badge_ru: null })
      return undefined
    })
    render(qcWrap(<Shell />))
    const logo = screen.getByTestId('app-logo')
    expect(useDemoMenu.getState().open).toBe(false)
    expect(screen.queryByRole('dialog')).toBeNull()

    fireEvent.pointerDown(logo)
    fireEvent.pointerUp(logo)
    expect(useDemoMenu.getState().open).toBe(false)
    expect(screen.queryByRole('dialog')).toBeNull()

    fireEvent.pointerDown(logo)
    await vi.advanceTimersByTimeAsync(LONG_PRESS_MS + 50)
    fireEvent.pointerUp(logo)
    vi.useRealTimers()
    expect(useDemoMenu.getState().open).toBe(true)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('закрытие убирает role=dialog из DOM', async () => {
    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ llm_mode: 'live' })
      return undefined
    })
    render(qcWrap(<DemoMenu />))
    useDemoMenu.setState({ open: true })
    await screen.findByRole('dialog')
    fireEvent.click(screen.getByText(i18n.t('demoMenu.close')))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(useDemoMenu.getState().open).toBe(false)
  })

  it('открытое меню при GET /api/demo/status 501 показывает ErrorBox', async () => {
    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ title: 'Не реализовано', status: 501, card: 'T-195-demo' }, 501)
      return undefined
    })
    render(qcWrap(<DemoMenu />))
    useDemoMenu.setState({ open: true })
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByText(/T-195-demo/)).toBeInTheDocument()
  })

  it('badge_ru в футере Shell; null и 501 — футер пустой', async () => {
    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ badge_ru: 'офлайн-кассета от 20.10' })
      return undefined
    })
    const { unmount } = render(qcWrap(<Shell />))
    expect(await screen.findByTestId('demo-mode-footer')).toHaveTextContent('офлайн-кассета от 20.10')
    unmount()

    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ badge_ru: null })
      return undefined
    })
    const { unmount: u2 } = render(qcWrap(<Shell />))
    await waitFor(() => expect(screen.queryByTestId('demo-mode-footer')).toBeNull())
    u2()

    installFetch((url) => {
      if (url.includes('/api/demo/status')) return jsonRes({ title: 'x', status: 501 }, 501)
      return undefined
    })
    render(qcWrap(<Shell />))
    await waitFor(() => expect(screen.queryByTestId('demo-mode-footer')).toBeNull())
  })
})
