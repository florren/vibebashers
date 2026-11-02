import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useMetricsOverview } from '@/shared/api/overview'
import { Empty, ErrorBox, Skeleton } from '@/shared/ui'

/** Explicit run проверяется сервером до монтирования legacy дочерних queries. */
export function ScopedRunBoundary({ requested, children }: { requested: string; children: (resolved: string) => ReactNode }) {
  const { t } = useTranslation(), result = useMetricsOverview(requested)
  if (result.isError) return <ErrorBox error={result.error} />
  if (result.isPending) return <Skeleton className="m-4 h-32" />
  const scope = result.data.scope
  if (scope.current_missing || !scope.all_runs && scope.resolved_run_id == null) return <Empty title={t('overviewUi.noCurrent')} />
  return children(scope.all_runs ? 'all' : String(scope.resolved_run_id))
}
