import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { UserRound } from 'lucide-react'
import { client360Query, useClient360Clock } from '@/pages/client/query'

/** Прогреваем общий кэш, пока сотрудник читает исходный сигнал/инцидент/HITL. */
export function ClientProfileLink(props: { id?: number | null; runId?: number | null; onOpen?: () => void }) {
  if (typeof props.id !== 'number' || !Number.isSafeInteger(props.id) || props.id <= 0) return null
  return <PrefetchedProfileLink {...props} id={props.id} />
}

function PrefetchedProfileLink({ id, runId, onOpen }: { id: number; runId?: number | null; onOpen?: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const clock = useClient360Clock()
  const current = clock.runId
  const scope = runId != null ? String(runId) : 'current'
  const prefetch = () => { if (scope === 'current' && !clock.ready) return; void qc.prefetchQuery(client360Query(id, scope, 72, current)) }
  useEffect(() => {
    if (scope === 'current' && !clock.ready) return
    void qc.prefetchQuery(client360Query(id, scope, 72, current))
  }, [qc, id, scope, current, clock.ready])
  return <Link className="btn btn-sm w-fit" to={`/clients/${id}?run_id=${scope}`} onPointerEnter={prefetch} onFocus={prefetch} onClick={event => { event.stopPropagation(); onOpen?.() }}>
    <UserRound size={14} aria-hidden /> {t('client360.open')}
  </Link>
}
