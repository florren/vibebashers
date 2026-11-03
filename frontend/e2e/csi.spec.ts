import { expect, test } from '@playwright/test'

// Настоящие API/production UI; fixture меняет настройки только собственного стенда.
for (const language of ['ru', 'en']) for (const mode of ['light', 'dark']) {
  test(`CSI native scope and charts ${language} ${mode}`, async ({ page, request }, info) => {
    const settings = await (await request.get('/api/settings')).json()
    expect((await request.patch('/api/settings', { data: { ui: { layout: 'v2', mode, theme_pack: 'brand', attention: 'calm' } } })).ok()).toBeTruthy()
    await page.addInitScript(({ language, mode }) => {
      localStorage.setItem('cx.lang', language); localStorage.setItem('cx.ui.layout', 'v2'); localStorage.setItem('cx.ui.mode', mode)
      localStorage.setItem('cx.ui.theme_pack', 'brand'); localStorage.setItem('cx.ui.role', 'cx_lead'); localStorage.removeItem('cx.ui.productLine')
    }, { language, mode })
    const expectedResponse = await request.get('/api/csi/analytics?run_id=current&period=month', { headers: { 'X-Cx-Role': 'cx_lead' } })
    expect(expectedResponse.status()).toBe(200)
    const expected = await expectedResponse.json()
    const errors: string[] = [], external: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const origin = new URL(info.project.use.baseURL as string).origin
    page.on('request', request => { const url = new URL(request.url()); if (!['data:', 'blob:'].includes(url.protocol) && url.origin !== origin) external.push(request.url()) })
    try {
      await page.goto('/csi?run_id=current&period=month')
      const root = page.getByRole('main', { name: language === 'ru' ? 'CSI и сеть ВСП' : 'CSI and branch network' })
      await expect(root.locator('[data-block]')).toHaveCount(9)
      await expect(root.locator('svg').first()).toBeVisible()
      await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
      expect(await root.textContent()).not.toMatch(/csi\.[a-zA-Z]/)
      const table = root.locator('[data-block]').first()
      await expect(table.locator('tbody tr')).toHaveCount(expected.complaints.items.length)
      const row = expected.complaints.items[0]
      if (row) {
        await expect(table.getByRole('link', { name: row.signal_ref }).first()).toHaveAttribute('href', `/trace/signal/${row.signal_ref}?run_id=current`)
        if (row.csi_no) await expect(table.getByRole('link', { name: row.csi_no }).first()).toHaveAttribute('href', `/trace/csi/${row.csi_no}?run_id=current`)
      }
      await page.screenshot({ path: info.outputPath(`csi-${language}-${mode}-table.png`) })
      await root.locator('[data-block]').nth(1).scrollIntoViewIfNeeded()
      await page.screenshot({ path: info.outputPath(`csi-${language}-${mode}-charts.png`) })
      const probability = root.locator('[data-block]').nth(7)
      await probability.scrollIntoViewIfNeeded(); await expect(probability).toContainText('Spearman')
      await expect(probability.locator('tbody tr')).toHaveCount(expected.probabilities.wait.buckets.length)
      await page.screenshot({ path: info.outputPath(`csi-${language}-${mode}-probabilities.png`) })
      await root.getByRole('combobox', { name: language === 'ru' ? 'Период' : 'Period', exact: true }).selectOption('week')
      await expect(page).toHaveURL(/period=week/)
      await expect(root.locator('[data-block]')).toHaveCount(9)
      expect(errors).toEqual([]); expect(external).toEqual([])
    } finally { await request.patch('/api/settings', { data: { ui: settings.ui ?? null } }) }
  })
}

test('CSI mobile has no page overflow and keeps chart alternatives', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/csi?run_id=current')
  const root = page.getByRole('main', { name: /CSI/ })
  await expect(root.locator('[data-block]')).toHaveCount(9)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await expect(root.locator('summary').first()).toBeVisible()
})
