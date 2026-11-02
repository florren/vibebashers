import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { LlmKeysPanel } from '../LlmKeysPanel'
import type { LlmApiKey } from '@/shared/api/client'
import i18n from '@/shared/i18n'

const base: LlmApiKey = { id: 7, provider: 'openai_compatible', label: 'synthetic-key', key_hint: '••••', is_active: true, tokens_limit: 100, rpd_limit: 10 }
afterEach(() => { vi.unstubAllGlobals() })
function mount(key: Partial<LlmApiKey>) {
  const fetcher = vi.fn(async () => new Response(JSON.stringify([{ ...base, ...key }]), { headers: { 'content-type': 'application/json' } }))
  vi.stubGlobal('fetch', fetcher)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><LlmKeysPanel /></QueryClientProvider>)
  return { qc, fetcher }
}
it.each(['ru', 'en'])('unknown legacy не превращается в остаток или полный расход (%s)', async lang => {
  await i18n.changeLanguage(lang)
  const { qc, fetcher } = mount({ tokens_used: 17, usage_known: false, observed_tokens_floor: 3, usage_source: 'legacy_unverified', tokens_remaining: null, requests_today: 0, requests_known: false, requests_remaining: null, requests_day: '2026-11-02' })
  const row = (await screen.findByText('synthetic-key')).closest('tr')!
  expect(within(row).getAllByText(i18n.t('setup.keys.usageUnknown')).length).toBe(2)
  expect(within(row).getAllByText(i18n.t('setup.keys.remaining', { value: i18n.t('setup.keys.usageUnknown') })).length).toBe(2)
  expect(within(row).getByText(i18n.t('setup.keys.observedFloor', { value: 3 }))).toBeVisible()
  expect(within(row).getByText(i18n.t('setup.keys.legacyHint', { value: 17 }))).toBeVisible()
  expect(within(row).queryByText(i18n.t('setup.keys.remaining', { value: 83 }))).toBeNull()
  expect(within(row).getByText(i18n.t('setup.keys.requestsDay', { value: '2026-11-02' }))).toBeVisible()
  expect(fetcher).toHaveBeenCalledOnce()
  qc.clear()
})
it('missing known flags старого сервера не означают known zero', async () => {
  await i18n.changeLanguage('ru')
  const { qc } = mount({ tokens_used: 0, requests_today: 0 })
  const row = (await screen.findByText('synthetic-key')).closest('tr')!
  expect(within(row).getAllByText('Неизвестно')).toHaveLength(2)
  expect(within(row).queryByText('Осталось: 100')).toBeNull()
  expect(within(row).queryByText('Осталось: 10')).toBeNull()
  qc.clear()
})
it('подтверждённый zero остаётся zero, остаток берётся только с сервера', async () => {
  await i18n.changeLanguage('ru')
  const { qc } = mount({ tokens_used: 0, usage_known: true, observed_tokens_floor: 0, tokens_remaining: 0, requests_today: 0, requests_known: true, requests_remaining: 0, balance_usd: 0 })
  const row = (await screen.findByText('synthetic-key')).closest('tr')!
  expect(within(row).getAllByText('Осталось: 0')).toHaveLength(2)
  expect(within(row).queryByText('Осталось: 100')).toBeNull()
  expect(within(row).queryByText('Неизвестно')).toBeNull()
  expect(within(row).getByText('0 USD')).toBeVisible()
  qc.clear()
})
it('не показывает непроверенный remaining даже при переданном числе', async () => {
  await i18n.changeLanguage('en')
  const { qc } = mount({ usage_known: false, tokens_used: 20, tokens_remaining: 80, requests_known: false, requests_today: 1, requests_remaining: 9, usage_source: 'synthetic-private-echo' })
  const row = (await screen.findByText('synthetic-key')).closest('tr')!
  expect(within(row).queryByText('Remaining: 80')).toBeNull()
  expect(within(row).queryByText('Remaining: 9')).toBeNull()
  expect(row).not.toHaveTextContent('synthetic-private-echo')
  qc.clear()
})
