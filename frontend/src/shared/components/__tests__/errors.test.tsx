import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { ApiConnectionError, ApiError, api } from '@/shared/api/client'
import { ErrorBox } from '@/shared/ui'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('ordinary protocol errors and TypeError remain unknown, with their controlled details available', () => {
  for (const error of [new Error('Incomplete comparison response'), new TypeError('Invalid local data')]) {
    const view = render(<ErrorBox error={error} />)
    expect(screen.getByRole('status')).toHaveTextContent('Не получилось выполнить действие.')
    expect(screen.getByText(error.message)).toBeInTheDocument()
    expect(screen.queryByText('Не получилось связаться с сервисом.', { exact: false })).not.toBeInTheDocument()
    view.unmount()
  }
})
it('only a marked fetch rejection receives connection wording; raw transport details stay out of DOM', async () => {
  const privateTransportDetail = 'https://localhost/private?token=DO_NOT_ECHO'
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError(privateTransportDetail)))
  let caught: unknown
  try { await api('/api/settings') } catch (error) { caught = error }
  expect(caught).toBeInstanceOf(ApiConnectionError)
  render(<ErrorBox error={caught} />)
  expect(screen.getByRole('status')).toHaveTextContent('Не получилось связаться с сервисом.')
  expect(screen.getByText('Network request failed')).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(privateTransportDetail)
})
it('HTTP Problem and fetch cancellation retain their existing typed behavior', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 429, statusText: 'Too Many Requests', json: async () => ({ title: 'Rate limited', status: 429 }) }))
  await expect(api('/api/settings')).rejects.toBeInstanceOf(ApiError)
  const cancelled = new DOMException('Cancelled', 'AbortError')
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(cancelled))
  await expect(api('/api/settings')).rejects.toBe(cancelled)
})
