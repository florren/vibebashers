import { clsx } from 'clsx'
import { Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Signal } from '@/shared/api/client'
import { useRefName, useSignals } from '@/shared/api/hooks'
import { Channel, SignalType } from '@/shared/contracts/enums'
import { tEnum } from '@/shared/i18n'
import { fmtClock } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'
import { criticalityTone, sentimentTone, signalStatusTone } from '@/shared/ui/tones'

// enum-значения — из сгенерированных контрактов (scripts/gen_enums.py), не руками
const TYPES = Object.values(SignalType) as string[]
const STATUSES = ['new', 'processing', 'awaiting_human', 'answered', 'linked', 'deferred', 'closed']
const CHANNELS = (Object.values(Channel) as string[]).filter((c) => !['voice_input', 'branch_audio', 'api', 'internal'].includes(c))

export function SignalsFeed({ runId, onOpen }: { runId: number | undefined; onOpen: (id: number) => void }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [statuses, setStatuses] = useState<string[]>([])
  const [channels, setChannels] = useState<string[]>([])
  const query = useMemo(
    () => ({ run_id: runId, q: q || undefined, signal_type: types, status: statuses, channel: channels, limit: 100 }),
    [runId, q, types, statuses, channels],
  )
  const list = useSignals(query)
  const segName = useRefName('segments')
  const hasFilters = q || types.length || statuses.length || channels.length

  return (
    <div className="flex h-full">
      <aside className="hidden w-56 shrink-0 space-y-4 overflow-y-auto border-r border-line p-3 md:block">
        <label className="relative block">
          <Search size={13} className="pointer-events-none absolute left-2 top-2.5 text-faint" />
          <input className="input w-full pl-7" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('common.search')} />
        </label>
        <FilterGroup title={t('common.type')} items={TYPES} value={types} onChange={setTypes} label={(c) => tEnum('signal.type', c)} />
        <FilterGroup title={t('common.status')} items={STATUSES} value={statuses} onChange={setStatuses} label={(c) => tEnum('signal.status', c)} />
        <FilterGroup title={t('common.channel')} items={CHANNELS} value={channels} onChange={setChannels} label={(c) => tEnum('channel', c)} />
        {hasFilters ? (
          <button
            className="btn btn-ghost btn-sm w-full"
            onClick={() => {
              setQ('')
              setTypes([])
              setStatuses([])
              setChannels([])
            }}
          >
            <X size={12} /> {t('common.reset')}
          </button>
        ) : null}
      </aside>
      <div className="min-w-0 flex-1 overflow-y-auto">
        {list.isPending && <SkeletonRows n={8} />}
        {list.isError && <ErrorBox error={list.error} />}
        {list.data && list.data.items?.length === 0 && <Empty title={t('common.empty')} />}
        {list.data && (
          <ul className="divide-y divide-line">
            {(list.data.items ?? []).map((s) => (
              <SignalRow key={s.id} s={s} onOpen={onOpen} segName={segName} />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

export function SignalRow({
  s,
  onOpen,
  segName,
  compact,
}: {
  s: Signal
  onOpen: (id: number) => void
  segName: (c: string | null | undefined) => string
  compact?: boolean
}) {
  const { t } = useTranslation()
  const c = s.classification
  const flags = (c?.flags ?? []) as string[]
  return (
    <li>
      <button
        onClick={() => s.id !== undefined && onOpen(s.id)}
        className={clsx('flex w-full items-start gap-3 px-3 text-left transition hover:bg-raised', compact ? 'py-1.5' : 'py-2')}
      >
        <span className="num w-11 shrink-0 pt-0.5 font-mono text-xs text-muted">{fmtClock(s.received_sim)}</span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <Badge tone="neutral">{tEnum('channel', s.channel_code)}</Badge>
            {c?.signal_type && <Badge tone="info">{tEnum('signal.type', c.signal_type)}</Badge>}
            {c?.criticality && c.criticality !== 'low' && <Badge tone={criticalityTone(c.criticality)}>{tEnum('incident.criticality', c.criticality)}</Badge>}
            {s.sentiment && s.sentiment !== 'neutral' && <Badge tone={sentimentTone(s.sentiment)}>{tEnum('signal.sentiment', s.sentiment)}</Badge>}
            {flags
              .filter((f) => f !== 'typos' && f !== 'slang')
              .map((f) => (
                <Badge key={f} tone={f === 'vip' ? 'brand' : 'warn'}>
                  {tEnum('signal.flags', f)}
                </Badge>
              ))}
            {s.origin && s.origin !== 'sim' && <Badge tone="neutral">{tEnum('signal.origin', s.origin)}</Badge>}
          </span>
          <span className={clsx('mt-1 block text-[13px] leading-snug', compact ? 'line-clamp-1' : 'line-clamp-2')}>{s.text}</span>
          <span className="mt-1 block truncate text-xs text-muted">
            {s.client
              ? `${s.client.display_name} · ${segName(s.client.segment_code)} · ${s.client.city_name ?? ''}`
              : s.external_contact?.nick
                ? `@${s.external_contact.nick}`
                : t('signal.noClient')}
          </span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
          <Badge tone={signalStatusTone(s.status)}>{tEnum('signal.status', s.status)}</Badge>
          {c?.confidence !== undefined && <span className="num text-[11px] text-faint">{Math.round(c.confidence * 100)}%</span>}
        </span>
      </button>
    </li>
  )
}

function FilterGroup({
  title,
  items,
  value,
  onChange,
  label,
}: {
  title: string
  items: string[]
  value: string[]
  onChange: (v: string[]) => void
  label: (c: string) => string
}) {
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c])
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((c) => (
          <button key={c} onClick={() => toggle(c)} className={clsx('chip', value.includes(c) && 'chip-on')}>
            {label(c)}
          </button>
        ))}
      </div>
    </div>
  )
}
