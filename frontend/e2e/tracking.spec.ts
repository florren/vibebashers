import { expect, test } from '@playwright/test'

for (const lang of ['ru', 'en']) {
  for (const dark of [false, true]) {
    test(`tracking ${lang} ${dark ? 'dark' : 'light'}: reply and accessible narrow layout`, async ({ page }, info) => {
      await page.addInitScript(({ lang, dark }) => {
        localStorage.setItem('cx.lang', lang)
        localStorage.setItem('cx.ui.mode', dark ? 'dark' : 'light')
      }, { lang, dark })
      let appended = false
      await page.route('**/api/public/track/**', async route => {
        if (route.request().method() === 'POST') {
          expect(route.request().postDataJSON()).toEqual({ text: '450 рублей' })
          expect(route.request().headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/)
          appended = true
          await route.fulfill({ status: 202 })
          return
        }
        await route.fulfill({ json: { public_id: 'SIG-000123', can_append: !appended, question_from_agent: lang === 'en' ? 'What was the amount?' : 'Уточните сумму операции', timeline: [{ step: 'received', done: true, at_sim: '2026-11-01T10:00:00Z' }, { step: 'team_working', done: true }, { step: 'clarification_needed', done: !appended }], notifications: [{ id: 1, body: lang === 'en' ? 'We are reviewing your request' : 'Мы проверяем ваше обращение', status: 'sent' }] } })
      })
      await page.setViewportSize({ width: 390, height: 844 })
      await page.goto('/track/' + 'a'.repeat(32))
      await expect(page.getByText('SIG-000123')).toBeVisible()
      await page.getByRole('combobox').selectOption(lang)
      await page.evaluate(dark => document.documentElement.classList.toggle('dark', dark), dark)
      const input = page.locator('textarea')
      await input.fill('450 рублей')
      await page.screenshot({ path: info.outputPath('tracking.png'), fullPage: true })
      await page.getByRole('button', { name: lang === 'en' ? 'Send update' : 'Отправить дополнение' }).click()
      await expect(input).toHaveCount(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(2)
      await expect(page.getByRole('link')).toBeVisible()
    })
  }
}
