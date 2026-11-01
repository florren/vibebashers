import { useSyncExternalStore } from 'react'
import { create } from 'zustand'

export type DeviceMode = 'auto' | 'mobile' | 'desktop'
const KEY = 'cx.ui.device_mode'
const stored = localStorage.getItem(KEY)
const initial: DeviceMode = stored === 'mobile' || stored === 'desktop' ? stored : 'auto'
export const useDeviceMode = create<{ mode: DeviceMode; setMode: (mode: DeviceMode) => void }>(set => ({
  mode: initial,
  setMode: mode => { localStorage.setItem(KEY, mode); set({ mode }) },
}))
const query = '(max-width: 767px), (pointer: coarse) and (max-width: 1023px)'
const subscribe = (notify: () => void) => {
  const media = window.matchMedia(query)
  media.addEventListener('change', notify)
  return () => media.removeEventListener('change', notify)
}
export function useMobileLayout() {
  const mode = useDeviceMode(s => s.mode)
  const small = useSyncExternalStore(subscribe, () => window.matchMedia(query).matches)
  return mode === 'mobile' || (mode === 'auto' && small)
}

