import { useTranslation } from 'react-i18next'
import { useUiTheme } from './store'
import type { ThemeMode, ThemePack } from './types'

const PACKS: ThemePack[] = ['brand', 'ops']
const MODES: ThemeMode[] = ['light', 'dark', 'auto', 'circadian']

export function ThemeSelector({ className }: { className?: string }) {
  const { t } = useTranslation()
  const pack = useUiTheme((s) => s.theme_pack)
  const mode = useUiTheme((s) => s.mode)
  const setPack = useUiTheme((s) => s.setPack)
  const setMode = useUiTheme((s) => s.setMode)

  return (
    <div className={className ?? 'flex items-center gap-1'}>
      <label className="sr-only" htmlFor="theme-pack">{t('theme.packLabel')}</label>
      <select
        id="theme-pack"
        className="input h-7 py-0 text-xs"
        aria-label={t('theme.packLabel')}
        value={pack}
        onChange={(e) => setPack(e.target.value as ThemePack)}
      >
        {PACKS.map((p) => (
          <option key={p} value={p}>{t(`theme.pack.${p}`)}</option>
        ))}
      </select>
      <label className="sr-only" htmlFor="theme-mode">{t('theme.modeLabel')}</label>
      <select
        id="theme-mode"
        className="input h-7 py-0 text-xs"
        aria-label={t('theme.modeLabel')}
        value={mode}
        onChange={(e) => setMode(e.target.value as ThemeMode)}
      >
        {MODES.map((m) => (
          <option key={m} value={m}>{t(`theme.mode.${m}`)}</option>
        ))}
      </select>
    </div>
  )
}
