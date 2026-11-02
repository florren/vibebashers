import { readFileSync } from 'node:fs'
const base = readFileSync('src/index.css', 'utf8')
const brand = readFileSync('src/shared/theming/brand.css', 'utf8')
const circadian = readFileSync('src/shared/theming/circadian.css', 'utf8')
const ops = readFileSync('src/shared/theming/ops.css', 'utf8')

// Читаем реальные CSS-токены в порядке root → mode → pack → phase.
export function tokens(pack: string, mode: string, phase?: string) {
  const selectors = [':root', ...(mode === 'dark' ? ['.dark'] : []), `html[data-pack='${pack}']`, `html[data-pack='${pack}'][data-mode='${mode}']`, ...(mode === 'dark' ? [`html[data-pack='${pack}'].dark`] : []), ...(phase ? ["html[data-circadian='true']", `html[data-circadian='true'][data-mode='${mode}'][data-phase='${phase}']`] : [])]
  const values: Record<string, string> = {}
  const blocks = [...`${base}\n${brand}\n${ops}\n${circadian}`.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  for (const selector of selectors) {
    for (const block of blocks) {
      const actual = block[1]!
      const declarations = block[2]!
      if (actual.trim().split('\n').at(-1)?.trim() !== selector) continue
      for (const declaration of declarations.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) values[declaration[1]!] = declaration[2]!.trim()
    }
  }
  const rgb = (name: string): [number, number, number] => {
    const value = values[name]
    if (!value) throw new Error(`missing token ${name}`)
    const alias = value.match(/^var\(--([\w-]+)\)$/)
    return alias ? rgb(alias[1]!) : value.split(/\s+/).map(Number) as [number, number, number]
  }
  return rgb
}

