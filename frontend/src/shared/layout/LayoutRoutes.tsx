import { Navigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useUiTheme } from '@/shared/theming/store'
import { WorkspacePage } from '@/pages/workspace/WorkspacePage'

export function WorkspaceEntry() {
  const layout = useUiTheme(s => s.layout)
  const { search } = useLocation()
  if (layout !== 'v2') return <WorkspacePage />
  const destination = new URLSearchParams(search).has('tab') ? '/workspace' : '/overview'
  return <Navigate to={`${destination}${search}`} replace />
}

/** Прозрачная граница зависимостей T-255/T-242/T-249; здесь нет выдуманных метрик. */
export function PendingScreen({ title }: { title: string }) {
  const { t } = useTranslation()
  return <section className="mx-auto max-w-3xl space-y-4 p-6" aria-label={title}>
    <h1 className="text-2xl font-semibold">{title}</h1>
    <p>{t('shell.pending')}</p>
    <Link className="btn" to="/workspace?tab=signals">{t('shell.openWorkspace')}</Link>
  </section>
}
