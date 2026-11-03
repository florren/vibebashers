import i18n from '@/shared/i18n'
import { useQuery } from '@tanstack/react-query'
import { api, ApiError, type Schemas } from './client'

export function validateMetricsRun(run: string): void {
  if (run === 'current' || run === 'all') return
  if (!/^[1-9][0-9]{0,18}$/.test(run) || BigInt(run) > 9223372036854775807n) {
    throw new ApiError(422, { title: i18n.t('overviewUi.invalidScope') }, 'Invalid run scope')
  }
}
export const useMetricsOverview = (requested: string) => useQuery({ queryKey: ['metrics', 'overview', requested], queryFn: ({ signal }) => {
  // qs опускает пустые строки: invalid scope обязан завершиться ДО fetch.
  validateMetricsRun(requested)
  return api<Schemas['MetricsOverview']>('/api/metrics/overview', { query: { run_id: requested }, signal })
}, refetchInterval: 8000 })
