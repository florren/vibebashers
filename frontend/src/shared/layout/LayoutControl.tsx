import { useTranslation } from 'react-i18next'
import { useUiTheme } from '@/shared/theming/store'

export function LayoutControl() {
  const { t } = useTranslation()
  const layout = useUiTheme(s => s.layout), setLayout = useUiTheme(s => s.setLayout)
  return <label className="flex flex-wrap items-center gap-2 text-sm">{t('shell.layout')}
    <select className="input" value={layout} onChange={e => setLayout(e.target.value as 'legacy' | 'v2')}>
      <option value="legacy">{t('shell.legacy')}</option><option value="v2">{t('shell.v2')}</option>
    </select>
  </label>
}
