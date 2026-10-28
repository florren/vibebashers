import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act } from '@testing-library/react'
import { api, patch } from '@/shared/api/client'
import { PHASES, phaseAt, resolveMode } from '../apply'
import { connectThemeSettings } from '../settings'
import { useUiTheme } from '../store'

vi.mock('@/shared/api/client', () => ({ api: vi.fn(), patch: vi.fn() }))
let disconnect = () => {}
const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
  useUiTheme.setState({ theme_pack: 'brand', mode: 'light', density: 'comfortable', simTime: null, syncError: false })
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

it('maps all Moscow simulation phase boundaries independently of OS theme', () => {
  const hours = [5, 7, 11, 16, 19, 21]
  for (const [index, hour] of hours.entries()) {
    const phase = phaseAt(`2026-11-09T${String(hour).padStart(2, '0')}:00:00+03:00`)
    expect(phase).toBe(PHASES[index])
    expect(resolveMode('circadian', phase)).toBe(hour >= 19 ? 'dark' : 'light')
  }
  expect(phaseAt('2026-11-09T04:59:59+03:00')).toBe('night')
  expect(resolveMode('auto')).toBe('light')
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
  expect(resolveMode('auto')).toBe('dark')
  expect(resolveMode('circadian', 'noon')).toBe('light')
  useUiTheme.getState().setMode('circadian')
  useUiTheme.getState().setSimTime('2026-11-09T21:00:00+03:00')
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
