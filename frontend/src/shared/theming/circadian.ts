/** Общий код runtime и inline bootstrap: без импортов, сети и побочных эффектов при загрузке. */
export const PHASES = ['dawn', 'morning', 'noon', 'sunset', 'twilight', 'night'] as const
export type ThemePhase = (typeof PHASES)[number]
export type CircadianPreferences = { source: 'sim' | 'real' | 'fixed'; fixed_phase: ThemePhase }
export type Coordinates = { latitude: number; longitude: number }
export const MOSCOW: Coordinates = { latitude: 55.7558, longitude: 37.6173 }
export const DEFAULT_CIRCADIAN: CircadianPreferences = { source: 'sim', fixed_phase: 'morning' }

export function validCircadian(value: unknown): CircadianPreferences | null {
  if (!value || typeof value !== 'object') return null
  const v = value as Record<string, unknown>
  return ['sim', 'real', 'fixed'].includes(String(v.source)) && PHASES.includes(v.fixed_phase as ThemePhase)
    ? { source: v.source as CircadianPreferences['source'], fixed_phase: v.fixed_phase as ThemePhase } : null
}
export function validCoordinates(value: unknown): Coordinates | null {
  if (!value || typeof value !== 'object') return null
  const v = value as Coordinates
  return Number.isFinite(v.latitude) && Math.abs(v.latitude) <= 90 && Number.isFinite(v.longitude) && Math.abs(v.longitude) <= 180
    ? { latitude: v.latitude, longitude: v.longitude } : null
}
export function readCircadian(): CircadianPreferences {
  try { return validCircadian(JSON.parse(localStorage.getItem('cx.ui.circadian') ?? 'null')) ?? { ...DEFAULT_CIRCADIAN } } catch { return { ...DEFAULT_CIRCADIAN } }
}
export function readCoordinates(): Coordinates {
  try { return validCoordinates(JSON.parse(localStorage.getItem('cx.ui.location') ?? 'null')) ?? MOSCOW } catch { return MOSCOW }
}

/** NOAA, General Solar Position Calculations. UTC; долгота положительна на восток. */
export function solarDay(time: number, coordinates: Coordinates = MOSCOW) {
  const { latitude, longitude } = validCoordinates(coordinates) ?? MOSCOW
  const localDate = new Date(time + longitude * 240_000)
  const year = localDate.getUTCFullYear()
  const midnight = Date.UTC(year, localDate.getUTCMonth(), localDate.getUTCDate())
  const day = (midnight - Date.UTC(year, 0, 1)) / 86_400_000 + 1
  const days = (Date.UTC(year + 1, 0, 1) - Date.UTC(year, 0, 1)) / 86_400_000
  const gamma = 2 * Math.PI / days * (day - 1)
  const eq = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma) - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma))
  const decl = 0.006918 - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma) - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma) - 0.002697 * Math.cos(3 * gamma) + 0.00148 * Math.sin(3 * gamma)
  const lat = latitude * Math.PI / 180
  const cosHour = Math.cos(90.833 * Math.PI / 180) / (Math.cos(lat) * Math.cos(decl)) - Math.tan(lat) * Math.tan(decl)
  const noon = midnight + (720 - 4 * longitude - eq) * 60_000
  if (cosHour <= -1) return { polar: 'day' as const, noon, sunrise: noon - 43_200_000, sunset: noon + 43_200_000 }
  if (cosHour >= 1) return { polar: 'night' as const, noon, sunrise: noon, sunset: noon }
  const halfDay = Math.acos(cosHour) * 180 / Math.PI * 240_000
  return { polar: null, noon, sunrise: noon - halfDay, sunset: noon + halfDay }
}

/** При 12-часовом дне границы соответствуют опорным 05/07/11/16/19/21. */
export function solarBoundaries(time: number, coordinates: Coordinates = MOSCOW) {
  const sun = solarDay(time, coordinates)
  const day = sun.sunset - sun.sunrise
  const night = 86_400_000 - day
  return { ...sun, boundaries: [sun.sunrise - night / 12, sun.sunrise + day / 12, sun.sunrise + 5 * day / 12, sun.sunrise + 10 * day / 12, sun.sunset + night / 12, sun.sunset + night / 4].map(Math.ceil) }
}
export function solarPhase(time: number, coordinates: Coordinates = MOSCOW): ThemePhase {
  if (!Number.isFinite(time)) return 'morning'
  const { polar, boundaries } = solarBoundaries(time, coordinates)
  if (polar) return polar === 'day' ? 'noon' : 'night'
  for (let i = 0; i < boundaries.length - 1; i++) if (time >= boundaries[i]! && time < boundaries[i + 1]!) return PHASES[i]!
  return 'night'
}
export function circadianPhase(preferences: CircadianPreferences, simTime?: string | null, now = Date.now(), coordinates = readCoordinates()): ThemePhase {
  if (preferences.source === 'fixed') return preferences.fixed_phase
  if (preferences.source === 'real') return solarPhase(now, coordinates)
  const time = Date.parse(simTime ?? localStorage.getItem('cx.ui.sim_time') ?? '')
  if (Number.isFinite(time)) return solarPhase(time, coordinates)
  const cached = localStorage.getItem('cx.ui.phase')
  return PHASES.includes(cached as ThemePhase) ? cached as ThemePhase : 'morning'
}

/** Вызывается до первого paint и при инициализации React из одного исходника. */
export function bootstrapCircadian() {
  try {
    const root = document.documentElement
    const storedPack = localStorage.getItem('cx.ui.theme_pack')
    const storedMode = localStorage.getItem('cx.ui.mode') ?? localStorage.getItem('cx.theme')
    const mode = ['light', 'dark', 'auto', 'circadian'].includes(storedMode ?? '') ? storedMode : 'light'
    const phase = circadianPhase(readCircadian())
    const resolved = mode === 'circadian' ? (phase === 'night' || phase === 'twilight' ? 'dark' : 'light') : mode === 'auto' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : mode
    const attributes = { pack: storedPack === 'ops' ? 'ops' : 'brand', mode: resolved ?? 'light', phase, circadian: String(mode === 'circadian'), density: localStorage.getItem('cx.ui.density') === 'compact' ? 'compact' : 'comfortable' }
    for (const [key, value] of Object.entries(attributes)) if (root.dataset[key] !== value) root.dataset[key] = value
    if (root.classList.contains('dark') !== (resolved === 'dark')) root.classList.toggle('dark', resolved === 'dark')
  } catch { /* Недоступное хранилище не должно мешать первому paint со светлой CSS-темой. */ }
}
