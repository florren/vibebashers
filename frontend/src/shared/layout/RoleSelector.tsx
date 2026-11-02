import { useUndo } from '@/shared/ui/undo'
import { useTranslation } from 'react-i18next'
import { ROLE_CODES, useViewPreset, type ViewRole } from './preset'

export function RoleSelector() {
  const { t } = useTranslation()
  const { role, demonstrator, setRole, setDemonstrator } = useViewPreset()
  return <div className="flex min-w-0 flex-wrap items-center gap-2">
    <label className="flex min-w-0 items-center gap-2 text-xs">{t('shell.role')}
      <select className="input h-8 max-w-full text-xs" value={role} onChange={e => { const previous = { role, demonstrator }; setRole(e.target.value as ViewRole); useUndo.getState().offer(() => { setRole(previous.role); setDemonstrator(previous.demonstrator) }) }}>
        {ROLE_CODES.map(code => <option key={code} value={code}>{t(`shell.roles.${code}`)}</option>)}
      </select>
    </label>
    <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={demonstrator} onChange={e => { const previous = demonstrator; setDemonstrator(e.target.checked); useUndo.getState().offer(() => setDemonstrator(previous)) }} />{t('shell.demonstrator')}</label>
    <span className="sr-only">{t('shell.presetHint')}</span>
  </div>
}
