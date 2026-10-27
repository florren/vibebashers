import { create } from 'zustand'
import { applyUiTheme, resolveMode } from './apply'
import type { ThemeDensity, ThemeMode, ThemePack, ResolvedThemeMode } from './types'

const PACK_KEY = 'cx.ui.theme_pack'
const MODE_KEY = 'cx.ui.mode'
const DENSITY_KEY = 'cx.ui.density'

function readPack(): ThemePack {
  const v = localStorage.getItem(PACK_KEY)
  return v === 'ops' ? 'ops' : 'brand'
}

function readMode(): ThemeMode {
  const v = localStorage.getItem(MODE_KEY)
  if (v === 'dark' || v === 'light' || v === 'auto' || v === 'circadian') return v
  const legacy = localStorage.getItem('cx.theme')
  if (legacy === 'dark' || legacy === 'light') return legacy
  return 'light'
}

function readDensity(): ThemeDensity {
  return localStorage.getItem(DENSITY_KEY) === 'compact' ? 'compact' : 'comfortable'
}

type UiThemeState = {
  theme_pack: ThemePack
  mode: ThemeMode
  density: ThemeDensity
  setPack: (pack: ThemePack) => void
  setMode: (mode: ThemeMode) => void
  setDensity: (density: ThemeDensity) => void
  resolvedMode: () => ResolvedThemeMode
}

export const useUiTheme = create<UiThemeState>((set, get) => ({
  theme_pack: readPack(),
  mode: readMode(),
  density: readDensity(),
  resolvedMode: () => resolveMode(get().mode),
  setPack: (theme_pack) => {
    localStorage.setItem(PACK_KEY, theme_pack)
    set({ theme_pack })
    applyUiTheme(theme_pack, get().mode)
  },
  setMode: (mode) => {
    localStorage.setItem(MODE_KEY, mode)
    localStorage.setItem('cx.theme', resolveMode(mode))
    set({ mode })
    applyUiTheme(get().theme_pack, mode)
  },
  setDensity: (density) => {
    localStorage.setItem(DENSITY_KEY, density)
    set({ density })
  },
}))

export function bootstrapUiTheme() {
  const pack = readPack()
  const mode = readMode()
  applyUiTheme(pack, mode)
}
