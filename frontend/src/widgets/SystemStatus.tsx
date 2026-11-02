import { ChevronDown } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '@/shared/api/client'
import type { paths } from '@/shared/api/types'
import { useDemoStatus } from '@/shared/api/hooks'
import { Badge } from '@/shared/ui'

type Health = paths['/api/health']['get']['responses'][200]['content']['application/json']
/** Поля health отражают готовность БД/конфигурации, а не результат внешнего LLM probe. */
export function SystemStatus() {
  const { t } = useTranslation()
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/api/health'), refetchInterval: 30_000 })
  const demo = useDemoStatus()
  return <section className="m-3 space-y-2 rounded-xl border border-line bg-surface p-3 text-xs" aria-label={t('shell.systemStatus')}>
    <details className="group"><summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2"><span className="font-semibold">{t('shell.systemStatus')}</span><Badge>{health.isError || demo.isError ? t('shell.unknown') : demo.data?.llm_mode ?? t('shell.unknown')}</Badge><ChevronDown size={14} aria-hidden="true" className="shrink-0 transition-transform duration-300 group-open:rotate-180" /></summary>
    <div className="space-y-2 pt-2">
    {health.isError || demo.isError ? <p role="status">{t('care.errors.service')}</p> : health.isPending || demo.isPending ? <p>{t('shell.statusLoading')}</p> : <>
      <p>{t('shell.service')}: {t(health.data.status === 'ok' ? 'shell.ready' : 'shell.degraded')}</p>
      <p>{t('shell.database')}: {t(health.data.db ? 'shell.available' : 'shell.unavailable')}</p>
      <p className="flex flex-wrap items-center gap-2">{t('shell.agent')}: <Badge tone="neutral">{demo.data.llm_mode ?? t('shell.unknown')}</Badge></p>
      <p>{t('shell.channels')}: STT {demo.data.stt_mode ?? t('shell.unknown')} · Telegram {t(`shell.telegram.${health.data.tgbot ?? 'unknown'}`)}</p>
      <p className="text-muted">{t('shell.configurationHint')}</p>
    </>}
    </div></details>
  </section>
}
