import { expect, test } from '@playwright/test'

// Проверка браузерной формы/вёрстки; реальный DB/agent scenario4 проверяет test_tracking_public.py.
test.beforeEach(async ({ page }) => {
  page.on('pageerror', error => { throw error })
  const token = 'a'.repeat(32)
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) { await route.continue(); return }
    let body: unknown = []
    if (path.endsWith('/regions')) body = [{ code: '01', name_ru: 'Адыгея' }]
    if (path.endsWith('/cities')) body = [{ id: 2, region_code: '01', name_ru: 'Майкоп' }]
    if (path.endsWith('/products')) body = [{ code: 'credit_card', name_ru: 'Кредитная карта' }]
    if (path.endsWith('/captcha')) body = { id: 'browser-challenge', question: '2 + 3 = ?' }
    if (path.endsWith('/claim')) {
      expect(route.request().postDataJSON()).toMatchObject({ consent: true, captcha: { id: 'browser-challenge', answer: 5 }, contact: { email: 'guest@example.com', city_id: 2 } })
      body = { public_id: 'SIG-000123', tracking_token: token, track_url: `/track/${token}`, qr_svg: '<svg xmlns="http://www.w3.org/2000/svg" />' }
    }
    if (path.includes('/track/')) {
      expect(route.request().headers()['referer']).toBeUndefined()
      body = { public_id: 'SIG-000123', timeline: [{ step: 'received', done: true }], can_append: false, notifications: [] }
    }
    await route.fulfill({ status: path.endsWith('/claim') ? 201 : 200, json: body })
  })
})

test('public landing sends a claim and exposes its private tracking link', async ({ page }) => {
  const token = 'a'.repeat(32)
  await page.goto('/landing')
  await expect(page.getByRole('button', { name: 'Отправить', exact: true })).toBeDisabled()
  await page.getByLabel('Эл. почта').fill('guest@example.com')
  await page.getByLabel('Регион', { exact: true }).selectOption('01')
  await page.getByLabel('Город', { exact: true }).selectOption('2')
  await page.locator('textarea').fill('Отказали в кредитной карте без объяснений. Почему?')
  await page.getByRole('checkbox').check()
  await page.getByLabel('Проверка', { exact: true }).fill('5')
  await page.getByRole('button', { name: 'Отправить', exact: true }).click()
  await expect(page.getByText('SIG-000123')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Открыть трекинг' })).toHaveAttribute('href', `/track/${token}`)
})

for (const lang of ['ru', 'en']) {
  for (const dark of [false, true]) {
    test(`landing ${lang} ${dark ? 'dark' : 'light'} layout`, async ({ page }, info) => {
      await page.addInitScript(({ lang, dark }) => {
        localStorage.setItem('cx.lang', lang)
        localStorage.setItem('cx.ui.mode', dark ? 'dark' : 'light')
      }, { lang, dark })
      await page.goto('/landing')
      await expect(page.getByRole('heading', { name: lang === 'ru' ? 'Обращение в Банк' : 'Contact the Bank' })).toBeVisible()
      await page.screenshot({ path: info.outputPath('landing.png'), fullPage: true })
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(2)
    })
  }
}
