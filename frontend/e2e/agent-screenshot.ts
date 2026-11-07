import type { Page, TestInfo } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { basename, dirname } from 'node:path'

const emptyFrame = /^(?:page\.screenshot: )?Protocol error \(Page\.captureScreenshot\): Unable to capture screenshot(?:\r?\n|$)/

async function paint(page: Page) {
  await page.bringToFront()
  await page.evaluate(async () => {
    await document.fonts.ready
    // Visible DOM ещё не означает, что compositor получил отрисованный кадр.
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
  })
}

export async function captureAgentScreenshot(page: Page, info: Pick<TestInfo, 'attach'>, path: string) {
  const url = page.url()
  const capture = () => page.screenshot({ path, fullPage: true, animations: 'disabled' })
  await paint(page)
  try {
    return await capture()
  } catch (error) {
    // Chromium ScreenshotCaptured возвращает эту ошибку при image.IsEmpty():
    // https://chromium.googlesource.com/chromium/src/+/refs/heads/main/content/browser/devtools/protocol/page_handler.cc
    // Восстанавливаем только один потерянный bitmap, а не перезапускаем UI-проверки.
    if (!(error instanceof Error) || !emptyFrame.test(error.message) || page.isClosed() || page.url() !== url) throw error
    // CI загружает test-results с list reporter: body-вложения остаются в памяти.
    const diagnosticPath = `${path}.empty-frame.json`
    await mkdir(dirname(diagnosticPath), { recursive: true })
    await writeFile(diagnosticPath, JSON.stringify({ url, viewport: page.viewportSize(), error: error.message }, null, 2))
    await info.attach(`${basename(path)}-empty-frame`, {
      path: diagnosticPath,
      contentType: 'application/json',
    })
    await paint(page)
    if (page.url() !== url) throw error
    // Повторная ошибка захвата не перехватывается: артефакт обязателен.
    return await capture()
  }
}
