import { slaWarning } from '@/shared/ui/sla'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '@/shared/api/client'
import type { paths } from '@/shared/api/types'
import { useUiTheme } from '@/shared/theming/store'
import { Badge } from '@/shared/ui'

type SettingsMap = paths['/api/settings']['get']['responses'][200]['content']['application/json']
/** Тихая UI-подсказка ТЗ 26.3; серверная политика sla_warning этим не меняется. */
export function SlaWarning({ due, status }: { due?: string | null; status?: string }) {
  const { t } = useTranslation()
  const simTime = useUiTheme(s => s.simTime)
  const settings = useQuery({ queryKey: ['attention-settings'], queryFn: () => api<SettingsMap>('/api/settings'), staleTime: 30_000 })
  const hours = slaWarning(due, simTime, status, settings.data?.sla_warn_hours)
  if (hours === null) return null
  return <Badge tone={hours < 0 ? 'danger' : 'warn'}>{hours < 0 ? t('attention.slaOverdue') : t('attention.slaSoon', { hours: Math.ceil(hours) })}</Badge>
}
