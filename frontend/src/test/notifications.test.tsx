import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'

import { NotificationsTab } from '@/pages/workspace/NotificationsTab'
import i18n from '@/shared/i18n'

afterEach(() => { vi.unstubAllGlobals() })

it.each(['ru', 'en'])('показывает unknown отдельно от sent/failed (%s)', async (lang) => {
  await i18n.changeLanguage(lang)
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [{
    id: 1, recipient_type: 'client', channel_code: 'telegram_bot', status: 'unknown',
    body: 'Synthetic uncertain delivery', sent_at: null, sent_sim: null, external_ref: null,
  }], total: 1 }), { headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('fetch', fetcher)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MemoryRouter><NotificationsTab runId={42} /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText(i18n.t('notifStatus.unknown'))).toBeVisible()
  expect(screen.getByText('Synthetic uncertain delivery')).toBeVisible()
  expect(screen.queryByText(i18n.t('notifStatus.sent'))).toBeNull()
  expect(screen.queryByText(i18n.t('notifStatus.failed'))).toBeNull()
  expect(fetcher).toHaveBeenCalledOnce()
  qc.clear()
})
