import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api, patch, ApiError } from '@/shared/api/client'
import { useViewPreset } from '@/shared/layout/preset'
import { useUiTheme } from '@/shared/theming/store'
import { useUndo } from '@/shared/ui/undo'
import { assertBlockBudget } from '@/shared/ui/motion'
import { CabinetPage } from '../CabinetPage'
import { overview, signal } from './fixtures'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn(), patch: vi.fn() }))
vi.mock('../CabinetChart', () => ({ CabinetChart: () => <div data-testid="chart">SVG chart tested separately</div> }))
let failure = false
let client: QueryClient
beforeEach(async () => {
  failure = false; localStorage.clear(); await i18n.changeLanguage('ru')
  useViewPreset.setState({ role: 'cx_lead', demonstrator: false })
  useUiTheme.setState({ simTime: overview.scope.sim_time })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(patch).mockReset().mockResolvedValue(undefined)
  vi.mocked(api).mockReset().mockImplementation(async path => {
    if (path === '/api/cabinet/overview') { if (failure) throw new ApiError(403, { title: 'Scope forbidden' }, '403 Forbidden'); return overview }
    if (path === '/api/cabinet/signals') return { items: [signal], total: 1, next_offset: null }
    if (path === '/api/roles') return { default_role: 'cx_lead', items: [{ code: 'cx_lead', name_ru: 'Руководитель CX', name_en: 'CX lead', scope: 'all', default_red_words: false }, { code: 'product_manager', name_ru: 'Менеджер продукта', name_en: 'Product manager', scope: 'one', default_red_words: false }, { code: 'compliance_officer', name_ru: 'Комплаенс-офицер', name_en: 'Compliance officer', scope: 'all', default_red_words: true }] }
    if (path === '/api/sim/runs') return { items: [] }
    if (path === '/api/settings') return { sla_warn_hours: 4 }
    if (path === '/api/refs/channels') return [{ code: 'review_portal', name_ru: 'Отзывы', name_en: 'Reviews' }]
    if (path === '/api/metrics/economics/preview') return { affected_count: 2, rate_code: 'deposit', rate_rub: 961, potential_loss_rub: 123.45, premium_addon_rub: 0, detractor_share: .1, no_return_share: .5 }
    if (path === '/api/settings/economics') return { detractor_share: .1, no_return_share: .5, rates: [{ code: 'deposit', name_ru: 'Вклады', name_en: 'Deposits', rate_rub: 961 }] }
    throw new Error(`Unmocked unit endpoint: ${path}`)
  })
})
afterEach(() => { cleanup(); client.clear(); useUndo.getState().dismiss() })
function show(entry = '/cabinet?period=week&run_id=current') {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/cabinet" element={<CabinetPage />} /><Route path="/cabinet/:productLine" element={<CabinetPage />} /></Routes></MemoryRouter></QueryClientProvider>)
}
it('shows seven real blocks, NULL coverage, red words, scoped trace IDs and Moscow SLA', async () => {
  const { container } = show()
  await screen.findByText('Главное за период')
  expect(() => assertBlockBudget(container.querySelector('[data-cabinet]')!)).not.toThrow()
  expect(container.querySelectorAll('[data-cabinet] [data-block]')).toHaveLength(7)
  expect(screen.getByText(/сохранённая экономика: 0 из 1/)).toBeInTheDocument()
  expect(container.querySelector('[data-block="cabinet-kpi"]')).toHaveTextContent('—')
  expect(container.querySelector('li.border-l-\\[4px\\]')).not.toBeNull()
  expect(screen.getAllByText('Отзывы клиентов').length).toBeGreaterThan(0)
  expect(screen.getByText('Срок через 3 ч')).toBeInTheDocument()
  expect(container.querySelector('a[href="/trace/signal/SIG-000007?run_id=current"]')).not.toBeNull()
})
it('sends filters, preserves run scope and offers local reset Undo', async () => {
  show('/cabinet?period=month&run_id=19&channel=review_portal')
  await screen.findByText('Главное за период')
  fireEvent.change(screen.getByLabelText('Сортировка'), { target: { value: 'level' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/cabinet/signals', expect.objectContaining({ query: expect.objectContaining({ run_id: '19', period: 'month', sort: 'level', channel: 'review_portal' }) })))
  fireEvent.click(screen.getByText('Сбросить фильтры'))
  await waitFor(() => expect(screen.getByLabelText('Канал')).toHaveValue(''))
  act(() => useUndo.getState().undo())
  await waitFor(() => expect(screen.getByLabelText('Канал')).toHaveValue('review_portal'))
})
it('persists visibility using a narrow server patch and sends the selected preset', async () => {
  show('/cabinet/deposits')
  await screen.findByText('Главное за период')
  fireEvent.change(screen.getByLabelText('Видимость'), { target: { value: 'strict' } })
  await waitFor(() => expect(patch).toHaveBeenCalledWith('/api/settings', { cabinet: { visibility: 'strict' } }))
  fireEvent.change(screen.getByLabelText('Пресет роли'), { target: { value: 'product_manager' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/cabinet/overview', expect.objectContaining({ headers: { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'deposits' } })))
})
it('opens a read-only signal drawer and preloads selected-region data', async () => {
  show()
  await screen.findByText('Главное за период')
  fireEvent.click(screen.getByText('Открыть карточку'))
  const drawer = screen.getByRole('dialog', { name: 'Сигнал клиента' })
  expect(within(drawer).getByText('CL-000002')).toBeInTheDocument()
  expect(within(drawer).queryByRole('textbox')).toBeNull()
  const region = screen.getByRole('button', { name: /Москва:.*2/ })
  fireEvent.focus(region)
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/cabinet/signals', expect.objectContaining({ query: expect.objectContaining({ region: '77' }) })))
})
it('keeps a strict error visible and never fabricates KPI zeros', async () => {
  failure = true; const { container } = show('/cabinet/deposits')
  await screen.findByText(i18n.t('care.errors.request'))
  expect(container.querySelector('[data-block="cabinet-kpi"]')).toBeNull()
})

it('restores the full local role/filter/presenter snapshot with Undo', async () => {
  useViewPreset.setState({ demonstrator: true })
  show('/cabinet?region=77')
  await screen.findByText('Главное за период')
  fireEvent.change(screen.getByLabelText('Пресет роли'), { target: { value: 'compliance_officer' } })
  await screen.findByText(/Пресет комплаенса/)
  act(() => useUndo.getState().undo())
  expect(useViewPreset.getState().role).toBe('cx_lead')
  expect(useViewPreset.getState().demonstrator).toBe(true)
  expect(screen.queryByText(/Пресет комплаенса/)).not.toBeInTheDocument()
  expect(screen.getByLabelText('Регион')).toHaveValue('77')
  expect(localStorage.getItem('cx.ui.productLine')).toBeNull()
})

it('keeps the first useful snapshot through a rapid second reset and rejects an old restore after run change', async () => {
  show('/cabinet?run_id=19&channel=review_portal')
  await screen.findByText('Главное за период')
  fireEvent.click(screen.getByText('Сбросить фильтры'))
  await waitFor(() => expect(screen.getByLabelText('Канал')).toHaveValue(''))
  fireEvent.click(screen.getByText('Сбросить фильтры'))
  act(() => useUndo.getState().undo())
  await waitFor(() => expect(screen.getByLabelText('Канал')).toHaveValue('review_portal'))
  fireEvent.click(screen.getByText('Сбросить фильтры'))
  const stale = useUndo.getState().entry!.restore
  fireEvent.change(screen.getByLabelText('Запуск'), { target: { value: 'all' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/cabinet/overview', expect.objectContaining({ query: expect.objectContaining({ run_id: 'all' }) })))
  act(stale)
  expect(screen.getByLabelText('Запуск')).toHaveValue('all')
  expect(screen.getByLabelText('Канал')).toHaveValue('')
})

it('never invents an own product line from the first catalog item when a manager preset is unbound', async () => {
  show('/cabinet')
  await screen.findByText('Главное за период')
  fireEvent.change(screen.getByLabelText('Пресет роли'), { target: { value: 'product_manager' } })
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/cabinet/overview', expect.objectContaining({ headers: { 'X-Cx-Role': 'product_manager' } })))
  expect(localStorage.getItem('cx.ui.productLine')).toBeNull()
  expect(screen.getByLabelText('Направление менеджера (код)')).toBeVisible()
})

it('mounts the calculator outside hover-transformed cards so fixed bounds belong to the viewport', async () => {
  show('/cabinet/deposits')
  await screen.findByText('Главное за период')
  fireEvent.click(screen.getByRole('button', { name: 'Открыть калькулятор' }))
  const drawer = screen.getByRole('dialog', { name: 'Калькулятор потерь' })
  expect(drawer.closest('.card')).toBeNull()
  expect(await within(drawer).findByLabelText('Пострадавшие')).toBeInTheDocument()
})
