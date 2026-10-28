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

// Проверяем сгенерированные text-brand стили на экране из PR #73.
test('theme packs retain readable trace links and global search', async ({ page, request }) => {
  const previous = (await (await request.get('/api/settings')).json()).ui ?? null
  try {
    for (const pack of ['brand', 'ops']) for (const mode of ['light', 'dark']) {
      await request.patch('/api/settings', { data: { ui: { theme_pack: pack, mode, density: 'comfortable' } } })
      await page.goto('/trace/signal/SIG-000001')
      await expect(page.locator('html')).toHaveAttribute('data-pack', pack)
      await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
      const link = page.getByRole('link', { name: 'Открыть след SIG-000001' }).last()
      await expect(link).toBeVisible()
      const contrast = await link.evaluate(renderedContrast)
      expect(contrast, `${pack}/${mode} trace link`).toBeGreaterThanOrEqual(4.5)
      expect(await page.getByTestId('app-logo').evaluate(renderedContrast), `${pack}/${mode} logo`).toBeGreaterThanOrEqual(3)
      await expect(page.getByRole('button', { name: 'Поиск Ctrl+K' })).toBeVisible()
      await expect(page.getByRole('link', { name: 'Путь обращения', exact: true }).first()).toBeVisible()
      await page.goto('/setup')
      await expect(page.locator('html')).toHaveAttribute('data-pack', pack)
      await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
      expect(await page.locator('ol button').first().evaluate(renderedContrast), `${pack}/${mode} selected control`).toBeGreaterThanOrEqual(4.5)
    }
  } finally {
    await request.patch('/api/settings', { data: { ui: null } })
    if (previous !== null) await request.patch('/api/settings', { data: { ui: previous } })
  }
})

function renderedContrast(element: Element) {
        const rgb = (color: string) => (color.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number)
        const luminance = (channels: number[]) => channels.map((v) => {
          const c = v / 255
          return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
        }).reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i]!, 0)
        let parent: Element | null = element
        while (parent && getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') parent = parent.parentElement
        const foreground = luminance(rgb(getComputedStyle(element).color))
        const background = luminance(rgb(getComputedStyle(parent ?? document.body).backgroundColor))
        return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05)
      }
