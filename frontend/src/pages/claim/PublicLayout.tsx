import { Link, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

/** Публичные обращения не показывают клиенту операторские инструменты. */
export function PublicLayout() {
  const { t, i18n } = useTranslation()
  return <div className="flex h-full min-h-0 flex-col bg-surface text-ink">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
      <Link to="/claim" className="font-semibold text-brand">{t('nav.claim')}</Link>
      <label className="flex items-center gap-2 text-sm">
        <span>{t('tracking.language')}</span>
        <select className="input" value={i18n.language.startsWith('en') ? 'en' : 'ru'} onChange={event => void i18n.changeLanguage(event.target.value)}>
          <option value="ru">Русский</option><option value="en">English</option>
        </select>
      </label>
    </header>
    <main className="min-h-0 flex-1 overflow-auto"><Outlet /></main>
  </div>
}
