import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, ApiError, type Schemas } from '@/shared/api/client'
import i18n from '@/shared/i18n'
import { useViewPreset } from '@/shared/layout/preset'
import { ReportPage } from '../ReportPage'
import { overview, signal } from './fixtures'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
vi.mock('../ReportChart', () => ({ ReportChart: () => <svg data-testid="report-chart" /> }))
const fixture: Schemas['CabinetReport'] = {
  money_exact: { kpi: { potential_loss_rub: null, prevented_loss_rub: null }, daily: [], monthly: [] },
  lang: 'ru', overview, summary_ru: ['Записанные наблюдения.'], summary: ['Записанные наблюдения.'],
  kpi: [{ code: 'loss', label: 'Сохранённая потеря', value: null, unit: 'RUB', delta: null, verdict: 'нет данных' }],
  charts: [{ code: 'daily', title_insight: 'Разрывы — неизвестные оценки', note: 'Не прогноз.' }],
  previous: { since_sim: overview.scope.since_sim, sim_time: overview.scope.sim_time, signals: 0, note: 'Полнота не подтверждена.' },
  signals: [signal], top_problems: [], attention: [], attention_total: 0, red_phrase_signals: 0, red_phrase_attention: [], red_phrase_action: 'Проверить сигналы',
  method: { formula_ru: [], formula_note: 'Не рассчитано', rules_version: [], rules_note: 'Не записано', app_version: 'test', run_public_id: ['SR-000001'], requested_run: 'current', synthetic: 'Синтетические данные', terms: 'Нет индекса CSI.', generated_sim: overview.scope.sim_time, signal_limit: 10000, byte_limit: 5242880 },
}
let client: QueryClient
beforeEach(async () => {
  localStorage.clear(); useViewPreset.setState({ role: 'cx_lead' }); await i18n.changeLanguage('ru')
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(api).mockReset().mockResolvedValue(fixture)
})
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks() })
function show(path = '/cabinet/deposits/report?period=week&run_id=17') {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/cabinet/:productLine/report" element={<ReportPage />} /></Routes></MemoryRouter></QueryClientProvider>)
}
it('renders three A4 sections, words first, unknown economics and scoped requests', async () => {
  const { container } = show()
  await screen.findByText('Записанные наблюдения.')
  expect(container.querySelectorAll('[data-report-page]')).toHaveLength(3)
  expect(screen.getByText('Сохранённая потеря').parentElement).toHaveTextContent('—')
  expect(container.querySelector('a')).toHaveAttribute('href','/cabinet/deposits?period=week&run_id=17')
  expect(api).toHaveBeenCalledWith('/api/cabinet/report',expect.objectContaining({ query: { product_line: 'deposits', period: 'week', run_id: '17', lang: 'ru' }, signal: expect.any(AbortSignal) }))
  const print = vi.spyOn(window,'print').mockImplementation(() => undefined)
  fireEvent.click(screen.getByRole('button',{ name: 'Сохранить PDF' }))
  expect(print).toHaveBeenCalledOnce()
})
it('passes an unknown explicit binding to server validation and never broadens to bank scope', async () => {
  localStorage.setItem('cx.ui.productLine','missing-direction'); useViewPreset.setState({ role: 'product_manager' })
  vi.mocked(api).mockRejectedValue(new ApiError(403,{ detail: 'Forbidden scope' },'403'))
  const { container } = show()
  await screen.findByText(i18n.t('care.errors.request'))
  expect(container.querySelector('[data-report-page]')).toBeNull()
  expect(api).toHaveBeenCalledWith('/api/cabinet/report', expect.objectContaining({ headers: { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'missing-direction' } }))
  expect(screen.getByRole('button',{ name: 'Сохранить PDF' })).toBeDisabled()
})
it('refetches translated server words and retains selected scope on language change', async () => {
  show(); await screen.findByText('Записанные наблюдения.')
  fireEvent.click(screen.getByRole('button',{ name: 'EN' }))
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/cabinet/report',expect.objectContaining({ query: expect.objectContaining({ lang: 'en', run_id: '17', product_line: 'deposits' }) })))
  expect(screen.getByRole('button',{ name: 'Save PDF' })).toBeInTheDocument()
})

it('uses the lossless decimal string for visible and printed money, independently of legacy numeric approximation', async () => {
  const large = structuredClone(fixture)
  large.kpi[0]!.value = 900719925474099.9
  large.money_exact.kpi.potential_loss_rub = '900719925474099.93'
  vi.mocked(api).mockResolvedValue(large)
  const { container } = show()
  await screen.findByText('Записанные наблюдения.')
  expect(container.querySelector('[data-exact-money]')?.textContent?.replace(/\s/g, '')).toBe('900719925474099,93₽')
})
