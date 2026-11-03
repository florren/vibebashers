import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { BotQrButton } from '@/widgets/BotQrButton'
import i18n from '@/shared/i18n'

afterEach(() => { vi.unstubAllGlobals() })

function mount(health: object) {
  const fetcher = vi.fn(async () => new Response(JSON.stringify(health), { headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('fetch', fetcher)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rendered = render(<QueryClientProvider client={qc}><BotQrButton /></QueryClientProvider>)
  return { fetcher, qc, ...rendered }
}

it.each(['ru', 'en'])('показывает настоящий username и крупный QR после ready health (%s)', async lang => {
  await i18n.changeLanguage(lang)
  const { fetcher, qc } = mount({ tgbot: 'running', tgbot_username: 'ReviewBankBot' })
  fireEvent.click(await screen.findByRole('button', { name: i18n.t('botQr.open') }))
  expect(screen.getByText('@ReviewBankBot')).toBeVisible()
  const qr = screen.getByRole('img', { name: i18n.t('botQr.alt') })
  expect(qr).toHaveAttribute('src', '/api/public/bot/qr')
  expect(qr).toHaveAttribute('width', '480')
  expect(screen.getByText(i18n.t('botQr.fictional'))).toBeVisible()
  fireEvent.error(qr)
  expect(screen.getByRole('alert')).toHaveTextContent(i18n.t('botQr.unavailable'))
  expect(screen.queryByRole('img')).toBeNull()
  expect(fetcher).toHaveBeenCalledOnce()
  qc.clear()
})

it.each([{ tgbot: 'disabled' }, { tgbot: 'error' }, { tgbot: 'running' }])('скрывает блок без подтверждённого polling username: %j', async health => {
  const { qc } = mount(health)
  await waitFor(() => expect(qc.isFetching()).toBe(0))
  expect(screen.queryByRole('button')).toBeNull()
  expect(screen.queryByRole('img')).toBeNull()
  qc.clear()
})
