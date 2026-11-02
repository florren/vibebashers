import { describe, expect, it } from 'vitest'
import { PHASES, resolveMode } from '../apply'
import { contrastRatio } from '../contrast'
import { tokens } from './tokens'

describe('actual theme tokens across packs, modes and phases', () => {
  for (const pack of ['brand', 'ops']) for (const mode of ['light', 'dark', 'circadian'] as const) for (const phase of PHASES) {
    it(`${pack}/${mode}/${phase}: text ≥4.5, controls ≥3`, () => {
      const rgb = tokens(pack, resolveMode(mode, phase), mode === 'circadian' ? phase : undefined)
      for (const bg of ['surface-1', 'surface-2', 'surface-3']) {
        for (const ink of ['ink', 'ink-muted', 'brand-foreground', 'ok', 'warn', 'danger', 'info']) expect(contrastRatio(rgb(ink), rgb(bg)), `${ink}/${bg}`).toBeGreaterThanOrEqual(4.5)
        for (const control of ['focus-ring', 'control-line', 'brand-strong']) expect(contrastRatio(rgb(control), rgb(bg)), `${control}/${bg}`).toBeGreaterThanOrEqual(3)
      }
      expect(contrastRatio(rgb('on-brand'), rgb('brand-strong'))).toBeGreaterThanOrEqual(4.5)
    })
  }
})
