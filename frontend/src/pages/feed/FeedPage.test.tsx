import { cleanup, render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { fmtDateTime } from '@/shared/lib/format'
import { FeedPage } from './FeedPage'

const { post } = vi.hoisted(() => ({ post: {
  id: 1, public_id: 'POST-000001', platform: 'review_portal', author_nick: '@client_demo',
  text: 'Вопрос клиента', posted_at: '2026-11-03T09:00:00Z', posted_sim: '2026-11-09T09:00:00Z',
  status: 'replied', author_client: null,
  replies: [{ id: 1, author: 'agent', text: 'Ответ банка', published_at: '2026-11-03T09:00:01Z' }],
} }))
vi.mock('@/shared/api/hooks', () => ({
  useFeed: () => ({ data: { items: [post] } }),
  useFeedStats: () => ({}),
  usePost: () => ({ data: post }),
  useAbsAccounts: () => ({}),
  useRefName: () => (value: string) => value,
  usePublishReview: () => ({}),
  useManualReply: () => ({}),
}))
afterEach(cleanup)

it.each(['ru', 'en'])('сопоставляет вопрос и ответ по реальным часам, %s', async language => {
  await i18n.changeLanguage(language)
  const { container } = render(<MemoryRouter><FeedPage /></MemoryRouter>)
  const times = Array.from(container.querySelectorAll('time')).map(el => el.dateTime)
  expect(times).toEqual([post.posted_at, post.replies[0]!.published_at])
  expect(container).toHaveTextContent(fmtDateTime(post.posted_at))
  expect(Date.parse(times[1]!)).toBeGreaterThanOrEqual(Date.parse(times[0]!))
  expect(container.querySelector('time')?.title).toContain(i18n.t('feed.realTime'))
})
