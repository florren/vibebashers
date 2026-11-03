import { expect, test } from '@playwright/test'

// Синтетические API fixtures: browser proof порядка, не доказательство внешней доставки.
for (const lang of ['ru', 'en']) for (const theme of ['light', 'dark']) {
  test(`хронология каналов ${lang} ${theme}`, async ({ page }, info) => {
    await page.addInitScript(({ lang, theme }) => {
      localStorage.setItem('cx.lang', lang)
      localStorage.setItem('cx.ui.mode', theme)
      localStorage.setItem('cx.ui.layout', 'legacy')
    }, { lang, theme })
    const post = {
      id: 1, public_id: 'POST-000001', platform: 'review_portal', author_nick: '@client_demo',
      text: 'Вопрос клиента', posted_at: '2026-11-03T09:00:00Z', posted_sim: '2026-11-09T09:00:00Z',
      status: 'replied', author_client: null,
      replies: [{ id: 1, author: 'agent', text: 'Ответ банка', published_at: '2026-11-03T09:00:01Z' }],
    }
    const writes: string[] = []
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (!path.startsWith('/api/')) { await route.continue(); return }
      if (route.request().method() !== 'GET') { writes.push(path); await route.abort(); return }
      const data = path === '/api/public/feed' ? { items: [post], total: 1, next_cursor: null }
        : path === '/api/public/feed/1' ? post
          : path === '/api/personal/session' ? { display_name: '', products: [], regions: [], cities: [] }
            : path === '/api/personal/messages' ? {
              messages: [
                { public_id: 'SIG-000001', text: 'Вопрос один', status: 'answered', received_at: '2026-11-03T12:00:00.123100+03:00' },
                { public_id: 'SIG-000002', text: 'Вопрос два', status: 'answered', received_at: '2026-11-03T09:00:00.123300Z' },
              ], answers: [
                { id: 1, text: 'Ответ один', at: '2026-11-03T09:00:00.123200Z' },
                { id: 2, text: 'Ответ два', at: '2026-11-03T09:00:00.123400Z' },
              ],
            } : path.startsWith('/api/refs/') || path === '/api/scenarios' ? [] : {}
      await route.fulfill({ json: data })
    })
    await page.goto('/feed')
    await expect(page.locator('time')).toHaveCount(2)
    expect(await page.locator('time').evaluateAll(elements => elements.map(el => el.getAttribute('datetime'))))
      .toEqual([post.posted_at, post.replies[0]!.published_at])
    await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
    await page.screenshot({ path: info.outputPath('feed-chronology.png'), fullPage: true })
    await page.goto('/personal.html')
    await expect(page.locator('article p.whitespace-pre-wrap')).toHaveText(['Вопрос один', 'Ответ один', 'Вопрос два', 'Ответ два'])
    await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
    await page.screenshot({ path: info.outputPath('personal-chronology.png'), fullPage: true })
    expect(writes).toEqual([])
  })
}
