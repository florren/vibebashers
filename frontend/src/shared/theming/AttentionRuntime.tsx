import { useViewPreset } from '@/shared/layout/preset'
import { useLayoutEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useUiTheme } from './store'
import { resolveAttention } from './attention'

export function AttentionRuntime() {
  const { pathname } = useLocation()
  const attention = useUiTheme(s => s.attention)
  const { role, demonstrator } = useViewPreset()
  const pack = useUiTheme(s => s.theme_pack)
  useLayoutEffect(() => {
    document.documentElement.dataset.attention = resolveAttention(attention, pack, pathname, demonstrator ? 'demonstrator' : role)
    document.documentElement.dataset.alertException = String(/^\/(manager|compliance)(\/|$)/.test(pathname))
  }, [attention, pack, pathname, role, demonstrator])
  return null
}
