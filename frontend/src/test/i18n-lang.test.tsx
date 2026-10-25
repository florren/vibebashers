import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/shared/theme', () => ({
  useTheme: () => ({ theme: 'light' as const, toggle: vi.fn() }),
  applyTheme: vi.fn(),
}))

vi.mock('@/shared/api/hooks', () => ({
  useSimState: () => ({ data: undefined }),
  useSimControl: () => ({ mutate: vi.fn(), isPending: false }),
  useRefs: () => ({ data: [] }),
  useClients: () => ({ data: [] }),
  useJury: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false }),
}))

import i18n from '@/shared/i18n'
import { Header } from '@/widgets/Header'

const RAW_KEY = /\b[a-z]+(\.[a-zA-Z_]+){1,3}\b/

function renderHeader() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(['sim-state'], { running: false, current_run_status: 'none', speed: 1 })
  qc.setQueryData(['refs', 'channels'], [])
  qc.setQueryData(['refs', 'segments'], [])
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Header />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('i18n language', () => {
  beforeEach(async () => {
    const bag = new Map<string, string>()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (key: string) => bag.get(key) ?? null,
        setItem: (key: string, value: string) => {
          bag.set(key, value)
        },
        removeItem: (key: string) => {
          bag.delete(key)
        },
        clear: () => {
          bag.clear()
        },
        key: () => null,
        length: 0,
      },
    })
    await i18n.changeLanguage('ru')
  })

  afterEach(async () => {
    await i18n.changeLanguage('ru')
  })

  it('шапка переключает язык на английский nav без сырого ключа', async () => {
    renderHeader()
    expect(screen.getByRole('link', { name: 'Рабочее место' })).toBeInTheDocument()
    expect(screen.getByText('Симуляция')).toBeInTheDocument()
    const lang = screen.getByRole('button', { name: 'Язык' })
    expect(lang).toHaveTextContent('EN')
    fireEvent.click(lang)
    expect(await screen.findByRole('link', { name: 'Workspace' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Language' })).toHaveTextContent('RU')
    expect(screen.getByText('Simulation')).toBeInTheDocument()
    expect(screen.queryByText('nav.workspace')).toBeNull()
    const suspicious = (document.body.textContent ?? '')
      .split(/\s+/)
      .filter((w) => RAW_KEY.test(w) && !w.includes('@') && !/\d/.test(w) && !w.includes('/') && !w.startsWith('http'))
    expect(suspicious).toEqual([])
    expect(document.documentElement.lang).toBe('en')
    expect(window.localStorage.getItem('cx.lang')).toBe('en')
  })
})
