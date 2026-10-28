import type { ResolvedThemeMode, ThemeDensity, ThemeMode, ThemePack } from './types'

export const PHASES = ['dawn', 'morning', 'noon', 'sunset', 'twilight', 'night'] as const
export type ThemePhase = (typeof PHASES)[number]

export function phaseAt(simTime?: string | null): ThemePhase {
  if (!simTime || !Number.isFinite(Date.parse(simTime))) {
    const cached = localStorage.getItem('cx.ui.phase')
    return PHASES.includes(cached as ThemePhase) ? cached as ThemePhase : 'morning'
  }
  const hour = Number(new Intl.DateTimeFormat('en', { hour: 'numeric', hourCycle: 'h23', timeZone: 'Europe/Moscow' }).format(new Date(simTime)))
  if (hour < 5 || hour >= 21) return 'night'
  if (hour < 7) return 'dawn'
  if (hour < 11) return 'morning'
  if (hour < 16) return 'noon'
  if (hour < 19) return 'sunset'
  return 'twilight'
}

export function resolveMode(mode: ThemeMode, phase: ThemePhase = phaseAt()): ResolvedThemeMode {
  if (mode === 'light' || mode === 'dark') return mode
  if (mode === 'circadian') return phase === 'night' || phase === 'twilight' ? 'dark' : 'light'
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyUiTheme(pack: ThemePack, mode: ThemeMode, density: ThemeDensity = 'comfortable', simTime?: string | null) {
  const phase = phaseAt(simTime)
  const resolved = resolveMode(mode, phase)
  const root = document.documentElement
  root.dataset.pack = pack
  root.dataset.mode = resolved
  root.dataset.phase = phase
  root.dataset.density = density
  root.classList.toggle('dark', resolved === 'dark')
  localStorage.setItem('cx.ui.phase', phase)
  localStorage.setItem('cx.theme', resolved)
}
