import { AlertTriangle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { CabinetSignal, Overview } from './api'
import { Badge, Drawer, Empty } from '@/shared/ui'
import { IdLink } from '@/shared/components/IdLink'
import { SourcePlatformBadge } from '@/shared/components/SourcePlatformBadge'
import { SlaWarning } from '@/shared/components/SlaWarning'
import { fmtSimMoscow } from '@/shared/lib/format'
import { ROUTES } from '@/shared/routes'
import { tEnum } from '@/shared/i18n'

export function SignalLevel({ value }: { value: CabinetSignal['criticality'] }) {
  const { t } = useTranslation()
  return <Badge tone={value === 'high' ? 'danger' : value === 'medium' ? 'warn' : 'neutral'}>{value ? t(`cabinet.level.${value}`) : t('cabinet.unknown')}</Badge>
}
export function SignalLinks({ item, runId }: { item: CabinetSignal; runId: string }) {
  const { t } = useTranslation()
  return <div className="flex flex-wrap items-center gap-2"><IdLink kind="signal" value={item.public_id} runId={runId} /><Link className="text-brand underline text-sm" to={`${ROUTES.traceObject('signal', item.public_id)}?run_id=${encodeURIComponent(runId)}`}>{t('cabinet.showTrace')}</Link></div>
}
export function CabinetFeed({ rows, data, runId, onOpen }: { rows: CabinetSignal[]; data: Overview; runId: string; onOpen: (item: CabinetSignal) => void }) {
  const { t, i18n } = useTranslation()
  const lines = new Map(data.product_lines.map(row => [row.code, i18n.language.startsWith('en') ? row.name_en : row.name_ru]))
  const regions = new Map(data.regions.map(row => [row.code, i18n.language.startsWith('en') ? row.name_en : row.name_ru]))
  if (!rows.length) return <Empty title={t('cabinet.noSignals')} />
  return <ol className="grid gap-3 sm:grid-cols-2">{rows.map(item => <li key={item.id} className={`min-w-0 rounded border border-line bg-surface p-3 ${item.flags.includes('red_word') ? 'border-l-[4px] border-l-danger' : ''}`}>
    <div className="flex flex-wrap items-center gap-2"><SignalLevel value={item.criticality} />{item.flags.includes('red_word') && <span className="inline-flex items-center gap-1 text-danger text-sm"><AlertTriangle size={16} aria-hidden />{t('cabinet.redWords')}</span>}<SourcePlatformBadge platform={item.source_platform} /></div>
    <p className="mt-2 break-words text-sm">{item.summary}</p>
    <p className="mt-2 text-sm text-muted">{item.product_line_code ? lines.get(item.product_line_code) ?? item.product_line_code : t('cabinet.unassigned')} · {item.region_code ? regions.get(item.region_code) ?? item.region_code : t('cabinet.noGeo')}</p>
    <p className="text-sm text-muted">{tEnum('channel', item.channel_code)} · {tEnum('signal.status', item.status)} · {fmtSimMoscow(item.received_sim)} {t('attention.moscow')}</p>
    <SlaWarning due={item.sla_due_sim} />
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2"><SignalLinks item={item} runId={runId} /><button className="btn btn-sm" onClick={() => onOpen(item)}>{t('cabinet.openSignal')}</button></div>
  </li>)}</ol>
}
export function CabinetSignalDrawer({ item, onClose, runId }: { item: CabinetSignal | null; onClose: () => void; runId: string }) {
  const { t } = useTranslation()
  return <Drawer open={item !== null} onClose={onClose} title={t('cabinet.signalDetails')}>{item && <div className="space-y-4 p-4">
    <SignalLinks item={item} runId={runId} /><SignalLevel value={item.criticality} />
    <p className="break-words">{item.summary}</p><SourcePlatformBadge platform={item.source_platform} />
    <p className="text-sm">{tEnum('signal.status', item.status)} · {fmtSimMoscow(item.received_sim)} {t('attention.moscow')}</p>
    {item.red_words.length > 0 && <p className="border-l-[4px] border-l-danger pl-3 text-sm">{t('cabinet.redWords')}: {item.red_words.join(', ')}</p>}
    <SlaWarning due={item.sla_due_sim} />
    {item.client_public_id && <p><IdLink kind="client" value={item.client_public_id} runId={runId} /></p>}
    <ul className="space-y-2">{item.incidents.map(incident => <li key={incident.id}><IdLink kind="incident" value={incident.public_id} runId={runId} /> · {tEnum('incident.status', incident.status)}</li>)}</ul>
  </div>}</Drawer>
}
