import { afterEach, expect, it, vi } from 'vitest'
import { getJourney } from '@/shared/api/trace'
import { scopedJourneyHref } from '../api'
afterEach(() => vi.unstubAllGlobals())
it('finds the latest manual case outside current World after reopening Journey', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })))
  for (const [origin, expected] of [['jury', 'all'], ['sim', 'current'], ['feed', 'current']] as const) {
    await getJourney(undefined, origin)
    const url = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), 'http://cx.local')
    expect(url.searchParams.get('run_id')).toBe(expected)
    expect(url.searchParams.get('origin')).toBe(origin)
  }
})
it('sends explicit run including invalid input without widening legacy defaults', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })))
  for (const runId of ['19', 'all', 'invalid']) {
    await getJourney('SIG-000001', 'any', true, runId)
    const url = String(vi.mocked(fetch).mock.calls.at(-1)![0])
    expect(new URL(url, 'http://cx.local').searchParams.get('run_id')).toBe(runId)
  }
  const calls = vi.mocked(fetch).mock.calls.length
  await expect(getJourney('SIG-000001', 'any', false, '')).rejects.toThrow()
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(calls)
})
it('replaces an existing run and preserves query/hash; absent scope preserves the href', () => {
  expect(scopedJourneyHref('/trace/signal/SIG-1?run_id=all&phase=after#step', '19')).toBe('/trace/signal/SIG-1?run_id=19&phase=after#step')
  expect(scopedJourneyHref('/engine/3?node=classify', '19')).toBe('/engine/3?node=classify&run_id=19')
  expect(scopedJourneyHref('/journey/SIG-1')).toBe('/journey/SIG-1')
})
