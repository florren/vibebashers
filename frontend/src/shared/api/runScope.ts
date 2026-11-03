import i18n from '@/shared/i18n'
import { ApiError } from './client'

/** qs() опускает пустые строки; явный пустой run нельзя превратить в default. */
export function requireRunScope(runId: string): string {
  if (!runId.trim()) throw new ApiError(422, { title: i18n.t('common.emptyRunScope') }, 'Invalid run_id')
  return runId
}
