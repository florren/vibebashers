import { describe, expect, it } from 'vitest'
import { PHASES, resolveMode } from '../apply'
import { contrastRatio } from '../contrast'
import { BACKGROUNDS, FOREGROUNDS, PALETTE_KEYS, transitionPalette, TRANSITION_MS, type Palette } from '../transition'
import { tokens } from './tokens'

const palette = (pack: string, phase: string) => {
  const rgb = tokens(pack, resolveMode('circadian', phase as typeof PHASES[number]), phase)
  return Object.fromEntries(PALETTE_KEYS.map((key) => [key, rgb(key)])) as Palette
}
describe('every directed seasonal phase transition, real CSS from both packs', () => {
  for (const pack of ['brand', 'ops']) for (const from of PHASES) for (const to of PHASES) {
    it(`${pack}/${from}→${to}: every sampled frame preserves text/status/focus contrast`, () => {
      const a = palette(pack, from), b = palette(pack, to)
      for (let step = 0; step <= 100; step++) {
        const frame = transitionPalette(a, b, step / 100)
        for (const bg of BACKGROUNDS) for (const fg of FOREGROUNDS) {
          const minimum = fg === 'focus-ring' || fg === 'control-line' ? 3 : 4.5
          const ratio = contrastRatio(frame[fg]!, frame[bg]!)
          if (ratio < minimum) throw new Error(`${pack}/${from}/${to}/${step}: ${fg}/${bg}=${ratio}`)
        }
        expect(contrastRatio(frame['on-brand']!, frame['brand-strong']!)).toBeGreaterThanOrEqual(4.5)
      }
    })
  }
})
it('defines the required eight-second transition', () => expect(TRANSITION_MS).toBe(8000))

it('interpolates decorative borders and accents as well as surfaces', () => {
  const a = palette('ops', 'noon'), b = palette('ops', 'night')
  for (const key of ['line', 'brand']) {
    expect(transitionPalette(a, b, 0)[key]).toEqual(a[key])
    expect(transitionPalette(a, b, 1)[key]).toEqual(b[key])
    expect(transitionPalette(a, b, .5)[key]).toEqual(a[key]!.map((value, i) => Math.round((value + b[key]![i]!) / 2)))
  }
})
