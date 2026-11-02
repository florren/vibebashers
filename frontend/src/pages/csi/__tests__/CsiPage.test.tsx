import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api, ApiError } from '@/shared/api/client'
import { assertBlockBudget } from '@/shared/ui/motion'
import { useViewPreset } from '@/shared/layout/preset'
import { CsiPage } from '../CsiPage'
import { snapshot } from './fixtures'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
vi.mock('../Chart', () => ({ CsiChart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }))
let client: QueryClient
beforeEach(async () => {
  localStorage.clear(); await i18n.changeLanguage('ru'); useViewPreset.setState({ role: 'cx_lead' })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(api).mockReset().mockImplementation(async path => {
    if (path === '/api/csi/analytics') return snapshot
    if (path === '/api/branches') return { items: [{ id: 42, code: '0041', city_name: 'Москва' }], next_cursor: null }
    if (path === '/api/refs/regions') return [{ code: '77', name_ru: 'Москва', name_en: 'Moscow' }]
    if (path === '/api/sim/runs') return { items: [{ id: 19, label: 'CSI demo' }] }
    if (path === '/api/cabinet/overview') return { product_lines: [{ code: 'deposits', name_ru: 'Вклады', name_en: 'Deposits' }] }
    throw new Error('Unexpected read: ' + path)
  })
})
afterEach(() => { cleanup(); client.clear() })
function show(path = '/csi?run_id=19') { return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><CsiPage /></MemoryRouter></QueryClientProvider>) }
it('shows all seven functions, truthful unknown sample, and exact scoped CSI/branch links', async () => {
  const { container } = show()
  await screen.findByText('Тестовая жалоба')
  expect(() => assertBlockBudget(container)).not.toThrow()
  expect(container.querySelectorAll('[data-block]')).toHaveLength(9)
  expect(screen.getByText('Источник выборки: смешанный / неизвестен')).toBeVisible()
  expect(screen.queryByText('Демонстрационные данные выборки')).not.toBeInTheDocument()
  expect(container.querySelector('a[href="/trace/csi/CSI-030001?run_id=19"]')).not.toBeNull()
  expect(container.querySelector('a[href="/trace/branch/42?run_id=19"]')).not.toBeNull()
  expect(container.querySelector('a[href="/journey/SIG-000007?run_id=19"]')).not.toBeNull()
  expect(screen.getAllByRole('img')).toHaveLength(6)
  expect(screen.getAllByRole('table').length).toBeGreaterThanOrEqual(4)
  expect(screen.getByText('Жалоб в выборке: Нет данных, визитов: Нет данных, полных когорт: 0')).toBeVisible()
})
it('sends URL scope and changed filters without widening manager binding', async () => {
  localStorage.setItem('cx.ui.productLine', 'deposits'); useViewPreset.setState({ role: 'product_manager' })
  show('/csi?run_id=19&period=week&region_code=77')
  await screen.findByText('Тестовая жалоба')
  fireEvent.change(screen.getByLabelText('ВСП'), { target: { value: '42' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/csi/analytics', expect.objectContaining({ query: expect.objectContaining({ run_id: '19', period: 'week', region_code: '77', branch_id: 42 }), headers: { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'deposits' } })))
  expect(localStorage.getItem('cx.ui.productLine')).toBe('deposits')
  fireEvent.change(screen.getByLabelText('Период'), { target: { value: 'day' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/csi/analytics', expect.objectContaining({ query: expect.objectContaining({ period: 'day', run_id: '19' }) })))
})
it('does not keep a warm snapshot after role changes to a forbidden strict scope', async () => {
  show(); await screen.findByText('Тестовая жалоба')
  const previous = vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async (...args) => {
    if (args[0] === '/api/csi/analytics') throw new ApiError(403, { title: 'Scope forbidden' }, '403 Forbidden')
    return previous(...args)
  })
  act(() => useViewPreset.setState({ role: 'product_manager' }))
  await waitFor(() => expect(screen.queryByText('Тестовая жалоба')).not.toBeInTheDocument())
  expect((await screen.findAllByText('Scope forbidden')).length).toBeGreaterThan(0)
})
it('preserves explicit invalid run for server validation and translates every page key to English', async () => {
  await i18n.changeLanguage('en'); const { container } = show('/csi?run_id=invalid')
  await screen.findByText('CSI complaints')
  expect(api).toHaveBeenCalledWith('/api/csi/analytics', expect.objectContaining({ query: expect.objectContaining({ run_id: 'invalid' }) }))
  expect(container.textContent).not.toContain('csi.')
  expect(screen.getByText('Sample source: mixed / unknown')).toBeVisible()
})

it('rejects an explicit empty run before qs can silently drop it', async () => {
  show('/csi?run_id=')
  expect(await screen.findByText('Явный run_id не может быть пустым. Выберите запуск.')).toBeInTheDocument()
  expect(vi.mocked(api).mock.calls.some(([path]) => path === '/api/csi/analytics')).toBe(false)
})

it('shows explicit IDs outside loaded directory/run pages instead of a misleading All selection', async () => {
  show('/csi?run_id=27&branch_id=315')
  await screen.findByText('Тестовая жалоба')
  expect(screen.getByLabelText('Запуск')).toHaveValue('27')
  expect(screen.getByLabelText('ВСП')).toHaveValue('315')
  expect(screen.getByText('Выбранный ID: 315')).toBeInTheDocument()
  expect(api).toHaveBeenCalledWith('/api/csi/analytics', expect.objectContaining({ query: expect.objectContaining({ run_id: '27', branch_id: 315 }) }))
})
