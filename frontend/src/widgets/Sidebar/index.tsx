import { useId } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useViewPreset } from '@/shared/layout/preset'
import { navigationFor, itemActive } from './navigation'

export function Sidebar({ onNavigate, onHelp }: { onNavigate?: () => void; onHelp: () => void }) {
  const { t } = useTranslation(), { pathname, search } = useLocation()
  const { role, demonstrator } = useViewPreset()
  const id = useId()
  return <nav className="v2-sidebar space-y-4 p-3" aria-label={t('shell.navigation')}>
    {navigationFor(role, demonstrator).map(group => <section key={group.id} aria-labelledby={`${id}-${group.id}`}>
      <h2 id={`${id}-${group.id}`} className="mb-1 text-xs font-semibold text-muted">{t(`shell.groups.${group.id}`)}</h2>
      <ul className="space-y-1">{group.items.map((item, index) => <li key={item.id}>
        <Link to={item.href} onClick={onNavigate} aria-current={itemActive(item, pathname, search) ? 'page' : undefined} className="flex min-h-10 items-center justify-between gap-2 rounded-lg border border-transparent px-2 py-2 text-sm hover:bg-raised aria-[current=page]:border-brand aria-[current=page]:bg-brand-soft">
          <span>{t(item.label)}</span>{group.id === 'operations' && <kbd className="kbd" aria-hidden="true">{index + 1}</kbd>}
        </Link>
      </li>)}</ul>
    </section>)}
    <div className="space-y-2 border-t border-line pt-3">
      <Link className="btn w-full" to="/setup" onClick={onNavigate}>{t('nav.settings')}</Link>
      <button className="btn w-full" onClick={() => { onNavigate?.(); onHelp() }}>{t('shell.shortcuts')}</button>
      <p className="text-xs text-muted">{t('shell.presetHint')}</p>
    </div>
  </nav>
}
