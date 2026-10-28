import { useEffect } from 'react'
import { useSimState } from '@/shared/api/hooks'
import { useWs } from '@/shared/ws/client'
import { applyUiTheme } from './apply'
import { connectThemeSettings } from './settings'
import { useUiTheme } from './store'

export function ThemeRuntime() {
  const sim = useSimState()
  const live = useWs((s) => s.sim)
  const simTime = live?.sim_time ?? sim.data?.sim_time ?? null
  const pack = useUiTheme((s) => s.theme_pack)
  const mode = useUiTheme((s) => s.mode)
  const density = useUiTheme((s) => s.density)
  useEffect(() => connectThemeSettings(), [])
  useEffect(() => useUiTheme.getState().setSimTime(simTime), [simTime])
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => applyUiTheme(pack, mode, density, useUiTheme.getState().simTime)
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [pack, mode, density])
  return null
}
