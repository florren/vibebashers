import { describe, expect, it } from 'vitest'
import { contrastRatio } from '../contrast'

type Sample = { name: string; ink: [number, number, number]; bg: [number, number, number] }

const BRAND: Sample[] = [
  { name: 'brand light', ink: [24, 28, 31], bg: [246, 247, 248] },
  { name: 'brand dark', ink: [232, 236, 239], bg: [15, 18, 21] },
]

const OPS: Sample[] = [
  { name: 'ops light', ink: [24, 28, 31], bg: [244, 245, 247] },
  { name: 'ops dark', ink: [232, 236, 239], bg: [12, 14, 18] },
]

describe('theme contrast tokens', () => {
  for (const row of [...BRAND, ...OPS]) {
    it(`${row.name} body text ≥ 4.5:1`, () => {
      expect(contrastRatio(row.ink, row.bg)).toBeGreaterThanOrEqual(4.5)
    })
  }

  it('brand accent on surface ≥ 3:1 (large)', () => {
    const ratio = contrastRatio([33, 160, 56], [255, 255, 255])
    expect(ratio).toBeGreaterThanOrEqual(3)
  })
})
