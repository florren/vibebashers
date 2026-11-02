import type { ResolvedThemeMode, ThemeDensity, ThemeMode, ThemePack } from './types'
import { circadianPhase, readCircadian, type ThemePhase } from './circadian'
import { animateTheme, cancelThemeTransition, clearPalette, readPalette } from './transition'
export { PHASES, type ThemePhase } from './circadian'

export function phaseAt(simTime?: string | null): ThemePhase {
  return circadianPhase(readCircadian(), simTime)
}
export function resolveMode(mode: ThemeMode, phase: ThemePhase = phaseAt()): ResolvedThemeMode {
  if (mode === 'light' || mode === 'dark') return mode
  if (mode === 'circadian') return phase === 'night' || phase === 'twilight' ? 'dark' : 'light'
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyUiTheme(pack: ThemePack, mode: ThemeMode, density: ThemeDensity = 'comfortable', simTime?: string | null, animate = false) {
  const phase = phaseAt(simTime)
  const resolved = resolveMode(mode, phase)
  const root = document.documentElement
  const changed = root.dataset.phase !== phase || root.dataset.mode !== resolved || root.dataset.pack !== pack
  const shouldAnimate = animate && changed && mode === 'circadian' && !matchMedia('(prefers-reduced-motion: reduce)').matches
  const from = shouldAnimate ? readPalette(root) : null
  // Повторный tick той же фазы не обрывает уже идущий переход.
  if (!changed && animate) return
  cancelThemeTransition()
  clearPalette(root)
  root.dataset.themeTransition = 'idle'
  const attributes = { pack, mode: resolved, phase, circadian: String(mode === 'circadian'), density }
  for (const [key, value] of Object.entries(attributes)) if (root.dataset[key] !== value) root.dataset[key] = value
  if (root.classList.contains('dark') !== (resolved === 'dark')) root.classList.toggle('dark', resolved === 'dark')
  localStorage.setItem('cx.ui.phase', phase)
  localStorage.setItem('cx.theme', resolved)
  if (from) {
    const to = readPalette(root)
    if (to) animateTheme(root, from, to)
  }
}
