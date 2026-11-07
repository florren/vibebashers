import { expect, test } from '@playwright/test'
import { captureAgentScreenshot } from './agent-screenshot'

const emptyFrame = 'page.screenshot: Protocol error (Page.captureScreenshot): Unable to capture screenshot'

test('снимок ждёт кадр и сохраняет всю страницу', async ({ page }, info) => {
  await page.setContent('<div style="height:1800px;background:#21a038">static graph</div>')
  await page.evaluate(() => {
    let frames = 0
    const count = () => { document.documentElement.dataset.frames = String(++frames); requestAnimationFrame(count) }
    requestAnimationFrame(count)
  })
  const screenshot = page.screenshot.bind(page)
  let calls = 0
  let failures = 0
  page.screenshot = async options => {
    calls++
    expect(Number(await page.locator('html').getAttribute('data-frames'))).toBeGreaterThanOrEqual(2)
    expect(options).toMatchObject({ fullPage: true, animations: 'disabled' })
    try { return await screenshot(options) } catch (error) { failures++; throw error }
  }
  const png = await captureAgentScreenshot(page, info, info.outputPath('full-page.png'))
  // Реальный compositor тоже может вернуть один empty frame: корректное
  // восстановление не должно превращаться в новый flaky assert числа вызовов.
  expect(calls).toBe(failures + 1)
  expect(failures).toBeLessThanOrEqual(1)
  expect(info.attachments).toHaveLength(failures)
  expect(png.subarray(0, 8)).toEqual(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
  expect(png.readUInt32BE(20)).toBeGreaterThan(page.viewportSize()!.height)
})

test('один пустой bitmap восстанавливается с диагностикой и настоящим PNG', async ({ page }, info) => {
  await page.setContent('<div style="height:1800px">interrupted</div>')
  const screenshot = page.screenshot.bind(page)
  let calls = 0
  page.screenshot = async options => {
    if (++calls === 1) throw new Error(emptyFrame)
    return screenshot(options)
  }
  const png = await captureAgentScreenshot(page, info, info.outputPath('recovered.png'))
  expect(calls).toBe(2)
  expect(png.readUInt32BE(20)).toBeGreaterThan(page.viewportSize()!.height)
  const diagnostic = info.attachments.find(item => item.name === 'recovered.png-empty-frame')
  expect(diagnostic?.contentType).toBe('application/json')
  expect(JSON.parse(diagnostic!.body!.toString()).error).toBe(emptyFrame)
})

test('повторный пустой bitmap остаётся ошибкой', async ({ page }, info) => {
  await page.setContent('<p>interrupted</p>')
  const error = new Error(emptyFrame)
  let calls = 0
  page.screenshot = async () => { calls++; throw error }
  await expect(captureAgentScreenshot(page, info, info.outputPath('persistent.png'))).rejects.toBe(error)
  expect(calls).toBe(2)
  expect(info.attachments).toHaveLength(1)
})

for (const message of ['page.screenshot: Timeout 30000ms exceeded', 'Target page, context or browser has been closed', 'Protocol error (Page.captureScreenshot): Unable to encode screenshot']) {
  test(`другая ошибка не перехватывается: ${message}`, async ({ page }, info) => {
    await page.setContent('<p>interrupted</p>')
    const error = new Error(message)
    let calls = 0
    page.screenshot = async () => { calls++; throw error }
    await expect(captureAgentScreenshot(page, info, info.outputPath('failed.png'))).rejects.toBe(error)
    expect(calls).toBe(1)
    expect(info.attachments).toHaveLength(0)
  })
}

test('переход на другую страницу не выдаёт её снимок за исходную', async ({ page }, info) => {
  await page.setContent('<p>interrupted</p>')
  const error = new Error(emptyFrame)
  let calls = 0
  page.screenshot = async () => {
    calls++
    await page.goto('data:text/html,new page')
    throw error
  }
  await expect(captureAgentScreenshot(page, info, info.outputPath('navigated.png'))).rejects.toBe(error)
  expect(calls).toBe(1)
  expect(info.attachments).toHaveLength(0)
})
