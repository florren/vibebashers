import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ErrorBox, KV, Section, Skeleton } from '@/shared/ui'
import { IdLink } from '@/shared/components/IdLink'
import type { BranchDetail } from './api'

export function BranchCard({ data, error, loading, runId, close }: { data: BranchDetail | undefined; error: unknown; loading: boolean; runId: string; close: () => void }) {
  const { t, i18n } = useTranslation()
  const noCurrent = data?.scope.run_ids?.length === 0
  const value = (number: number | null | undefined) => number == null ? t('branchMap.unknown') : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 3 }).format(number)
  return <Section title={data?.branch.code ?? t('branchMap.card')} right={<button className="btn btn-sm" onClick={close}>{t('common.close')}</button>}>
    {error != null && <ErrorBox error={error} compact />}
    {loading && <Skeleton className="m-3 h-24" />}
    {data && error == null && <>
      <p className="p-3 text-sm">{data.branch.name_ru}</p>
      {noCurrent && <p className="p-3 text-xs text-muted">{t('branchMap.noCurrent')}</p>}
      <KV k={t('branchMap.address')} v={data.branch.address_ru ?? t('branchMap.unknown')} />
      <KV k={t('branchMap.hours')} v={data.branch.hours_ru ?? t('branchMap.unknown')} />
      <KV k={t('branchMap.statusLabel')} v={t('branchMap.status.' + (data.branch.branch_status ?? 'unknown'))} />
      <KV k={t('branchMap.directSignals')} v={value(noCurrent ? null : data.signals.total)} />
      <KV k={t('branchMap.csiResponses')} v={value(noCurrent ? null : data.csi.coverage.complaints)} />
      <KV k={t('branchMap.sample')} v={`${value(data.csi.probabilities.sample_complaints)} / ${value(data.csi.probabilities.sample_visits)}`} />
      <p className="p-3 text-xs text-muted">{t('branchMap.directBasis')}</p>
      <Link className="block px-3 pb-3 text-sm text-brand hover:underline" to={`/trace/branch/${encodeURIComponent(data.branch.code)}?run_id=${encodeURIComponent(runId)}`}>{t('branchMap.trace')}</Link>
      <ul className="max-h-40 overflow-auto border-t border-line p-3">{data.signals.items.map(signal => <li key={signal.signal_ref}><IdLink kind="signal" value={signal.signal_ref} runId={runId} /></li>)}</ul>
      {!noCurrent && <p className="px-3 text-xs text-muted">{t('branchMap.signalPreview', { shown: data.signals.items.length, total: data.signals.total })}</p>}
      <p className="p-3 text-xs text-muted">{t('branchMap.snapshot', { time: data.scope.sim_time })}</p>
    </>}
  </Section>
}
