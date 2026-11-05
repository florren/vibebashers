import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { DashboardTab } from '@/pages/workspace/DashboardTab'
import i18n from '@/shared/i18n'

beforeEach(async () => { await i18n.changeLanguage('ru') })
afterEach(() => { vi.unstubAllGlobals() })

function setup(runId: number | null = 17) {
  const requests: URL[] = []
  const mutations: string[] = []
  let finish: ((response: Response) => void) | undefined
  const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    requests.push(url)
    if (init?.method === 'POST') mutations.push(url.pathname)
    if (url.pathname.endsWith('/fact')) {
      if (url.searchParams.get('run_id') === 'all') return new Promise<Response>(resolve => { finish = resolve })
      return json({ assumptions_vs_fact: { detractor_share: { assumed: 0.1, fact: null }, no_return_share: { assumed: 0.5, fact: 0.25 }, retention_factors: {} } })
    }
    if (url.pathname.includes('/refs/')) return json([])
    return json({ calibration_mode: 'manual', groups: [] })
  }))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={qc}><MemoryRouter><DashboardTab runId={runId ?? undefined} /></MemoryRouter></QueryClientProvider>)
  return { ...view, requests, mutations, qc, finishAll: () => finish?.(json({ assumptions_vs_fact: { detractor_share: { assumed: 0.1, fact: null }, no_return_share: { assumed: 0.5, fact: 0.75 }, retention_factors: {} } })) }
}

it.each(['ru', 'en'])('Fact и CSV сохраняют scope текущего запуска (%s)', async lang => {
  await i18n.changeLanguage(lang)
  const { requests, qc } = setup()
  await screen.findByRole('button', { name: i18n.t('dash.fact.show') })
  fireEvent.click(await screen.findByRole('button', { name: i18n.t('dash.fact.show') }))
  const link = await screen.findByRole('link', { name: 'CSV' })
  expect(link).toHaveAttribute('href', '/api/metrics/economics/fact/export?format=csv&run_id=17')
  expect(requests.find(url => url.pathname.endsWith('/fact'))?.searchParams.get('run_id')).toBe('17')
  expect(requests.find(url => url.pathname.endsWith('/economics'))?.searchParams.get('run_id')).toBe('17')
  expect(screen.getByRole('button', { name: i18n.t('dash.fact.apply') })).toBeEnabled()
  qc.clear()
})

it.each(['ru', 'en'])('нет current — нет неявного all или подстановки (%s)', async lang => {
  await i18n.changeLanguage(lang)
  const { requests, qc } = setup(null)
  expect(screen.getByRole('status')).toHaveTextContent(i18n.t('dash.fact.noCurrent'))
  await waitFor(() => expect(requests.some(url => url.pathname.includes('/refs/'))).toBe(true))
  expect(requests.filter(url => url.pathname.startsWith('/api/metrics/'))).toEqual([])
  expect(screen.queryByRole('button', { name: i18n.t('dash.fact.apply') })).not.toBeInTheDocument()
  qc.clear()
})

it.each(['ru', 'en'])('all не показывает старый Fact и не применяет общую историю (%s)', async lang => {
  await i18n.changeLanguage(lang)
  const { requests, mutations, qc, finishAll } = setup()
  fireEvent.click(await screen.findByRole('button', { name: i18n.t('dash.fact.show') }))
  await screen.findByRole('link', { name: 'CSV' })
  fireEvent.click(screen.getByRole('button', { name: i18n.t('dash.window.all') }))
  await waitFor(() => expect(requests.some(url => url.pathname.endsWith('/fact') && url.searchParams.get('run_id') === 'all')).toBe(true))
  expect(screen.queryByRole('link', { name: 'CSV' })).not.toBeInTheDocument()
  finishAll()
  expect(await screen.findByRole('link', { name: 'CSV' })).toHaveAttribute('href', '/api/metrics/economics/fact/export?format=csv&run_id=all')
  const apply = screen.getByRole('button', { name: i18n.t('dash.fact.apply') })
  expect(apply).toBeDisabled()
  expect(apply).toHaveAttribute('title', i18n.t('dash.fact.applyCurrentOnly'))
  fireEvent.click(apply)
  expect(mutations).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: i18n.t('dash.window.run') }))
  expect(await screen.findByRole('link', { name: 'CSV' })).toHaveAttribute('href', '/api/metrics/economics/fact/export?format=csv&run_id=17')
  expect(screen.getByRole('button', { name: i18n.t('dash.fact.apply') })).toBeEnabled()
  qc.clear()
})
