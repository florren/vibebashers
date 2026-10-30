import { clsx } from 'clsx'
import { Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Signal } from '@/shared/api/client'
import { useRefName, useSignalPages } from '@/shared/api/hooks'
import { Channel, SignalType, SignalStatus } from '@/shared/contracts/enums'
import { tEnum } from '@/shared/i18n'
import { fmtClock } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'
import { criticalityTone, sentimentTone, signalStatusTone } from '@/shared/ui/tones'

// enum-значения — из сгенерированных контрактов (scripts/gen_enums.py), не руками
const TYPES = Object.values(SignalType) as string[]
const STATUSES = Object.values(SignalStatus) as string[]
const CHANNELS = (Object.values(Channel) as string[]).filter((c) => !['voice_input', 'branch_audio', 'api', 'internal'].includes(c))

export function SignalsFeed({ runId, onOpen }: { runId: number | undefined; onOpen: (id: number) => void }) {
  const { t } = useTranslation()
  const [scope, setScope] = useState<'all' | 'current'>('all')
  const [q, setQ] = useState('')
  const [personalOnly, setPersonalOnly] = useState(false)
  const [types, setTypes] = useState<string[]>([])
  const [statuses, setStatuses] = useState<string[]>([])
  const [channels, setChannels] = useState<string[]>([])
  const query = useMemo(
    () => ({ run_id: scope === 'all' ? 'all' : runId ?? 'current', q: q || undefined, tag: personalOnly ? 'ui_pers_demo' : undefined, signal_type: types, status: statuses, channel: channels, limit: 100 }),
    [runId, scope, q, personalOnly, types, statuses, channels],
  )
  const list = useSignalPages(query)
  const items = list.data?.pages.flatMap(page => page.items ?? []) ?? []
  const segName = useRefName('segments')
  const hasFilters = personalOnly || q || types.length || statuses.length || channels.length

  return (
    <div className="flex h-full flex-col overflow-y-auto md:flex-row md:overflow-hidden">
      <aside className="max-h-[40vh] w-full shrink-0 space-y-4 overflow-y-auto border-b border-line p-3 md:max-h-none md:w-56 md:border-r">
        <label className="relative block">
          <Search size={13} className="pointer-events-none absolute left-2 top-2.5 text-faint" />
          <input className="input w-full pl-7" value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('continuity.signalSearch')} maxLength={200} placeholder={t('continuity.signalSearch')} />
        </label>
        <label className="block text-xs text-muted">{t('continuity.scope')}<select className="input mt-1 w-full" value={scope} onChange={e => setScope(e.target.value as typeof scope)}><option value="all">{t('continuity.allRuns')}</option><option value="current">{t('continuity.currentRun')}</option></select></label>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={personalOnly} onChange={e=>setPersonalOnly(e.target.checked)}/>ui_pers_demo</label>
        <FilterGroup title={t('common.type')} items={TYPES} value={types} onChange={setTypes} label={(c) => tEnum('signal.type', c)} />
        <FilterGroup title={t('common.status')} items={STATUSES} value={statuses} onChange={setStatuses} label={(c) => tEnum('signal.status', c)} />
        <FilterGroup title={t('common.channel')} items={CHANNELS} value={channels} onChange={setChannels} label={(c) => tEnum('channel', c)} />
        {hasFilters ? (
          <button
            className="btn btn-ghost btn-sm w-full"
            onClick={() => {
              setQ('')
              setPersonalOnly(false)
              setTypes([])
              setStatuses([])
              setChannels([])
            }}
          >
            <X size={12} /> {t('common.reset')}
          </button>
        ) : null}
      </aside>
      <div className="min-w-0 shrink-0 md:min-h-0 md:flex-1 md:overflow-y-auto">
        {list.isPending && <SkeletonRows n={8} />}
        {list.isError && <ErrorBox error={list.error} />}
        {list.data && items.length === 0 && <Empty title={t('common.empty')} />}
        {list.data && (
          <ul className="divide-y divide-line">
            {items.map((s) => (
              <SignalRow key={s.id} s={s} onOpen={onOpen} segName={segName} />
            ))}
          </ul>
        )}
        {list.hasNextPage && <button className="btn m-3" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>{t('continuity.more')}</button>}
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
          <span className="mb-1 block break-words font-mono text-xs text-info">{s.public_id}{s.run_public_id && ` · ${s.run_public_id}`}{(s.incident_refs ?? []).length > 0 && ` → ${s.incident_refs!.join(', ')}`}</span>
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
            {s.tags?.map(tag => <Badge key={tag} tone="info">{tag}</Badge>)}
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
