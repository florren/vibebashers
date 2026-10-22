import { clsx } from 'clsx'
import { Landmark, MessageSquareText, Send, Wallet } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { ExternalPost, ExternalPostDetail, LedgerEntry } from '@/shared/api/client'
import { useAbsAccounts, useFeed, useFeedStats, useManualReply, usePost, usePublishReview, useRefName } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtDateTime, fmtMs, fmtRub, fmtSim } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, KV, Section, SkeletonRows } from '@/shared/ui'

type Platform = 'review_portal' | 'telegram_channel'

/** Экран /feed (B16/T-176): эмулятор внешней площадки — отзывы, ответы агента, виджет «АБС (эмуляция)» (B06/T-171). */
export function FeedPage() {
  const { t } = useTranslation()
  const [platform, setPlatform] = useState<'' | Platform>('')
  const [selected, setSelected] = useState<number | null>(null)
  const list = useFeed({ run_id: 'all', platform: platform || undefined, limit: 60 })
  const stats = useFeedStats('all')
  const items = list.data?.items ?? []
  const current = selected ?? items[0]?.id ?? null
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-0 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="flex min-h-0 flex-col border-r border-line">
        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-3">
          <MessageSquareText size={18} className="text-brand" />
          <div className="min-w-0">
            <div className="text-sm font-semibold">{t('feed.title')}</div>
            <div className="truncate text-[11px] text-muted">{t('feed.subtitle')}</div>
          </div>
          <select value={platform} onChange={(e) => setPlatform(e.target.value as '' | Platform)} className="input ml-auto w-40 text-xs" aria-label={t('feed.platform')}>
            <option value="">{t('feed.allPlatforms')}</option>
            <option value="review_portal">{t('feed.platforms.review_portal')}</option>
            <option value="telegram_channel">{t('feed.platforms.telegram_channel')}</option>
          </select>
        </div>
        <StatsStrip s={stats.data} />
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <PostForm />
          {list.isPending && <SkeletonRows />}
          {list.isError && <ErrorBox error={list.error} />}
          {list.data && items.length === 0 && <Empty title={t('feed.empty')} hint={t('feed.emptyHint')} icon={<MessageSquareText size={28} />} />}
          <div className="space-y-2">
            {items.map((p) => (
              <PostCard key={p.id} p={p} active={p.id === current} onSelect={() => setSelected(p.id ?? null)} />
            ))}
          </div>
        </div>
      </div>
      <aside className="min-h-0 overflow-y-auto bg-raised/40 p-3">
        {current != null ? <PostDetail id={current} /> : <Empty title={t('feed.selectPost')} icon={<Wallet size={28} />} />}
      </aside>
    </div>
  )
}

function StatsStrip({ s }: { s?: { posts?: number; replied?: number; identified?: number; reply_latency_p50_ms?: number | null; refunded_rub?: number; autonomous_refunds?: number; hitl_refunds?: number } }) {
  const { t } = useTranslation()
  const cell = (k: string, v: string) => (
    <div className="min-w-0">
      <div className="truncate text-[10px] uppercase tracking-wide text-muted">{k}</div>
      <div className="truncate text-sm font-semibold tabular-nums">{v}</div>
    </div>
  )
  return (
    <div className="grid shrink-0 grid-cols-3 gap-3 border-b border-line px-3 py-2 sm:grid-cols-6">
      {cell(t('feed.stats.posts'), String(s?.posts ?? '—'))}
      {cell(t('feed.stats.replied'), String(s?.replied ?? '—'))}
      {cell(t('feed.stats.identified'), String(s?.identified ?? '—'))}
      {cell(t('feed.stats.p50'), s?.reply_latency_p50_ms != null ? fmtMs(s.reply_latency_p50_ms) : '—')}
      {cell(t('feed.stats.refunded'), s ? fmtRub(s.refunded_rub ?? 0) : '—')}
      {cell(t('feed.stats.autonomy'), s ? `${s.autonomous_refunds ?? 0} / ${s.hitl_refunds ?? 0}` : '—')}
    </div>
  )
}

