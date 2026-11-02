import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { bootstrapCircadian, circadianPhase, DEFAULT_CIRCADIAN, MOSCOW, PHASES, readCoordinates, solarBoundaries, solarDay, solarPhase, validCircadian, validCoordinates } from '../circadian'

beforeEach(() => localStorage.clear())
afterEach(() => vi.useRealTimers())
it('calculates seasonal Moscow sunrise/sunset offline, including leap years', () => {
  const summer = solarDay(Date.parse('2024-06-21T12:00:00Z'))
  const winter = solarDay(Date.parse('2024-12-21T12:00:00Z'))
  expect((summer.sunset - summer.sunrise) / 3_600_000).toBeGreaterThan(17)
  expect((winter.sunset - winter.sunrise) / 3_600_000).toBeLessThan(8)
  // Проверочный диапазон восхода Москвы около летнего солнцестояния: 03–05 МСК.
  expect(new Date(summer.sunrise).getUTCHours()).toBeGreaterThanOrEqual(0)
  expect(new Date(summer.sunrise).getUTCHours()).toBeLessThanOrEqual(2)
  expect(solarPhase(NaN)).toBe('morning')
})
for (const date of ['2024-02-29', '2026-06-21', '2026-12-21']) for (const coordinates of [MOSCOW, { latitude: -33.9, longitude: 151.2 }, { latitude: 40.7, longitude: -74 }]) {
  it(`six ordered boundaries ${date}/${coordinates.longitude}`, () => {
    const { boundaries } = solarBoundaries(Date.parse(`${date}T12:00:00Z`), coordinates)
    expect(boundaries.every((time, i) => !i || time > boundaries[i - 1]!)).toBe(true)
    for (const [i, time] of boundaries.entries()) {
      // Формула привязана к местной солнечной дате, а не часовому поясу устройства.
      expect(solarPhase(time, coordinates)).toBe(PHASES[i])
      expect(solarPhase(time - 1, coordinates)).toBe(PHASES[(i + 5) % 6])
    }
  })
}
it('defines stable polar day/night without NaN or invented sunrise', () => {
  expect(solarPhase(Date.parse('2026-06-21T12:00:00Z'), { latitude: 90, longitude: 0 })).toBe('noon')
  expect(solarPhase(Date.parse('2026-12-21T12:00:00Z'), { latitude: 90, longitude: 0 })).toBe('night')
  expect(solarPhase(Date.parse('2026-06-21T12:00:00Z'), { latitude: -90, longitude: 0 })).toBe('night')
})
it('selects sim date/time, real clock or explicit fixed phase, never OS theme', () => {
  const noon = Date.parse('2026-06-21T12:00:00+03:00')
  const night = '2026-12-21T23:00:00+03:00'
  expect(circadianPhase(DEFAULT_CIRCADIAN, night, noon, MOSCOW)).toBe('night')
  expect(circadianPhase({ source: 'real', fixed_phase: 'night' }, night, noon, MOSCOW)).toBe('noon')
  for (const phase of PHASES) expect(circadianPhase({ source: 'fixed', fixed_phase: phase }, night, noon)).toBe(phase)
  localStorage.setItem('cx.ui.phase', 'dawn')
  expect(circadianPhase(DEFAULT_CIRCADIAN, null, noon)).toBe('dawn')
  localStorage.setItem('cx.ui.sim_time', night)
  expect(circadianPhase(DEFAULT_CIRCADIAN, null, noon)).toBe('night')
})
it('validates local inputs and defaults to Moscow without requesting geolocation', () => {
  expect(readCoordinates()).toEqual(MOSCOW)
  for (const value of [null, {}, { latitude: 91, longitude: 0 }, { latitude: 1, longitude: Infinity }, { latitude: '1', longitude: 2 }]) expect(validCoordinates(value)).toBeNull()
  expect(validCircadian({ source: 'network', fixed_phase: 'night' })).toBeNull()
  expect(validCircadian({ source: 'real', fixed_phase: 'broken' })).toBeNull()
  localStorage.setItem('cx.ui.location', '{broken')
  expect(readCoordinates()).toEqual(MOSCOW)
})
describe('bootstrap shared with runtime', () => {
  it('restores real solar phase before hydration rather than stale cached phase', () => {
    vi.useFakeTimers().setSystemTime(new Date('2026-06-21T12:00:00+03:00'))
    localStorage.setItem('cx.ui.mode', 'circadian')
    localStorage.setItem('cx.ui.circadian', JSON.stringify({ source: 'real', fixed_phase: 'night' }))
    localStorage.setItem('cx.ui.phase', 'night')
    bootstrapCircadian()
    expect(document.documentElement.dataset).toMatchObject({ phase: 'noon', mode: 'light', circadian: 'true' })
  })
  it('manual mode wins and remains stable across clock changes/reload', () => {
    localStorage.setItem('cx.ui.mode', 'light')
    localStorage.setItem('cx.ui.theme_pack', 'ops')
    localStorage.setItem('cx.ui.circadian', JSON.stringify({ source: 'fixed', fixed_phase: 'night' }))
    bootstrapCircadian()
    expect(document.documentElement.dataset).toMatchObject({ phase: 'night', mode: 'light', circadian: 'false', pack: 'ops' })
    bootstrapCircadian()
    expect(document.documentElement.dataset.mode).toBe('light')
  })
})

it('matches legacy mode fallback even if the newer preference is corrupted', () => {
  localStorage.setItem('cx.ui.mode', 'corrupt')
  localStorage.setItem('cx.theme', 'dark')
  bootstrapCircadian()
  expect(document.documentElement.dataset.mode).toBe('dark')
})
it('handles near-polar dawn/twilight crossing solar midnight', () => {
  for (const [latitude, iso, phase] of [
    [-78, '2026-10-22T23:59:35.305Z', 'dawn'],
    [-74, '2026-11-03T23:53:59.191Z', 'dawn'],
    [-71, '2026-01-30T00:05:11.484Z', 'twilight'],
    [-66, '2026-12-13T23:59:51.969Z', 'dawn'],
  ] as const) expect(solarPhase(Date.parse(iso), { latitude, longitude: 0 })).toBe(phase)
})
it('preserves all seasonal boundaries across a year near both polar circles and date-line longitudes', () => {
  let checked = 0
  for (let latitude = -89; latitude <= 89; latitude++) {
    if (Math.abs(latitude) < 60) continue
    for (const longitude of [-179, 0, 179]) for (let day = 1; day <= 365; day++) {
      const coordinates = { latitude, longitude }
      const sun = solarBoundaries(Date.UTC(2026, 0, day, 12), coordinates)
      if (sun.polar) continue
      for (let i = 0; i < PHASES.length; i++) {
        const phase = solarPhase(sun.boundaries[i]!, coordinates)
        if (phase !== PHASES[i]) throw new Error(`${latitude}/${longitude}/${day}/${i}: ${phase}`)
        checked++
      }
    }
  }
  expect(checked).toBeGreaterThan(200_000)
})
