import { EntityFilter } from '@/shared/components/EntityFilter'
import { IdLink } from '@/shared/components/IdLink'
import { clsx } from 'clsx'
import { BellRing, Check, ShieldAlert, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ComplianceAlert } from '@/shared/api/client'
import { useAckAlert, useComplianceAlerts } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtDateTime } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'

/** Экран /manager (B17/T-187): карточки алертов комплаенса на «устройстве руководителя», решение в один клик. */
export function ManagerPage() {
  const [entityQuery, setEntityQuery] = useState('')
  const { t } = useTranslation()
  const [branch, setBranch] = useState('')
  const [onlyOpen, setOnlyOpen] = useState(true)
  const q = useComplianceAlerts({ q: entityQuery || undefined, run_id: 'all', branch_code: branch || undefined, unacknowledged: onlyOpen || undefined, limit: 100 })
  const ack = useAckAlert()
  const items = q.data ?? []
  return (
    <div className="mx-auto flex h-full w-full max-w-2xl flex-col">
      <div className="manager-toolbar flex h-12 shrink-0 items-center gap-3 border-b border-line px-3">
        <ShieldAlert size={18} className="text-brand" />
        <div className="min-w-0">
          <div className="text-sm font-semibold">{t('manager.title')}</div>
          <div className="truncate text-[11px] text-muted">{t('manager.subtitle')}</div>
        </div>
        <input
          value={branch}
          onChange={(e) => setBranch(e.target.value.trim())}
          placeholder={t('manager.allBranches')}
          className="input ml-auto w-28 text-xs"
          aria-label={t('manager.branch')}
        />
        <label className="flex items-center gap-1 whitespace-nowrap text-xs text-muted">
          <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> {t('manager.onlyOpen')}
        </label>
      </div>
      <div className="p-3"><EntityFilter onChange={setEntityQuery} /></div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {q.isPending && <SkeletonRows />}
        {q.isError && <ErrorBox error={q.error} />}
        {q.data && items.length === 0 && <Empty title={t('manager.empty')} icon={<BellRing size={28} />} />}
        {items.map((a) => (
          <AlertCard key={a.id} a={a} onAck={(decision) => ack.mutate({ id: a.id!, decision })} busy={ack.isPending} />
        ))}
        {ack.isError && <ErrorBox error={ack.error} compact />}
      </div>
      <div className="shrink-0 border-t border-line px-3 py-1.5 text-[11px] text-muted">{t('manager.ackHelp')}</div>
    </div>
  )
}

function AlertCard({ a, onAck, busy }: { a: ComplianceAlert; onAck: (d: 'go' | 'false_positive' | 'open_incident') => void; busy: boolean }) {
  const { t } = useTranslation()
  const kind = a.kind ?? 'threshold'
  const tone = kind === 'immediate' ? 'danger' : kind === 'report' ? 'info' : 'warn'
  return (
    <article className={clsx('card border-l-4 p-3', kind === 'immediate' ? 'border-l-danger' : kind === 'report' ? 'border-l-brand' : 'border-l-warn')}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone}>{tEnum('compliance.alertKind', kind)}</Badge>
        <span className="text-sm font-semibold">{a.employee_display_name}</span>
        <span className="text-xs text-muted">
          ВСП {a.branch_code} · стол {a.desk_no}
        </span>
        {a.trigger_count != null && kind === 'threshold' && (
          <Badge tone="neutral">{t('manager.counter', { n: a.trigger_count, m: 3 })}</Badge>
        )}
        <span className="ml-auto text-[11px] text-muted">{fmtDateTime(a.sent_at)}</span>
      </div>
      {(a.patterns ?? []).length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {(a.patterns ?? []).map((p) => (
            <Badge key={p} tone="danger">
              {tEnum('compliance.pattern', p)}
            </Badge>
          ))}
        </div>
      )}
      {(a.quotes ?? []).length > 0 && (
        <ul className="mt-2 space-y-1 text-sm">
          {(a.quotes ?? []).slice(0, 3).map((qt, i) => (
            <li key={i} className="border-l-2 border-line pl-2 italic text-muted">
              «{qt}»
            </li>
          ))}
        </ul>
      )}
      {a.summary_ru && (
        <p className="mt-2 text-sm">
          <span className="text-muted">{t('manager.recommendation')}: </span>
          {a.summary_ru}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {a.incident_id && (
          <IdLink kind="incident" value={`INC-${String(a.incident_id).padStart(6, '0')}`} />
        )}
        {a.transcript_id && (
          <IdLink kind="transcript" value={`TR-${String(a.transcript_id).padStart(6, '0')}`} />
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
        {a.decision ? (
          <Badge tone={a.decision === 'false_positive' ? 'neutral' : 'ok'} title={a.acknowledged_by ? t('manager.by', { by: a.acknowledged_by }) : undefined}>
            {t('manager.decided', { d: tEnum('manager.decision', a.decision) })}
          </Badge>
        ) : kind === 'report' ? null : (
          <>
            <button className="btn btn-primary whitespace-nowrap" disabled={busy} onClick={() => onAck('go')}>
              <Check size={14} /> {t('manager.decision.go')}
            </button>
            <button className="btn btn-ghost whitespace-nowrap" disabled={busy} onClick={() => onAck('false_positive')}>
              <X size={14} /> {t('manager.decision.false_positive')}
            </button>
            <button className="btn btn-ghost whitespace-nowrap" disabled={busy} onClick={() => onAck('open_incident')}>
              <ShieldAlert size={14} /> {t('manager.decision.open_incident')}
            </button>
          </>
        )}
      </div>
    </article>
  )
}
