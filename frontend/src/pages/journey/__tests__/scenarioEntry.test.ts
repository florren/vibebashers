import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { loadScenarioJourney } from '../api'
import { recording } from './recordings'

beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
afterEach(() => vi.unstubAllGlobals())
it.each([
  [1, 'deposit_promo_rate'],
  [8, 'qr_fee_public_review'],
  [11, 'social_sarcasm_escalation'],
] as const)('opens scenario %i via GET only in its own recorded run', async (n, scenarioId) => {
  vi.mocked(fetch).mockImplementation(
    async (input) =>
      new Response(JSON.stringify(String(input).includes('/api/sim/runs') ? { items: [{ id: 1, scenario_id: scenarioId }] } : recording(n)), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
  )
  expect(await loadScenarioJourney(scenarioId)).toBe(`SIG-00000${n}`)
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true)
  expect(String(vi.mocked(fetch).mock.calls[1]?.[0])).toContain('run_id=1')
})
it('does not open a baseline journey returned instead of the requested scenario', async () => {
  vi.mocked(fetch).mockImplementation(
    async (input) =>
      new Response(JSON.stringify(String(input).includes('/api/sim/runs') ? { items: [{ id: 42, scenario_id: 'deposit_promo_rate' }] } : recording(1)), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
  )
  await expect(loadScenarioJourney('deposit_promo_rate')).rejects.toThrow('Записанный сценарий не найден')
})
it('reports missing scenario without starting a new run', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200, headers: { 'content-type': 'application/json' } }))
  await expect(loadScenarioJourney('deposit_promo_rate')).rejects.toThrow('Записанный сценарий не найден')
  expect(fetch).toHaveBeenCalledTimes(1)
})
