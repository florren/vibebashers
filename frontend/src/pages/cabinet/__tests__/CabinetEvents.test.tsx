import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useWs } from '@/shared/ws/client'
import { useCabinetEvents } from '../api'

let client: QueryClient
beforeEach(() => { vi.useFakeTimers(); client = new QueryClient(); useWs.setState({ events: [], seq: 0 }) })
afterEach(() => { cleanup(); client.clear(); vi.useRealTimers() })
function mount() { return renderHook(useCabinetEvents, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> }) }
it('coalesces real WS invalidations and never projects foreign event payload into the cabinet', async () => {
  const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()
  mount()
  act(() => { for (const topic of ['signals', 'incidents', 'runs']) useWs.getState().push({ topic, type: 'changed', ts: '2026-11-09T06:00:00Z', data: { foreign_payload: 'not a DTO' } }) })
  expect(invalidate).not.toHaveBeenCalled()
  await act(() => vi.advanceTimersByTimeAsync(500))
  expect(invalidate).toHaveBeenCalledTimes(1)
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['cabinet'] })
})
it('ignores unrelated topics and cancels a pending refresh on unmount', async () => {
  const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()
  const { unmount } = mount()
  act(() => useWs.getState().push({ topic: 'bench', type: 'changed', ts: '', data: {} }))
  await act(() => vi.advanceTimersByTimeAsync(500))
  expect(invalidate).not.toHaveBeenCalled()
  act(() => useWs.getState().push({ topic: 'signals', type: 'changed', ts: '', data: {} }))
  unmount(); await act(() => vi.advanceTimersByTimeAsync(500))
  expect(invalidate).not.toHaveBeenCalled()
})
