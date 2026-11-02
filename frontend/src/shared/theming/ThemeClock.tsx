import { useEffect } from 'react'
import { applyUiTheme } from './apply'
import { useUiTheme } from './store'

/** Локальные часы работают и на публичных страницах без операторского API/WS. */
export function ThemeClock() {
  const pack = useUiTheme((s) => s.theme_pack)
  const mode = useUiTheme((s) => s.mode)
  const density = useUiTheme((s) => s.density)
  const circadian = useUiTheme((s) => s.circadian)
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const reduced = matchMedia('(prefers-reduced-motion: reduce)')
    const apply = () => applyUiTheme(pack, mode, density, useUiTheme.getState().simTime, true)
    const stopMotion = () => { if (reduced.matches) applyUiTheme(pack, mode, density, useUiTheme.getState().simTime) }
    const timer = mode === 'circadian' && circadian.source === 'real' ? window.setInterval(apply, 1000) : null
    apply()
    media.addEventListener('change', apply)
    reduced.addEventListener('change', stopMotion)
    return () => { media.removeEventListener('change', apply); reduced.removeEventListener('change', stopMotion); if (timer !== null) clearInterval(timer) }
  }, [pack, mode, density, circadian])
  return null
}
