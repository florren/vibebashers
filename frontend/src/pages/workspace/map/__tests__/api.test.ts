import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/shared/api/client'
import { branchAnalyticsOptions, branchDetailOptions, closedDetailsOptions, directSignalCount } from '../api'
import { detail } from './fixtures'
vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
const scope = { run_id: 'current', period: 'week' as const, product_line: 'deposits', region_code: '77' }
const headers = { 'X-Cx-Role': 'product_manager', 'X-Cx-Product-Line': 'deposits' }
beforeEach(() => { vi.mocked(api).mockReset() })
it('passes exact scope/preset, abort signal and15s metrics cache; no invented branch-detail region parameter', async () => {
  vi.mocked(api).mockResolvedValue(detail)
  const signal = new AbortController().signal
  await branchDetailOptions('VSP-0042', scope, headers).queryFn({ signal })
  expect(api).toHaveBeenCalledWith('/api/branches/VSP-0042', { query: { run_id: 'current', period: 'week', product_line: 'deposits' }, headers, signal })
  expect(branchDetailOptions('VSP-0042', scope, headers).staleTime).toBe(15000)
  expect(branchAnalyticsOptions(scope, headers, 50).queryKey).not.toEqual(branchAnalyticsOptions({ ...scope, run_id: 'all' }, headers, 50).queryKey)
})
it('explicit blank scope fails before HTTP rather than falling back to current/all', async () => {
  await expect(closedDetailsOptions(['VSP-0042'], { ...scope, run_id: '' }, headers).queryFn({ signal: new AbortController().signal })).rejects.toMatchObject({ status: 422 })
  expect(api).not.toHaveBeenCalled()
})
it('bounds background detail concurrency and retains failures as unknown without a zero', async () => {
  let active = 0, max = 0
  vi.mocked(api).mockImplementation(async path => {
    active++; max = Math.max(active, max)
    await new Promise(resolve => setTimeout(resolve, 1))
    active--
    if (path.endsWith('bad')) throw new Error('unavailable')
    return detail
  })
  const data = await closedDetailsOptions(['1', '2', '3', '4', '5', 'bad', '7'], scope, headers).queryFn({ signal: new AbortController().signal })
  expect(max).toBe(3)
  expect(data.bad).toEqual({ detail: null, error: expect.any(Error) })
  expect(data['1']?.detail?.signals.total).toBe(2)
})
it('aborted batch cannot launch another chunk or publish stale old-scope results', async () => {
  const controller = new AbortController()
  vi.mocked(api).mockImplementation(async () => { controller.abort(); return detail })
  await expect(closedDetailsOptions(['1','2','3','4'], scope, headers).queryFn({ signal: controller.signal })).rejects.toBeInstanceOf(DOMException)
  expect(api).toHaveBeenCalledTimes(3)
})

it('missing/error/no current is unknown; an actual empty existing run or explicit All can report zero', () => {
  expect(directSignalCount(undefined)).toBeNull()
  expect(directSignalCount({ detail, error: new Error('failed') })).toBeNull()
  expect(directSignalCount({ detail: { ...detail, scope: { ...detail.scope, run_ids: [] } }, error: null })).toBeNull()
  expect(directSignalCount({ detail: { ...detail, signals: { ...detail.signals, total: 0 } }, error: null })).toBe(0)
  expect(directSignalCount({ detail: { ...detail, scope: { ...detail.scope, run_ids: null } }, error: null })).toBe(2)
})
