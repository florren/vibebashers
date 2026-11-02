import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/shared/api/client'
import { useViewPreset } from '@/shared/layout/preset'

const fetcher = vi.fn()
beforeEach(() => { useViewPreset.setState({ role: 'cx_lead' }); fetcher.mockReset().mockImplementation(async () => new Response('{}', { headers: { 'Content-Type': 'application/json' } })); vi.stubGlobal('fetch', fetcher) })
afterEach(() => { useViewPreset.setState({ role: 'cx_lead' }); vi.unstubAllGlobals() })
function actual() { return new Headers(fetcher.mock.calls.at(-1)![1].headers) }
it('leaves the legacy default request unchanged and follows an explicit preset/reset', async () => {
  await api('/unit-read')
  expect(actual().has('X-Cx-Role')).toBe(false)
  useViewPreset.getState().setRole('compliance_officer')
  await api('/unit-read')
  expect(actual().get('X-Cx-Role')).toBe('compliance_officer')
  useViewPreset.getState().setRole('cx_lead')
  await api('/unit-read')
  expect(actual().has('X-Cx-Role')).toBe(false)
})
it.each([
  { 'X-CX-ROLE': 'cx_lead' },
  new Headers({ 'x-cx-role': 'cx_operator' }),
  [['X-Cx-Role', 'bank_head']] as [string, string][],
])('keeps an explicit caller role authoritative regardless of header casing/form', async headers => {
  useViewPreset.getState().setRole('product_manager')
  const expected = new Headers(headers).get('X-Cx-Role')
  await api('/unit-read', { headers })
  expect(actual().get('X-Cx-Role')).toBe(expected)
  expect([...actual()].filter(([key]) => key.toLowerCase() === 'x-cx-role')).toHaveLength(1)
})
it('does not change HITL payload or grant any other preset authority', async () => {
  useViewPreset.getState().setRole('product_manager')
  const body = JSON.stringify({ decision: 'reject', decided_by: 'Fixture label' })
  await api('/unit-read', { method: 'POST', body })
  expect(fetcher.mock.calls[0]![1].body).toBe(body)
  expect(actual().get('X-Cx-Role')).toBe('product_manager')
  expect(actual().has('Authorization')).toBe(false)
})
