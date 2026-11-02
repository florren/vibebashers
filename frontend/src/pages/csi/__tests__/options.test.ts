import { expect, it } from 'vitest'
import { probabilityOption, scatterOption, tenureOption, positionOption } from '../options'
import type { CsiPalette } from '../palette'
import { snapshot } from './fixtures'
const palette = { ink: '#111', muted: '#555', line: '#ddd', surface: '#fff', brand: '#00a', danger: '#a00', warn: '#aa0', ok: '#0a0', info: '#0aa' } satisfies CsiPalette
it('preserves missing probabilities and known zero as different values', () => {
  const option = probabilityOption({ buckets: [{ bucket: '0', complaints: null, visits: null, probability: null }, { bucket: '1', complaints: 0, visits: 10, probability: 0 }], spearman: null, n_buckets: 1 }, palette, ['0', '1'])
  expect(option.series).toMatchObject([{ data: [null, 0] }])
})
it('uses observed min/max, R7 quartiles, and omits wholly unknown groups', () => {
  const option = tenureOption(snapshot, palette, key => key)
  expect(option.series).toMatchObject([{ type: 'custom', data: [[1, 0, 2.5, 5, 7.5, 10]], encode: { x: [1, 2, 3, 4, 5], y: 0 } }])
})
it('keeps unknown criticality in a separate symbol and does not classify it as low', () => {
  const option = scatterOption(snapshot, palette, key => key)
  expect(option.series).toMatchObject([{ symbol: 'triangle', data: [] }, { symbol: 'diamond', data: [] }, { symbol: 'circle', data: [] }, { symbol: 'rect', data: [{ value: [5, 12] }] }])
  expect(option.tooltip).toMatchObject({ renderMode: 'richText' })
  expect(option.animation).toBe(false)
})
it('uses API counts without dividing by guessed employee population', () => {
  expect(positionOption(snapshot, palette, 'unknown').series).toMatchObject([{ data: [1] }])
})
