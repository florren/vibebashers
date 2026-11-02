import { useLayoutEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useUiTheme } from './store'
import { resolveAttention } from './attention'

export function AttentionRuntime() {
  const { pathname } = useLocation()
  const attention = useUiTheme(s => s.attention)
  const pack = useUiTheme(s => s.theme_pack)
  useLayoutEffect(() => {
    document.documentElement.dataset.attention = resolveAttention(attention, pack, pathname)
    document.documentElement.dataset.alertException = String(/^\/(manager|compliance)(\/|$)/.test(pathname))
  }, [attention, pack, pathname])
  return null
}
