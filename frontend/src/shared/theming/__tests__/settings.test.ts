import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act } from '@testing-library/react'
import { api, patch } from '@/shared/api/client'
import { PHASES, phaseAt, resolveMode } from '../apply'
import { DEFAULT_CIRCADIAN, MOSCOW, solarBoundaries } from '../circadian'
import { connectThemeSettings } from '../settings'
import { useUiTheme } from '../store'

vi.mock('@/shared/api/client', () => ({ api: vi.fn(), patch: vi.fn() }))
let disconnect = () => {}
const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
  useUiTheme.setState({ theme_pack: 'brand', mode: 'light', density: 'comfortable', simTime: null, syncError: false, circadian: { ...DEFAULT_CIRCADIAN } })
})
afterEach(() => { disconnect(); vi.unstubAllGlobals() })

it('hydrates validated server preferences without PATCHing or replacing unrelated UI settings', async () => {
  vi.mocked(api).mockResolvedValue({ ui: { theme_pack: 'ops', mode: 'dark', density: 'compact', lang: 'en' } })
  disconnect = connectThemeSettings()
  await flush()
  expect(useUiTheme.getState()).toMatchObject({ theme_pack: 'ops', mode: 'dark', density: 'compact' })
  expect(document.documentElement.dataset).toMatchObject({ pack: 'ops', mode: 'dark', density: 'compact' })
  expect(localStorage.getItem('cx.ui.theme_pack')).toBe('ops')
  expect(patch).not.toHaveBeenCalled()
})

it('keeps edits made during GET and serializes rapid changes', async () => {
  let finishGet!: (data: unknown) => void
  let finishPatch!: () => void
  vi.mocked(api).mockReturnValue(new Promise((resolve) => { finishGet = resolve }))
  vi.mocked(patch).mockImplementationOnce(() => new Promise<void>((resolve) => { finishPatch = resolve })).mockResolvedValue(undefined)
  disconnect = connectThemeSettings()
  useUiTheme.getState().setPack('ops')
  await flush()
  useUiTheme.getState().setMode('dark')
  finishGet({ ui: { theme_pack: 'brand', mode: 'light', density: 'compact' } })
  await flush()
  expect(useUiTheme.getState()).toMatchObject({ theme_pack: 'ops', mode: 'dark', density: 'compact' })
  expect(patch).toHaveBeenCalledTimes(1)
  finishPatch()
  await flush()
  expect(patch).toHaveBeenLastCalledWith('/api/settings', { ui: { mode: 'dark' } })
  expect(JSON.parse(localStorage.getItem('cx.ui.pending')!)).toEqual({})
})

it('keeps unsaved choices and exposes errors, then retries on reconnect', async () => {
  vi.mocked(api).mockResolvedValue({ ui: { mode: 'light' } })
  vi.mocked(patch).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
  disconnect = connectThemeSettings()
  await flush()
  useUiTheme.getState().setMode('dark')
  await flush()
  expect(useUiTheme.getState().syncError).toBe(true)
  expect(JSON.parse(localStorage.getItem('cx.ui.pending')!)).toEqual({ mode: 'dark' })
  disconnect()
  disconnect = connectThemeSettings()
  await flush()
  expect(useUiTheme.getState()).toMatchObject({ mode: 'dark', syncError: false })
  expect(JSON.parse(localStorage.getItem('cx.ui.pending')!)).toEqual({})
})

it('maps every seasonal Moscow boundary independently of OS theme', () => {
  const { boundaries } = solarBoundaries(Date.parse('2026-11-09T12:00:00+03:00'), MOSCOW)
  for (const [index, time] of boundaries.entries()) {
    expect(phaseAt(new Date(time).toISOString())).toBe(PHASES[index])
    expect(phaseAt(new Date(time - 1).toISOString())).toBe(PHASES[(index + 5) % 6])
    expect(resolveMode('circadian', PHASES[index])).toBe(index >= 4 ? 'dark' : 'light')
  }
  expect(resolveMode('auto')).toBe('light')
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
  expect(resolveMode('auto')).toBe('dark')
  expect(resolveMode('circadian', 'noon')).toBe('light')
  useUiTheme.getState().setMode('circadian')
  useUiTheme.getState().setSimTime('2026-11-09T23:00:00+03:00')
  expect(document.documentElement.dataset.mode).toBe('dark')
  expect(document.documentElement.dataset.phase).toBe('night')
})


it('preserves an acknowledged user choice when the initial GET arrives later', async () => {
  let finishGet!: (data: unknown) => void
  vi.mocked(api).mockReturnValue(new Promise((resolve) => { finishGet = resolve }))
  vi.mocked(patch).mockResolvedValue(undefined)
  disconnect = connectThemeSettings()
  useUiTheme.getState().setMode('dark')
  await flush()
  expect(JSON.parse(localStorage.getItem('cx.ui.pending')!)).toEqual({})
  finishGet({ ui: { theme_pack: 'ops', mode: 'light', density: 'compact' } })
  await flush()
  expect(useUiTheme.getState()).toMatchObject({ theme_pack: 'ops', mode: 'dark', density: 'compact' })
  expect(localStorage.getItem('cx.ui.mode')).toBe('dark')
  expect(document.documentElement.dataset.mode).toBe('dark')
})

it('synchronizes only the complete circadian preference, never local coordinates', async () => {
  vi.mocked(api).mockResolvedValue({ ui: { circadian: { source: 'real', fixed_phase: 'dawn' }, lang: 'en' } })
  vi.mocked(patch).mockResolvedValue(undefined)
  localStorage.setItem('cx.ui.location', JSON.stringify({ latitude: 12, longitude: 34 }))
  disconnect = connectThemeSettings()
  await flush()
  expect(useUiTheme.getState().circadian).toEqual({ source: 'real', fixed_phase: 'dawn' })
  useUiTheme.getState().setCircadian({ source: 'fixed', fixed_phase: 'night' })
  await flush()
  expect(patch).toHaveBeenLastCalledWith('/api/settings', { ui: { circadian: { source: 'fixed', fixed_phase: 'night' } } })
  expect(localStorage.getItem('cx.ui.location')).toBe('{"latitude":12,"longitude":34}')
})
