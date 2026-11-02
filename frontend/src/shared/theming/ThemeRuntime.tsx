import { useEffect } from 'react'
import { useSimState } from '@/shared/api/hooks'
import { useWs } from '@/shared/ws/client'
import { connectThemeSettings } from './settings'
import { useUiTheme } from './store'

export function ThemeRuntime() {
  const sim = useSimState()
  const live = useWs((s) => s.sim)
  const simTime = live?.sim_time ?? sim.data?.sim_time ?? null
  useEffect(() => connectThemeSettings(), [])
  useEffect(() => useUiTheme.getState().setSimTime(simTime), [simTime])
  return null
}
