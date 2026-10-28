import { IdLink } from '@/shared/components/IdLink'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { useNotifications } from '@/shared/api/hooks'
import type { NotificationItem } from '@/shared/api/client'
import { fmtSim } from '@/shared/lib/format'
import { tEnum } from '@/shared/i18n'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'

const TYPES = ['all', 'client', 'team', 'public', 'cx'] as const

export function NotificationsTab({ runId }: { runId: number | undefined }) {
  const { t } = useTranslation()
  const [type, setType] = useState<(typeof TYPES)[number]>('all')
  const [open, setOpen] = useState<number | null>(null)
  const q = useNotifications({ run_id: runId, limit: 100, ...(type === 'all' ? {} : { recipient_type: type }) })
  const items = q.data?.items ?? []
  return (
    <div className="p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-muted">{t('notif.subtitle')}</div>
        <div className="flex overflow-hidden rounded border border-line text-xs">
          {TYPES.map((x) => (
            <button key={x} type="button" className={clsx('px-2 py-0.5', type === x ? 'bg-brand-strong text-on-brand' : 'text-muted hover:text-ink')} onClick={() => setType(x)}>
              {t(`notif.type.${x}`)}
            </button>
          ))}
        </div>
      </div>
      {q.error && <ErrorBox error={q.error} compact />}
      {q.isLoading && <SkeletonRows n={8} />}
      {!q.isLoading && items.length === 0 && <Empty title={t('notif.empty')} hint={t('notif.emptyHint')} />}
      <ul className="card divide-y divide-line">
        {items.map((n) => (
          <Row key={n.id} n={n} open={open === n.id} onToggle={() => setOpen(open === n.id ? null : (n.id ?? null))} />
        ))}
      </ul>
    </div>
  )
}

function Row({ n, open, onToggle }: { n: NotificationItem; open: boolean; onToggle: () => void }) {
  const { t } = useTranslation()
  const who = n.recipient_type === 'client' ? (n.client_name ?? (n.client_id ? `#${n.client_id}` : t('notif.unknownClient'))) : n.recipient_type === 'team' ? (n.team_code ?? t('notif.type.team')) : t(`notif.type.${n.recipient_type ?? 'cx'}`)
  return (
    <li className="cursor-pointer px-3 py-2 hover:bg-raised" onClick={onToggle}>
      <div className="flex items-center gap-2 text-sm">
        <span className="num w-20 shrink-0 text-xs text-muted">{fmtSim(n.sent_sim)}</span>
        <Badge tone={n.recipient_type === 'client' ? 'info' : n.recipient_type === 'public' ? 'warn' : 'neutral'}>{t(`notif.type.${n.recipient_type ?? 'cx'}`)}</Badge>
        <span className="w-40 shrink-0 truncate font-medium">{who}</span>
        <span className="shrink-0 text-xs text-muted">{tEnum('channel', n.channel_code)}</span>
        <span className={clsx('min-w-0 flex-1 text-muted', !open && 'truncate')}>{n.subject ? `${n.subject} — ` : ''}{open ? '' : n.body}</span>
        {n.incident_public_id && <IdLink kind="incident" value={n.incident_public_id} />}
        <Badge tone={n.status === 'sent' || n.status === 'delivered' ? 'ok' : n.status === 'failed' ? 'danger' : 'neutral'}>{tEnum('notifStatus', n.status)}</Badge>
      </div>
      {open && <pre className="mt-2 whitespace-pre-wrap rounded bg-raised p-2 font-sans text-sm leading-relaxed">{n.body}</pre>}
    </li>
  )
}
