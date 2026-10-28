import { expect, test } from '@playwright/test'

test('local Latin/Cyrillic faces render with all required weights without external access', async ({ page, baseURL }) => {
  const external: string[] = []
  const fonts: string[] = []
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.origin !== new URL(baseURL!).origin) {
      external.push(url.href)
      await route.abort()
    } else {
      if (url.pathname.endsWith('.woff2')) fonts.push(url.pathname)
      await route.continue()
    }
  })
  await page.goto('/setup')
  await page.evaluate(async () => {
    for (const [family, weights] of [['Inter', [400, 500, 600, 700]], ['JetBrains Mono', [400, 500]]] as const) {
      for (const weight of weights) {
        for (const text of ['Local fonts', 'Кириллица ёж']) {
          await document.fonts.load(`${weight} 24px "${family}"`, text)
          const sample = document.createElement('div')
          sample.id = `font-${family.replaceAll(' ', '')}-${weight}-${text === 'Local fonts' ? 'latin' : 'cyrillic'}`
          sample.style.font = `${weight} 24px "${family}", monospace`
          sample.textContent = text
          document.body.append(sample)
        }
      }
    }
    await document.fonts.ready
  })
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('DOM.enable')
  await cdp.send('CSS.enable')
  const { root } = await cdp.send('DOM.getDocument')
  for (const [family, weights] of [['Inter', [400, 500, 600, 700]], ['JetBrains Mono', [400, 500]]] as const) {
    for (const weight of weights) {
      for (const alphabet of ['latin', 'cyrillic']) {
        const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: `#font-${family.replaceAll(' ', '')}-${weight}-${alphabet}` })
        const { fonts: rendered } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId })
        expect(rendered.length).toBeGreaterThan(0)
        expect(rendered.every((font) => font.isCustomFont && font.familyName.startsWith(family) && font.postScriptName === `${family.replaceAll(' ', '')}-${({400: 'Regular', 500: 'Medium', 600: 'SemiBold', 700: 'Bold'} as Record<number, string>)[weight]}` && font.glyphCount > 0), JSON.stringify({family, weight, alphabet, rendered})).toBe(true)
      }
    }
  }
  expect(new Set(fonts).size).toBe(12)
  expect(external).toEqual([])
})
