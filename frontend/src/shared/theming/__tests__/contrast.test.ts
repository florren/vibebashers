import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
const base = readFileSync('src/index.css', 'utf8')
const brand = readFileSync('src/shared/theming/brand.css', 'utf8')
const ops = readFileSync('src/shared/theming/ops.css', 'utf8')
import { PHASES, resolveMode } from '../apply'
import { contrastRatio } from '../contrast'

// Read the actual CSS declarations, applying the same root → mode → pack cascade.
function tokens(pack: string, mode: string) {
  const selectors = [':root', ...(mode === 'dark' ? ['.dark'] : []), `html[data-pack='${pack}']`, `html[data-pack='${pack}'][data-mode='${mode}']`, ...(mode === 'dark' ? [`html[data-pack='${pack}'].dark`] : [])]
  const values: Record<string, string> = {}
  const blocks = [...`${base}\n${brand}\n${ops}`.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
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

describe('actual theme tokens across packs, modes and phases', () => {
  for (const pack of ['brand', 'ops']) for (const mode of ['light', 'dark', 'circadian'] as const) for (const phase of PHASES) {
    it(`${pack}/${mode}/${phase}: text ≥4.5, controls ≥3`, () => {
      const rgb = tokens(pack, resolveMode(mode, phase))
      for (const bg of ['surface-1', 'surface-2', 'surface-3']) {
        for (const ink of ['ink', 'ink-muted', 'brand-foreground', 'ok', 'warn', 'danger', 'info']) expect(contrastRatio(rgb(ink), rgb(bg)), `${ink}/${bg}`).toBeGreaterThanOrEqual(4.5)
        for (const control of ['focus-ring', 'control-line', 'brand-strong']) expect(contrastRatio(rgb(control), rgb(bg)), `${control}/${bg}`).toBeGreaterThanOrEqual(3)
      }
      expect(contrastRatio(rgb('on-brand'), rgb('brand-strong'))).toBeGreaterThanOrEqual(4.5)
    })
  }
})
