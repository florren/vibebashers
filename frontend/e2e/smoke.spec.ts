import { expect, test, type Page } from '@playwright/test'

// Сырые ключи i18n вида "signal.type.tech_fault" или "hitl.accept" в тексте страницы — признак незакрытого перевода.
const RAW_KEY = /\b[a-z]+(\.[a-zA-Z_]+){1,3}\b/

async function collectProblems(page: Page) {
  const external: string[] = []
  const errors: string[] = []
  page.on('request', (r) => {
    const u = new URL(r.url())
    if (!['localhost', '127.0.0.1'].includes(u.hostname) && !u.hostname.endsWith('.local')) external.push(r.url())
  })
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  return { external, errors }
}

async function expectNoRawKeys(page: Page) {
  const text = await page.locator('body').innerText()
  const suspicious = text
    .split(/\s+/)
    .filter((w) => RAW_KEY.test(w) && !w.includes('@') && !/\d/.test(w) && !w.includes('/') && !w.startsWith('http'))
    // допустимые технические значения: коды команд/систем/правил показываются осознанно моноширинным
    .filter((w) => !/^(team|sub|core|rule|v\d)/.test(w))
  expect(suspicious, `похоже на сырые ключи i18n: ${suspicious.slice(0, 5).join(', ')}`).toEqual([])
}

const pages = ['/?tab=signals', '/?tab=incidents', '/?tab=hitl', '/?tab=deferred', '/engine']

for (const path of pages) {
  test(`открывается ${path}: без ошибок консоли, внешних запросов и сырых ключей`, async ({ page }) => {
    const problems = await collectProblems(page)
    await page.goto(path)
    await expect(page.getByText('CX Pulse Control')).toBeVisible()
    await page.waitForTimeout(800)
    await expectNoRawKeys(page)
    expect(problems.errors, problems.errors.join('\n')).toEqual([])
    expect(problems.external, `внешние запросы: ${problems.external.join(', ')}`).toEqual([])
  })
}

for (const path of pages) {
  test(`en ${path}: клик языка, английская подпись, без сырых ключей`, async ({ page }) => {
    await page.goto(path)
    await expect(page.getByText('CX Pulse Control')).toBeVisible()
    await page.getByRole('button', { name: 'Язык' }).click()
    await expect(page.getByRole('link', { name: 'Workspace' })).toBeVisible()
    await expectNoRawKeys(page)
  })
}

test('лента сигналов → drawer → карточка инцидента → под капотом', async ({ page }) => {
  await page.goto('/?tab=signals')
  const first = page.locator('li button').first()
  await expect(first).toBeVisible()
  await first.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.goto('/?tab=incidents')
  const card = page.locator('a[href^="/incidents/"]').first()
  if (await card.count()) {
    await card.click()
    await expect(page).toHaveURL(/\/incidents\/\d+/)
    await expectNoRawKeys(page)
  }
  await page.goto('/engine')
  await expect(page.getByRole('tab', { name: 'Шаги' })).toBeVisible()
})

test('тёмная тема переключается и сохраняется', async ({ page, request }) => {
  const previous = (await (await request.get('/api/settings')).json()).ui ?? null
  try {
    await page.goto('/')
    const mode = page.getByRole('combobox', { name: 'Режим', exact: true })
    await mode.selectOption('light')
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')
    await mode.selectOption('dark')
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    await expect(page.locator('html')).toHaveClass(/dark/)
    await expect.poll(async () => (await (await request.get('/api/settings')).json()).ui?.mode).toBe('dark')
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    await expect(page.locator('html')).toHaveClass(/dark/)
  } finally {
    await request.patch('/api/settings', { data: { ui: null } })
    if (previous !== null) await request.patch('/api/settings', { data: { ui: previous } })
  }
})

test('мобильная ширина не ломает шапку', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await page.goto('/?tab=signals')
  await expect(page.getByRole('tab', { name: 'Сигналы' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(2)
})
