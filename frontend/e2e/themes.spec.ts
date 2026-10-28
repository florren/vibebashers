import { expect, test } from '@playwright/test'

test('theme changes persist to settings, reload without a light flash, and follow OS auto', async ({ page, request }) => {
  const settings = await (await request.get('/api/settings')).json()
  const previous = settings.ui ?? null
  try {
    await request.patch('/api/settings', { data: { ui: { theme_pack: 'brand', mode: 'light', density: 'comfortable', theme_test_sentinel: true } } })
    await page.goto('/setup')
    await expect(page.locator('html')).toHaveAttribute('data-pack', 'brand')
    const selectors = page.locator('header select')
    await selectors.nth(0).selectOption('ops')
    await selectors.nth(1).selectOption('dark')
    await selectors.nth(2).selectOption('compact')
    await expect.poll(async () => (await (await request.get('/api/settings')).json()).ui).toMatchObject({ theme_pack: 'ops', mode: 'dark', density: 'compact', theme_test_sentinel: true })
    await page.addInitScript(() => {
      const modes: string[] = []
      const observer = new MutationObserver(() => { const m = document.documentElement?.dataset.mode; if (m) modes.push(m) })
      observer.observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-mode'] })
      Object.assign(window, { observedThemeModes: modes })
    })
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    expect(await page.evaluate(() => (window as Window & {observedThemeModes?: string[]}).observedThemeModes)).not.toContain('light')
    await selectors.nth(1).selectOption('auto')
    await page.emulateMedia({ colorScheme: 'light' })
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')
    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
  } finally {
    await request.patch('/api/settings', { data: { ui: null } })
    if (previous !== null) await request.patch('/api/settings', { data: { ui: previous } })
  }
})
