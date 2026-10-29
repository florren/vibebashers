import { chromium } from '../../../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs/promises'
const dir = process.env.CX_SCREENSHOT_DIR ?? '/tmp/finance-visual'
await fs.mkdir(dir, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_EXECUTABLE ? { executablePath: process.env.CHROME_EXECUTABLE } : {}) })
const report = []
for (const lang of ['ru', 'en']) {
  for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: 'reduce' })
    await context.addInitScript(({lang, theme}) => {
      localStorage.setItem('cx.lang', lang)
      localStorage.setItem('cx.ui.mode', theme)
      localStorage.setItem('cx.ui.pending', JSON.stringify({ mode: theme }))
    }, {lang,theme})
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(`${process.env.CX_BASE_URL ?? 'http://localhost:8000'}/finance`)
    await page.getByText(lang === 'ru' ? '1 · Действующая модель dCLTV' : '1 · Existing dCLTV model').waitFor()
    await page.screenshot({ path: `${dir}/${lang}-${theme}.png`, fullPage: true })
    const first = page.getByRole('button', { name: /^INC-/ }).first()
    if (await first.count()) {
      await first.click()
      await page.getByRole('dialog').waitFor()
      await page.getByRole('dialog').getByRole('link').waitFor()
      await page.screenshot({ path: `${dir}/${lang}-${theme}-detail.png`, fullPage: true })
      await page.keyboard.press('Escape')
    }
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('main > div').evaluate(el => el.scrollTop = 0)
    await page.screenshot({ path: `${dir}/${lang}-${theme}-mobile.png`, fullPage: true })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    report.push({ lang, theme, errors, overflow })
    await context.close()
  }
}
await browser.close()
await fs.writeFile(`${dir}/report.json`, JSON.stringify(report, null, 2))
console.log(JSON.stringify(report))
if (report.some(x => x.errors.length || x.overflow)) process.exitCode = 1
