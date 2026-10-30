import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { api, post, type Schemas } from '@/shared/api/client'
import { CaseEvidence, EvidencePanel } from './EvidencePanel'

vi.mock('@/shared/api/client', async (original) => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn(), post: vi.fn() }))
const contour = { scope: 'demo', known_risk_rub: 120, risk_total_rub: null, net_rub: null, refund_rub: 450, fine_rub: 0, combined_net_rub: null,
  known_clients: 1, unknown_clients: 1, duplicate_cases: 3, unidentified_cases: 0, qualified_deals: 0, excluded_deals: 1,
  reasons: { missing_score: 1 }, calibration: null, fine_policy: null, case_count: 5 }
const policy: Schemas['FinanceFinePolicy'] = { id: 'demo-fine-v1', scope: 'demo', currency: 'RUB', amount_rub: 50000, unit: 'deal', basis_ref: 'DEMO-NOT-LEGAL-BASIS', business_approval_ref: 'demo-owner', legal_approval_ref: null, effective_from_sim: '2026-10-08T00:00Z', effective_until_sim: '2027-10-08T00:00Z', additive_to_dcltv: true }
const detail: Schemas['FinancialImpactDetail'] = {
  run_id: 42, incident_id: 7, public_id: 'INC-000007', incident_type: 'misselling', product_code: 'debit_card', product_name: 'Карта',
  client_public_id: 'CL-000001', client_segment: 'mass', client_ltv_rub: 1000, status: 'resolved', resolved_sim: '2026-11-09T06:00:00Z',
  missing: false, stale: false, saved_rub: 20, refund_rub: 10, net_rub: 10, calculation: {}, scenario_base_rub: 458.46, fine_eligible: true,
  scenario_saved_rub: 458.46, scenario_net_rub: 448.46, scenario_fine_rub: 0, scenario_with_fine_net_rub: 448.46,
  proof: { risks: [], records: [], alerts: [{ id: 3, decision: 'go', session_ref: 'AS-000003' }], policies: { demo: policy, observed: null } },
}

function mount(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
  return qc
}
beforeEach(() => {
  vi.mocked(api).mockResolvedValue({ run_id: 42, contours: [contour, { ...contour, scope: 'observed', known_risk_rub: 0, known_clients: 0, fine_rub: null }] } as never)
  vi.mocked(post).mockResolvedValue({ id: 1, run_id: 42, replayed: false } as never)
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })

it('показывает контуры рядом, неполный итог неизвестным и повторные кейсы отдельно', async () => {
  mount(<EvidencePanel runId={42} period="live" start="" end="" />)
  expect(await screen.findByText('Демо · синтетическая калибровка')).toBeInTheDocument()
  expect(screen.getByText('Рабочий · допущенные наблюдения')).toBeInTheDocument()
  expect(screen.getAllByText('Недостаточно данных')).toHaveLength(2)
  expect(screen.getAllByText(/повторных кейсов: 3/)).toHaveLength(2)
  expect(screen.getByText(/Известная часть: 120,00/)).toBeInTheDocument()
  expect(screen.getAllByText('Нет согласованной политики штрафов для этого контура.')).toHaveLength(2)
})

it('сохраняет ключ при повторе и создаёт новую версию при изменении доказательства', async () => {
  let seq = 0
  vi.stubGlobal('crypto', { randomUUID: () => `TEST-KEY-${++seq}` })
  mount(<CaseEvidence detail={detail} />)
  fireEvent.click(screen.getByText('Записать доказательство / новую версию'))
  fireEvent.change(screen.getByLabelText('Алерт руководителя'), { target: { value: '3' } })
  fireEvent.change(screen.getByLabelText('Идентификатор сделки (без ПДн)'), { target: { value: 'DEAL-1' } })
  fireEvent.change(screen.getByLabelText('Факт вмешательства (UTC)'), { target: { value: '2026-11-09T04:00' } })
  fireEvent.change(screen.getByLabelText('Завершение процесса сделки (UTC)'), { target: { value: '2026-11-09T05:00' } })
  fireEvent.change(screen.getByLabelText('Ссылка или идентификатор доказательства'), { target: { value: 'DEMO-EVD-1' } })
  fireEvent.change(screen.getByLabelText('Подтверждённый исход'), { target: { value: 'prevented' } })
  fireEvent.click(screen.getByRole('button', { name: 'Записать версию' }))
  await screen.findByRole('status')
  expect(post).toHaveBeenCalledWith('/api/v1/finance/impact/evidence', expect.objectContaining({ incident_id: 7, alert_id: 3, scope: 'demo', intervention_sim: '2026-11-09T04:00:00Z', idempotency_key: 'TEST-KEY-1' }), { run_id: 42 })
  fireEvent.click(screen.getByRole('button', { name: 'Записать версию' }))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  expect(vi.mocked(post).mock.calls[1]?.[1]).toEqual(vi.mocked(post).mock.calls[0]?.[1])
  fireEvent.change(screen.getByLabelText('Подтверждённый исход'), { target: { value: 'unknown' } })
  fireEvent.click(screen.getByRole('button', { name: 'Записать версию' }))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(3))
  expect(vi.mocked(post).mock.calls[2]?.[1]).toMatchObject({ outcome: 'unknown', idempotency_key: 'TEST-KEY-2' })
})

it('не допускает рабочую запись без согласованной политики', async () => {
  mount(<CaseEvidence detail={detail} />)
  fireEvent.click(screen.getByText('Записать доказательство / новую версию'))
  fireEvent.change(screen.getByLabelText('Контур'), { target: { value: 'observed' } })
  expect(screen.getByRole('button', { name: 'Записать версию' })).toBeDisabled()
  expect(screen.getByText('Нет согласованной политики штрафов для этого контура.')).toBeInTheDocument()
  expect(post).not.toHaveBeenCalled()
})


it('передаёт выбор продуктов обоим контурам серверного снимка', async () => {
  mount(<EvidencePanel runId={42} period="live" start="" end="" products={{ mode: 'exclude', codes: ['deposit'] }} />)
  await screen.findByText('Рабочий · допущенные наблюдения')
  expect(api).toHaveBeenCalledWith('/api/v1/finance/impact/assessment', expect.objectContaining({ query: expect.objectContaining({ run_id: 42, product_mode: 'exclude', product_codes: ['deposit'] }) }))
})
