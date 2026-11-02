import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { useNight } from '@/shared/theming/night'
import { NightDecoration } from '@/shared/theming/NightDigest'
import { IdLink } from '@/shared/components/IdLink'
import { signalsOptions, type CabinetScope, type CabinetHeaders, type SignalFilters } from './api'

/** В кабинете даже ночная сводка читает только тот же product/run/preset scope. */
export function CabinetNightDigest({ scope, headers, redWords }: { scope: CabinetScope; headers: CabinetHeaders; redWords?: SignalFilters['red_words'] }) {
  const night = useNight(), { t } = useTranslation(), location = useLocation()
  const query = useQuery({ ...signalsOptions({ ...scope, ...(redWords === undefined ? {} : { red_words: redWords }), sort: 'level', direction: 'desc', limit: 10 }, headers), enabled: night, refetchInterval: night ? 30_000 : false })
  const high = query.data?.items.filter(item => item.criticality === 'high') ?? []
  if (!night) return null
  const filters = new URLSearchParams(location.search); filters.set('sort', 'level'); filters.set('direction', 'desc'); filters.delete('offset')
  return <><NightDecoration /><details className="relative z-10 rounded border border-line bg-surface px-3 py-2 text-sm" data-testid="cabinet-night-digest">
    <summary className="cursor-pointer">{t('theme.circadian.digest')}</summary>
    <div className="max-h-32 space-y-2 overflow-auto py-2">{query.isPending ? <p>{t('theme.circadian.loading')}</p> : query.isError ? <p role="status">{t('theme.circadian.digestError')}</p> : <>
      {!high.length && <p>{t('theme.circadian.empty')}</p>}
      <ul className="flex flex-wrap gap-3">{high.map(item => <li key={item.id}><IdLink kind="signal" value={item.public_id} runId={scope.run_id} /></li>)}</ul>
      {high.length === 10 && query.data.next_offset != null && <p>{t('theme.circadian.more')}</p>}
    </>}
      <Link className="text-brand underline" to={{ pathname: location.pathname, search: filters.toString() }}>{t('theme.circadian.openWorkspace')}</Link>
    </div>
  </details></>
}