function PostForm() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [platform, setPlatform] = useState<Platform>('review_portal')
  const [nick, setNick] = useState('@client_demo')
  const [last4, setLast4] = useState('')
  const [text, setText] = useState(t('feed.form.sample'))
  const pub = usePublishReview()
  const submit = () => {
    pub.mutate(
      { platform, author_nick: nick.trim(), text: text.trim(), mentions: last4 ? { card_last4: last4 } : undefined },
      { onSuccess: () => setOpen(false) },
    )
  }
  if (!open)
    return (
      <div className="mb-3 flex items-center gap-2">
        <button type="button" className="btn btn-primary btn-sm whitespace-nowrap" onClick={() => setOpen(true)}>
          <Send size={14} /> {t('feed.form.open')}
        </button>
        <span className="text-[11px] text-muted">{t('feed.form.hint')}</span>
      </div>
    )
  return (
    <form
      className="card mb-3 space-y-2 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <select value={platform} onChange={(e) => setPlatform(e.target.value as Platform)} className="input text-xs" aria-label={t('feed.platform')}>
          <option value="review_portal">{t('feed.platforms.review_portal')}</option>
          <option value="telegram_channel">{t('feed.platforms.telegram_channel')}</option>
        </select>
        <input value={nick} onChange={(e) => setNick(e.target.value)} className="input text-xs" placeholder="@nick" aria-label={t('feed.form.nick')} />
        <input
          value={last4}
          onChange={(e) => setLast4(e.target.value.replace(/\D/g, '').slice(0, 4))}
          className="input text-xs"
          placeholder={t('feed.form.last4')}
          aria-label={t('feed.form.last4')}
          inputMode="numeric"
        />
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} className="input w-full text-sm" aria-label={t('feed.form.text')} />
      <div className="flex items-center gap-2">
        <button type="submit" className="btn btn-primary btn-sm whitespace-nowrap" disabled={pub.isPending || text.trim().length < 10 || nick.trim().length < 3}>
          <Send size={14} /> {t('feed.form.publish')}
        </button>
        <button type="button" className="btn btn-ghost btn-sm whitespace-nowrap" onClick={() => setOpen(false)}>
          {t('common.close')}
        </button>
        <span className="text-[11px] text-muted">{t('feed.form.last4Hint')}</span>
      </div>
      {pub.isError && <ErrorBox error={pub.error} compact />}
    </form>
  )
}

const STATUS_TONE: Record<string, 'neutral' | 'info' | 'ok' | 'warn' | 'danger'> = {
  new: 'neutral',
  processing: 'info',
  replied: 'ok',
  escalated_to_dm: 'warn',
  ignored: 'neutral',
}

function PostCard({ p, active, onSelect }: { p: ExternalPost; active: boolean; onSelect: () => void }) {
  const { t } = useTranslation()
  const status = p.status ?? 'new'
  return (
    <article
      className={clsx('card cursor-pointer border-l-4 p-3 transition', active ? 'border-l-brand ring-1 ring-brand/40' : 'border-l-line hover:border-l-muted')}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={p.platform === 'telegram_channel' ? 'info' : 'neutral'}>{t(`feed.platforms.${p.platform ?? 'review_portal'}`)}</Badge>
        <span className="font-medium">{p.author_nick}</span>
        {p.author_client ? (
          <Badge tone="ok" title={t('feed.identifiedHint', { conf: Math.round((p.match_confidence ?? 0) * 100) })}>
            {t('feed.identified')} · {p.author_client.display_name}
          </Badge>
        ) : (
          <Badge tone="warn">{t('feed.anonymous')}</Badge>
        )}
        <Badge tone={STATUS_TONE[status] ?? 'neutral'}>{tEnum('feed.status', status)}</Badge>
        <span className="ml-auto text-muted">{fmtSim(p.posted_sim)}</span>
      </div>
      <p className="mt-2 text-sm leading-snug">{p.text}</p>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted">
        {p.signal_type && <span>{tEnum('signal.type', p.signal_type)}</span>}
        {p.replies_count ? <span>{t('feed.replies', { n: p.replies_count })}</span> : null}
        {p.agent_reply_latency_ms != null && <span>{t('feed.latency', { v: fmtMs(p.agent_reply_latency_ms) })}</span>}
        {p.incident_id && (
          <Link to={`/?incident=${p.incident_id}`} className="text-brand hover:underline" onClick={(e) => e.stopPropagation()}>
            {t('feed.incident', { id: p.incident_id })}
          </Link>
        )}
        <span className="ml-auto">{p.public_id}</span>
      </div>
    </article>
  )
}

