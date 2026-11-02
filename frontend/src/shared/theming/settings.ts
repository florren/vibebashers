import { api, patch } from '@/shared/api/client'
import { applyUiTheme } from './apply'
import { useUiTheme } from './store'
import { validCircadian, type CircadianPreferences } from './circadian'
import type { ThemeDensity, ThemeMode, ThemePack } from './types'

type Preferences = { theme_pack: ThemePack; mode: ThemeMode; density: ThemeDensity; circadian: CircadianPreferences }
const PENDING = 'cx.ui.pending'
let saveQueue = Promise.resolve()
const KEYS = ['theme_pack', 'mode', 'density', 'circadian'] as const

function validated(value: unknown): Partial<Preferences> {
  if (!value || typeof value !== 'object') return {}
  const obj = value as Record<string, unknown>
  const out: Partial<Preferences> = {}
  if (obj.theme_pack === 'brand' || obj.theme_pack === 'ops') out.theme_pack = obj.theme_pack
  if (['light', 'dark', 'auto', 'circadian'].includes(String(obj.mode))) out.mode = obj.mode as ThemeMode
  if (obj.density === 'compact' || obj.density === 'comfortable') out.density = obj.density
  const circadian = validCircadian(obj.circadian)
  if (circadian) out.circadian = circadian
  return out
}

/** PATCH содержит только изменённые ключи ui; локальные изменения побеждают запоздалый GET. */
export function connectThemeSettings(): () => void {
  let pending: Partial<Preferences>
  try { pending = validated(JSON.parse(localStorage.getItem(PENDING) ?? '{}')) } catch { pending = {} }
  // Подтверждение PATCH не делает запоздалый начальный GET актуальным.
  const localEdits: Partial<Preferences> = { ...pending }
  let active = true
  let hydrating = false
  const save = () => {
    saveQueue = saveQueue.then(async () => {
      if (!active || !Object.keys(pending).length) return
      const snapshot = { ...pending }
      try {
        await patch<void>('/api/settings', { ui: snapshot })
        if (!active) return
        for (const key of KEYS) if (pending[key] === snapshot[key]) delete pending[key]
        localStorage.setItem(PENDING, JSON.stringify(pending))
        if (active) useUiTheme.setState({ syncError: false })
      } catch {
        if (active) useUiTheme.setState({ syncError: true })
      }
    })
  }
  const unsubscribe = useUiTheme.subscribe((state, previous) => {
    if (hydrating) return
    const changed = Object.fromEntries(KEYS.filter((key) => state[key] !== previous[key]).map((key) => [key, state[key]]))
    if (!Object.keys(changed).length) return
    Object.assign(localEdits, changed)
    pending = { ...pending, ...changed }
    localStorage.setItem(PENDING, JSON.stringify(pending))
    save()
  })
  void api<{ ui?: unknown }>('/api/settings').then((settings) => {
    if (!active) return
    const preferences = { ...validated(settings.ui), ...localEdits, ...pending }
    hydrating = true
    useUiTheme.setState(preferences)
    const state = useUiTheme.getState()
    for (const key of KEYS) localStorage.setItem(`cx.ui.${key}`, typeof state[key] === 'string' ? state[key] : JSON.stringify(state[key]))
    applyUiTheme(state.theme_pack, state.mode, state.density, state.simTime)
    hydrating = false
    save()
  }).catch(() => { if (active) useUiTheme.setState({ syncError: true }) })
  return () => { active = false; unsubscribe() }
}
