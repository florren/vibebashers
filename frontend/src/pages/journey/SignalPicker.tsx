import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { api, type Signal } from '@/shared/api/client'
import { EntityFilter } from '@/shared/components/EntityFilter'
import { ErrorBox } from '@/shared/ui'

export function SignalPicker({ onSelect }: { onSelect: (ref: string) => void }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const result = useQuery({ queryKey: ['signals', 'journey-picker', query], queryFn: () => api<{ items?: Signal[] }>('/api/signals', { query: { q: query, run_id: 'all', limit: 30 } }), enabled: !!query })
  return <div className="border-b border-line p-3">
    <EntityFilter onChange={setQuery} />
    {query && result.isPending && <p role="status">{t('common.loading')}</p>}
    {result.isError && <ErrorBox error={result.error} />}
    {query && result.data && <ul aria-label={t('entityFilter.signals')} className="max-h-48 overflow-auto">
      {(result.data.items ?? []).map(s => <li key={s.id}><button className="btn btn-ghost w-full justify-start text-left" onClick={() => onSelect(s.public_id ?? `SIG-${String(s.id).padStart(6, '0')}`)}>{s.public_id} · {s.text?.slice(0, 120)}</button></li>)}
      {!result.data.items?.length && <li>{t('common.empty')}</li>}
    </ul>}
  </div>
}
