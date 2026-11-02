import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Signal } from '@/shared/api/client'
import { IdLink } from '@/shared/components/IdLink'

function currentNight() {
  const { circadian, phase } = document.documentElement.dataset
  return circadian === 'true' && phase === 'night'
}
export function NightDigest() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const [night, setNight] = useState(currentNight)
  useEffect(() => {
    const observer = new MutationObserver(() => setNight(currentNight()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-circadian', 'data-phase'] })
    return () => observer.disconnect()
  }, [])
  // Живые контуры руководителя и комплаенса сохраняют обычные приоритетные алерты.
  const enabled = night && !/^\/(manager|compliance)(\/|$)/.test(pathname)
  const query = { run_id: 'current', criticality: 'high', limit: 10 }
  const signals = useQuery({ queryKey: ['signals', 'list', query], queryFn: () => api<{ items?: Signal[]; next_cursor?: string | null }>('/api/signals', { query }), enabled, refetchInterval: enabled ? 30_000 : false })
  if (!enabled) return null
  return <>
    <div className="circadian-night-layer" aria-hidden="true" data-testid="night-decoration" />
    <details className="relative z-10 shrink-0 border-b border-line bg-surface px-3 py-1 text-xs" data-testid="night-digest">
      <summary className="cursor-pointer">{t('theme.circadian.digest')}</summary>
      <div className="max-h-32 overflow-auto py-2">
        {signals.isPending ? <p>{t('theme.circadian.loading')}</p> : signals.isError ? <p role="status">{t('theme.circadian.digestError')}</p> : <>
          {!signals.data.items?.length && <p>{t('theme.circadian.empty')}</p>}
          <ul className="flex flex-wrap gap-3">{signals.data.items?.map((signal) => <li key={signal.id}><IdLink kind="signal" value={signal.public_id} /></li>)}</ul>
          {signals.data.next_cursor && <p>{t('theme.circadian.more')}</p>}
        </>}
      </div>
    </details>
  </>
}
