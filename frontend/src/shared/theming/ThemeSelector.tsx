import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { useUiTheme } from './store'
import type { ThemeDensity, ThemeMode, ThemePack } from './types'

const PACKS: ThemePack[] = ['brand', 'ops']
const MODES: ThemeMode[] = ['light', 'dark', 'auto', 'circadian']

export function ThemeSelector({ className }: { className?: string }) {
  const { t } = useTranslation()
  const id = useId()
  const density = useUiTheme((s) => s.density)
  const setDensity = useUiTheme((s) => s.setDensity)
  const syncError = useUiTheme((s) => s.syncError)
  const pack = useUiTheme((s) => s.theme_pack)
  const mode = useUiTheme((s) => s.mode)
  const setPack = useUiTheme((s) => s.setPack)
  const setMode = useUiTheme((s) => s.setMode)

  return (
    <div className={className ?? 'flex items-center gap-1'}>
      <label className="sr-only" htmlFor={`${id}-pack`}>{t('theme.packLabel')}</label>
      <select
        id={`${id}-pack`}
        className="input h-7 py-0 text-xs"
        aria-label={t('theme.packLabel')}
        value={pack}
        onChange={(e) => setPack(e.target.value as ThemePack)}
      >
        {PACKS.map((p) => (
          <option key={p} value={p}>{t(`theme.pack.${p}`)}</option>
        ))}
      </select>
      <label className="sr-only" htmlFor={`${id}-mode`}>{t('theme.modeLabel')}</label>
      <select
        id={`${id}-mode`}
        className="input h-7 py-0 text-xs"
        aria-label={t('theme.modeLabel')}
        value={mode}
        onChange={(e) => setMode(e.target.value as ThemeMode)}
      >
        {MODES.map((m) => (
          <option key={m} value={m}>{t(`theme.mode.${m}`)}</option>
        ))}
      </select>
      <select className="input h-7 py-0 text-xs" aria-label={t('theme.densityLabel')} value={density} onChange={(e) => setDensity(e.target.value as ThemeDensity)}>
        <option value="comfortable">{t('theme.density.comfortable')}</option>
        <option value="compact">{t('theme.density.compact')}</option>
      </select>
      {syncError && <span role="status" className="text-xs text-danger">{t('theme.syncError')}</span>}
    </div>
  )
}
