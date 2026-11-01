import { useLayoutEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useDeviceMode, useMobileLayout, type DeviceMode } from './device-store'


export function DeviceLayoutRuntime() {
  const mode = useDeviceMode(s => s.mode)
  const mobile = useMobileLayout()
  useLayoutEffect(() => {
    document.documentElement.dataset.device = mobile ? 'mobile' : 'desktop'
    document.documentElement.dataset.devicePreference = mode
    const viewport = document.querySelector<HTMLMetaElement>('meta[name="viewport"]')
    // Явный desktop на телефоне соответствует режиму «версия для компьютера» браузера.
    if (viewport) viewport.content = mode === 'desktop' ? 'width=1280' : 'width=device-width, initial-scale=1.0'
    return () => {
      delete document.documentElement.dataset.device
      delete document.documentElement.dataset.devicePreference
      if (viewport) viewport.content = 'width=device-width, initial-scale=1.0'
    }
  }, [mode, mobile])
  return null
}

export function DeviceSelector() {
  const { t } = useTranslation()
  const mode = useDeviceMode(s => s.mode)
  const setMode = useDeviceMode(s => s.setMode)
  return <label className="device-selector flex items-center gap-2 text-xs text-muted">
    <span>{t('device.label')}</span>
    <select className="input h-8 py-0 text-xs" value={mode} onChange={e => setMode(e.target.value as DeviceMode)}>
      {(['auto', 'mobile', 'desktop'] as const).map(value => <option key={value} value={value}>{t(`device.${value}`)}</option>)}
    </select>
  </label>
}
