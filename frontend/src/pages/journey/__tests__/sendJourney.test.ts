import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { post, type Schemas } from '@/shared/api/client'
import { sendJourneyMessage } from '../api'

const body: Schemas['unified_message.schema'] = {
  channel: 'chat', external_id: 'journey-fixed-synthetic', origin: 'jury',
  client: { client_id: null }, text: 'Проверьте тестовый вклад',
  timestamp: '2026-11-05T04:00:00Z', geo: { source: 'none' },
  meta: { journey_execution: { scenario_id: 'deposit_promo_rate', team_outcome: 'failed', emulate_humans: false, auto_advance: true } },
}
beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response(JSON.stringify({ items: [{ signal_id: 23, status: 'accepted' }] }), { status: 202, headers: { 'Content-Type': 'application/json' } }))))
afterEach(() => vi.unstubAllGlobals())
it('marks only the Journey ingest request and preserves its exact local options payload', async () => {
  expect(await sendJourneyMessage(body)).toBe(23)
  const [path, init] = vi.mocked(fetch).mock.calls[0]!
  expect(path).toBe('/api/ingest/messages')
  expect(init?.method).toBe('POST')
  expect(new Headers(init?.headers).get('X-Source-Code')).toBe('journey')
  expect(JSON.parse(String(init?.body))).toEqual(body)
  expect(fetch).toHaveBeenCalledTimes(1)
})
it('retains a followup parent without injecting the local default profile', async () => {
  const followup = { ...body, meta: { parent_signal_id: 19 } }
  await sendJourneyMessage(followup)
  const sent = JSON.parse(String(vi.mocked(fetch).mock.calls[0]![1]?.body))
  expect(sent.meta).toEqual(followup.meta)
  expect(sent.meta).not.toHaveProperty('journey_execution')
})
it.each(['feed', 'sim', 'jury'] as const)('does not add Journey metadata or source marker to unrelated %s ingress', async origin => {
  const unrelated = { ...body, origin, meta: {} }
  await post('/api/ingest/messages', unrelated)
  const [, init] = vi.mocked(fetch).mock.calls[0]!
  expect(new Headers(init?.headers).has('X-Source-Code')).toBe(false)
  expect(JSON.parse(String(init?.body))).toEqual(unrelated)
})
it('propagates a rejected Journey response without retrying or global control writes', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ items: [{ status: 'rejected', error: 'invalid execution' }] }), { status: 202, headers: { 'Content-Type': 'application/json' } }))
  await expect(sendJourneyMessage(body)).rejects.toThrow('invalid execution')
  expect(fetch).toHaveBeenCalledTimes(1)
})
