import { create } from 'zustand'
import { applyUiTheme, resolveMode } from './theming/apply'
import { useUiTheme } from './theming/store'
import type { ResolvedThemeMode, ThemeMode } from './theming/types'

type Theme = ResolvedThemeMode

/** Совместимость с T-007: resolved light/dark для иконок и тестов. */
export const useTheme = create<{ theme: Theme; toggle: () => void }>((set) => ({
  theme: resolveMode(useUiTheme.getState().mode),
  toggle: () => {
    const cur = resolveMode(useUiTheme.getState().mode)
    const next: ThemeMode = cur === 'dark' ? 'light' : 'dark'
    useUiTheme.getState().setMode(next)
    set({ theme: next })
  },
}))

useUiTheme.subscribe((state) => {
  useTheme.setState({ theme: resolveMode(state.mode) })
})

export function applyTheme(theme: Theme) {
  applyUiTheme(useUiTheme.getState().theme_pack, theme)
}

export { useUiTheme, bootstrapUiTheme } from './theming/store'
export { ThemeSelector } from './theming/ThemeSelector'
