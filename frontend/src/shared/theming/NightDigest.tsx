import { useNight } from './night'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Signal } from '@/shared/api/client'
import { useWs } from '@/shared/ws/client'
import { IdLink } from '@/shared/components/IdLink'

export function NightDecoration() {
  return <div className="circadian-night-layer" aria-hidden="true" data-testid="night-decoration" />
}
export function NightDigest() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const liveRunId = useWs((s) => s.sim?.current_run_id ?? null)
  const [runRevision, setRunRevision] = useState(0)
  useEffect(() => useWs.subscribe((state, previous) => {
    const event = state.events[0]
    if (state.events !== previous.events && event?.topic === 'runs') setRunRevision(event.seq)
  }), [])
  const night = useNight()
  // Живые контуры руководителя и комплаенса сохраняют обычные приоритетные алерты.
  const enabled = night && !/^\/(manager|compliance)(\/|$)/.test(pathname)
  const query = { run_id: 'current', criticality: 'high', limit: 10 }
  const signals = useQuery({ queryKey: ['signals', 'list', query, 'night', liveRunId, runRevision], queryFn: async () => {
    const data = await api<{ items?: Signal[]; next_cursor?: string | null }>('/api/signals', { query })
    // В кеше digest не нужны тексты/контакты полного Signal DTO.
    return { items: data.items?.map(({ id, public_id }) => ({ id, public_id })), next_cursor: data.next_cursor }
  }, enabled, refetchInterval: enabled ? 30_000 : false })
  if (!enabled) return null
  return <>
    <NightDecoration />
    <details className="relative z-10 shrink-0 border-b border-line bg-surface px-3 py-1 text-xs" data-testid="night-digest">
      <summary className="cursor-pointer">{t('theme.circadian.digest')}</summary>
      <div className="max-h-32 overflow-auto py-2">
        {signals.isPending ? <p>{t('theme.circadian.loading')}</p> : signals.isError ? <p role="status">{t('theme.circadian.digestError')}</p> : <>
          {!signals.data.items?.length && <p>{t('theme.circadian.empty')}</p>}
          <ul className="flex flex-wrap gap-3">{signals.data.items?.map((signal) => <li key={signal.id}><IdLink kind="signal" value={signal.public_id} /></li>)}</ul>
          {signals.data.next_cursor && <p>{t('theme.circadian.more')}</p>}
        </>}
        <Link to="/" className="mt-1 inline-block text-brand hover:underline">{t('theme.circadian.openWorkspace')}</Link>
      </div>
    </details>
  </>
}
