import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../client'
import { useEconomicsPreview, type EconomicsPreviewInput } from '../useEconomicsPreview'

vi.mock('../client', async original => ({ ...await original<typeof import('../client')>(), api: vi.fn() }))
afterEach(() => { cleanup(); vi.mocked(api).mockReset() })
function setup(input: EconomicsPreviewInput | null, scopeKey: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return renderHook(({ input, scopeKey }) => useEconomicsPreview(input, scopeKey), { wrapper, initialProps: { input, scopeKey } })
}
it('does not send an unknown cohort but sends known zero explicitly to the server', async () => {
  vi.mocked(api).mockResolvedValue({ potential_loss_rub: 0, rate_code: 'deposit' })
  const hook = setup(null, 'current/deposits/month')
  expect(api).not.toHaveBeenCalled()
  hook.rerender({ input: { affected: 0, rate_code: 'deposit', detractor_share: .1, no_return_share: .5 }, scopeKey: 'current/deposits/month' })
  await waitFor(() => expect(hook.result.current.data?.potential_loss_rub).toBe(0))
  expect(api).toHaveBeenCalledWith('/api/metrics/economics/preview', expect.objectContaining({ query: expect.objectContaining({ affected: 0 }), signal: expect.any(AbortSignal) }))
})
it('aborts the old scope and never shows its late response as the new calculation', async () => {
  let first: ((value: unknown) => void) | undefined
  let second: ((value: unknown) => void) | undefined
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { first = resolve })).mockImplementationOnce(() => new Promise(resolve => { second = resolve }))
  const hook = setup({ affected: 2, rate_code: 'deposit' }, 'run1/deposits/week')
  await waitFor(() => expect(api).toHaveBeenCalledTimes(1))
  const signal = vi.mocked(api).mock.calls[0]![1]!.signal!
  hook.rerender({ input: { affected: 3, rate_code: 'deposit' }, scopeKey: 'run2/deposits/month' })
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  expect(signal.aborted).toBe(true)
  expect(hook.result.current.data).toBeUndefined()
  await act(async () => { first?.({ potential_loss_rub: 1 }); second?.({ potential_loss_rub: 2 }) })
  await waitFor(() => expect(hook.result.current.data?.potential_loss_rub).toBe(2))
  hook.rerender({ input: null, scopeKey: 'run2/deposits/month' })
  expect(hook.result.current.data).toBeUndefined()
})
it('surfaces server errors without keeping a prior amount', async () => {
  vi.mocked(api).mockRejectedValue(new Error('Server rejected explicit rate'))
  const hook = setup({ affected: 2, rate_code: 'removed' }, 'current/deposits')
  await waitFor(() => expect(hook.result.current.isError).toBe(true))
  expect(hook.result.current.data).toBeUndefined()
})
