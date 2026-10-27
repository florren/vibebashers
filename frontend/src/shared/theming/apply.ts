import type { ResolvedThemeMode, ThemeMode, ThemePack } from './types'

export function resolveMode(mode: ThemeMode): ResolvedThemeMode {
  if (mode === 'light' || mode === 'dark') return mode
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyUiTheme(pack: ThemePack, mode: ThemeMode) {
  const resolved = resolveMode(mode)
  const root = document.documentElement
  root.dataset.pack = pack
  root.dataset.mode = resolved
  root.classList.toggle('dark', resolved === 'dark')
}