function PostDetail({ id }: { id: number }) {
  const { t } = useTranslation()
  const q = usePost(id)
  const reply = useManualReply()
  const [draft, setDraft] = useState('')
  const d = q.data
  const clientId = d?.author_client?.id ?? null
  return (
    <div className="space-y-3">
      {q.isPending && <SkeletonRows n={4} />}
      {q.isError && <ErrorBox error={q.error} />}
      {d && (
        <>
          <Section title={t('feed.thread')}>
            <ol className="space-y-2">
              {(d.replies ?? []).length === 0 && <li className="text-xs text-muted">{t('feed.noReplies')}</li>}
              {(d.replies ?? []).map((r) => (
                <li key={r.id} className={clsx('rounded-lg p-2 text-sm', r.author === 'agent' ? 'bg-brand/10' : 'bg-raised')}>
                  <div className="mb-1 flex items-center gap-2 text-[11px] text-muted">
                    <Badge tone={r.author === 'agent' ? 'info' : 'neutral'}>{tEnum('feed.author', r.author ?? 'agent')}</Badge>
                    {r.latency_ms != null && <span>{t('feed.latency', { v: fmtMs(r.latency_ms) })}</span>}
                    {r.llm_source && <span>{r.llm_source}</span>}
                    <span className="ml-auto">{fmtDateTime(r.published_at)}</span>
                  </div>
                  {r.text}
                </li>
              ))}
            </ol>
            {d.effect_line_ru && <div className="mt-2 rounded-lg border border-ok/40 bg-ok/10 px-2 py-1 text-xs">{d.effect_line_ru}</div>}
            <form
              className="mt-2 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                reply.mutate({ id, text: draft.trim() }, { onSuccess: () => setDraft('') })
              }}
            >
              <input value={draft} onChange={(e) => setDraft(e.target.value)} className="input flex-1 text-xs" placeholder={t('feed.manualReply')} aria-label={t('feed.manualReply')} />
              <button type="submit" className="btn btn-ghost btn-sm whitespace-nowrap" disabled={reply.isPending || draft.trim().length < 5}>
                {t('feed.send')}
              </button>
            </form>
            {reply.isError && <ErrorBox error={reply.error} compact />}
          </Section>
          <Section title={t('feed.signalCard')}>
            <KV k={t('feed.post')} v={d.public_id} mono />
            <KV k={t('feed.signal')} v={d.signal_id ? `#${d.signal_id}` : '—'} mono />
            <KV k={t('feed.incidentK')} v={d.incident_public_id ? `${d.incident_public_id} · ${tEnum('incident.status', d.incident_status ?? '')}` : '—'} />
            <KV k={t('feed.matchConf')} v={d.match_confidence != null ? `${Math.round(d.match_confidence * 100)}%` : '—'} />
          </Section>
          <AbsWidget clientId={clientId} detail={d} />
        </>
      )}
    </div>
  )
}

function AbsWidget({ clientId, detail }: { clientId: number | null; detail: ExternalPostDetail }) {
  const { t } = useTranslation()
  const q = useAbsAccounts(clientId)
  const segName = useRefName('segments')
  const refundIds = new Set((detail.refunds ?? []).map((r) => r.id))
  return (
    <Section
      title={
        <span className="flex items-center gap-2">
          <Landmark size={14} /> {t('abs.title')}
        </span>
      }
      right={<span className="text-[10px] text-muted">{t('abs.badge')}</span>}
    >
      {clientId == null && <div className="text-xs text-muted">{t('abs.noClient')}</div>}
      {clientId != null && q.isPending && <SkeletonRows n={3} />}
      {q.isError && <ErrorBox error={q.error} compact />}
      {q.data && (
        <>
          <div className="mb-2 text-xs text-muted">
            {q.data.client?.display_name} · {segName(q.data.client?.segment_code)} · {q.data.client?.city_name ?? ''}
          </div>
          <div className="space-y-1">
            {(q.data.accounts ?? []).map((a) => (
              <div key={a.id} className="flex items-center justify-between rounded-lg bg-raised px-2 py-1 text-xs">
                <span className="font-mono">{a.number_masked}</span>
                <span className="text-muted">{tEnum('abs.accountStatus', a.status)}</span>
                <span className="font-semibold tabular-nums">{fmtRub(a.balance)}</span>
              </div>
            ))}
          </div>
          <div className="mt-2 text-[10px] uppercase tracking-wide text-muted">{t('abs.entries')}</div>
          <ul className="mt-1 max-h-72 space-y-0.5 overflow-y-auto">
            {(q.data.entries ?? []).map((e) => (
              <LedgerRow key={e.id} e={e} highlight={refundIds.has(e.id)} />
            ))}
          </ul>
        </>
      )}
    </Section>
  )
}

function LedgerRow({ e, highlight }: { e: LedgerEntry; highlight: boolean }) {
  const kind = e.kind ?? 'debit'
  const positive = kind === 'credit' || kind === 'refund' || kind === 'reversal'
  return (
    <li className={clsx('flex items-center gap-2 rounded px-1.5 py-0.5 text-[11px]', highlight && 'bg-ok/15 ring-1 ring-ok/40')}>
      <span className="w-[4.5rem] shrink-0 whitespace-nowrap text-muted">{fmtSim(e.posted_sim)}</span>
      <Badge tone={kind === 'refund' ? 'ok' : kind === 'fee' ? 'warn' : 'neutral'}>{tEnum('abs.kind', kind)}</Badge>
      <span className="min-w-0 flex-1 truncate" title={e.counterpart ?? ''}>
        {e.counterpart ?? (e.operation_id ? `#${e.operation_id}` : '')}
      </span>
      <span className={clsx('shrink-0 tabular-nums', positive ? 'text-ok' : '')}>
        {positive ? '+' : '−'}
        {fmtRub(e.amount)}
      </span>
    </li>
  )
}
