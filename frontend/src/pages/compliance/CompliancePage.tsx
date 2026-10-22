import { clsx } from 'clsx'
import { FileUp, FolderInput, Mic, Send } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import type { TranscriptDetail, TranscriptReport } from '@/shared/api/client'
import { useComplianceStats, useImportTranscripts, useSendReport, useTranscript, useTranscriptReport, useTranscripts, useUploadTranscripts } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { LiveMeeting } from './LiveMeeting'
import { fmtDateTime } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows, Tabs } from '@/shared/ui'

type Tab = 'turns' | 'report' | 'stats'

/** Экран /compliance (B07/B17): транскрипты → реплики с подсветкой находок → отчёт → отправка руководителю. */
export function CompliancePage() {
  const { t } = useTranslation()
  const [sp, setSp] = useSearchParams()
  const selected = sp.get('id') ? Number(sp.get('id')) : null
  const select = (id: number) =>
    setSp(
      (p) => {
        p.set('id', String(id))
        return p
      },
      { replace: true },
    )
  const list = useTranscripts({ run_id: 'all', limit: 100 })
  const detail = useTranscript(selected)
  const [tab, setTab] = useState<Tab>('report')
  const upload = useUploadTranscripts()
  const imp = useImportTranscripts()
  const fileRef = useRef<HTMLInputElement>(null)
  const items = list.data?.items ?? []
  const [live, setLive] = useState(false)

  return (
    <div className="flex h-full">
      <aside className="flex w-96 shrink-0 flex-col border-r border-line">
        <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line px-3 text-xs">
          <span className="font-semibold uppercase tracking-wide text-muted">{t('compliance.transcripts')}</span>
          <span className="num ml-1 text-muted">{items.length}</span>
          <button className={clsx('btn btn-sm ml-auto whitespace-nowrap', live ? 'btn-primary' : 'btn-ghost')} onClick={() => setLive(true)} title={t('live.hintServer')}>
            <Mic size={14} /> {t('live.button')}
          </button>
          <button className="btn btn-ghost btn-sm whitespace-nowrap" onClick={() => fileRef.current?.click()} disabled={upload.isPending} title={t('compliance.uploadHint')}>
            <FileUp size={14} /> <span className="sr-only">{t('compliance.upload')}</span>
          </button>
          <button className="btn btn-ghost btn-sm whitespace-nowrap" onClick={() => imp.mutate()} disabled={imp.isPending} title={`${t('compliance.importCorpus')} · data/import/transcripts`}>
            <FolderInput size={14} /> <span className="sr-only">{t('compliance.importCorpus')}</span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".json,.txt"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? [])
              if (files.length) upload.mutate(files)
              e.target.value = ''
            }}
          />
        </div>
        {imp.data && (
          <div className="border-b border-line bg-raised px-3 py-1.5 text-[11px] text-muted">
            {t('compliance.imported', { found: imp.data.files_found, accepted: imp.data.accepted, duplicates: imp.data.duplicates, rejected: imp.data.rejected })}
          </div>
        )}
        {(upload.isError || imp.isError) && <ErrorBox error={upload.error ?? imp.error} compact />}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {list.isPending && <SkeletonRows />}
          {list.isError && <ErrorBox error={list.error} />}
          {list.data && items.length === 0 && <Empty title={t('common.empty')} hint={t('compliance.uploadHint')} />}
          <ul className="divide-y divide-line">
            {items.map((tr) => (
              <li key={tr.id}>
                <button onClick={() => select(tr.id!)} className={clsx('block w-full px-3 py-2 text-left hover:bg-raised', tr.id === selected && 'bg-brand-soft/50')}>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">{tr.public_id}</span>
                    <Badge tone={tr.status === 'done' ? 'ok' : tr.status === 'failed' ? 'danger' : 'info'}>{tEnum('compliance.status', tr.status)}</Badge>
                    <Badge tone="neutral">{tEnum('compliance.kind', tr.kind)}</Badge>
                    {(tr.findings_count ?? 0) > 0 && <Badge tone="warn">{tr.findings_count}</Badge>}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                    <span className="truncate">{tr.filename ?? tr.source}</span>
                    {tr.branch_code && <span>ВСП {tr.branch_code}</span>}
                    <span className="ml-auto">{tr.turns_count} ⟷</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-10 shrink-0 items-center gap-3 border-b border-line px-3">
          <Tabs<Tab> value={tab} onChange={setTab} items={[{ id: 'report', label: t('compliance.report') }, { id: 'turns', label: t('compliance.turns') }, { id: 'stats', label: t('compliance.stats') }]} />
          {detail.data && (
            <span className="ml-auto text-xs text-muted">
              {detail.data.public_id} · {tEnum('compliance.kind', detail.data.kind)} · {detail.data.branch_code ? `ВСП ${detail.data.branch_code}` : '—'} · {fmtDateTime(detail.data.received_at)}
            </span>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {live ? (
            <LiveMeeting onClose={() => setLive(false)} />
          ) : tab === 'stats' ? (
            <StatsTable />
          ) : selected == null ? (
            <Empty title={t('compliance.pick')} />
          ) : detail.isPending ? (
            <SkeletonRows />
          ) : detail.isError ? (
            <ErrorBox error={detail.error} />
          ) : tab === 'turns' ? (
            <Turns d={detail.data} />
          ) : (
            <Report d={detail.data} />
          )}
        </div>
      </main>
    </div>
  )
}

function Turns({ d }: { d: TranscriptDetail }) {
  const { t } = useTranslation()
  return (
    <ol className="mx-auto max-w-3xl space-y-1.5">
      {(d.turns ?? []).map((u) => {
        const bad = (u.findings ?? []).length > 0
        return (
          <li key={u.seq} className={clsx('flex gap-2', u.speaker === 'client' && 'flex-row-reverse')}>
            <div className={clsx('max-w-[80%] rounded-lg border px-3 py-1.5 text-sm', bad ? 'border-danger/60 bg-danger/10' : 'border-line bg-raised')}>
              <div className="mb-0.5 flex items-center gap-2 text-[11px] text-muted">
                <span className="num">#{u.seq}</span>
                <span>{tEnum('compliance.speaker', u.speaker)}</span>
                {(u.findings ?? []).map((f) => (
                  <Badge key={f.pattern_code} tone="danger" title={`${tEnum('compliance.family', f.family)} · ${f.confidence?.toFixed(2)}`}>
                    {tEnum('compliance.pattern', f.pattern_code)}
                  </Badge>
                ))}
              </div>
              <div>{u.text}</div>
            </div>
          </li>
        )
      })}
      {(d.turns ?? []).length === 0 && <Empty title={t('common.empty')} />}
    </ol>
  )
}

function Report({ d }: { d: TranscriptDetail }) {
  const { t } = useTranslation()
  const rep = useTranscriptReport(d.id ?? null, d.status === 'done')
  const send = useSendReport()
  if (d.status === 'failed') return <ErrorBox error={new Error(`${t('compliance.failed')}: ${d.error ?? ''}`)} />
  if (d.status !== 'done') return <Empty title={t('compliance.analyzing')} hint={tEnum('compliance.status', d.status)} />
  if (rep.isPending) return <SkeletonRows />
  if (rep.isError) return <ErrorBox error={rep.error} />
  const r: TranscriptReport = rep.data
  const steps = r.script_compliance?.steps ?? []
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <section className="card p-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t('compliance.overall')}</h3>
            <p className="mt-1 text-sm">{r.overall_ru}</p>
          </div>
          <Badge tone={r.findings.length ? 'warn' : 'ok'}>
            {t('compliance.confidence')} {r.confidence.toFixed(2)}
          </Badge>
          <button className="btn btn-primary shrink-0 whitespace-nowrap" onClick={() => send.mutate({ id: d.id! })} disabled={send.isPending}>
            <Send size={14} /> {t('compliance.sendReport')}
          </button>
        </div>
        {send.isSuccess && <div className="mt-2 text-xs text-ok">{t('compliance.sent')}</div>}
        {send.isError && <ErrorBox error={send.error} compact />}
      </section>
      <section className="card">
        <header className="flex h-9 items-center border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-muted">
          {t('compliance.findings')} <span className="num ml-2">{r.findings.length}</span>
        </header>
        {r.findings.length === 0 ? (
          <div className="p-3 text-sm text-muted">{t('compliance.noFindings')}</div>
        ) : (
          <ul className="divide-y divide-line">
            {r.findings.map((f, i) => (
              <li key={i} className="p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={f.alert_policy === 'immediate' ? 'danger' : 'warn'}>{tEnum('compliance.pattern', f.pattern_code)}</Badge>
                  <Badge tone="neutral">{tEnum('compliance.family', f.family)}</Badge>
                  <span className="text-[11px] text-muted">
                    {t('compliance.turn', { n: f.turn_seq })} · {t('compliance.confidence')} {f.confidence.toFixed(2)}
                  </span>
                  {f.alert_policy && <span className="ml-auto text-[11px] text-muted">{tEnum('compliance.alertKind', f.alert_policy)}</span>}
                </div>
                <blockquote className="mt-1.5 border-l-2 border-danger/60 pl-2 italic">«{f.quote}»</blockquote>
                <p className="mt-1 text-muted">{f.explanation_ru}</p>
                {f.fact_check && (
                  <div className="mt-1 rounded border border-line bg-raised px-2 py-1 text-xs">
                    <span className="font-semibold">{t('compliance.factCheck')}:</span> {t('compliance.claim')} — {f.fact_check.claim}; {t('compliance.truth')} — <b>{f.fact_check.truth}</b>
                    {f.fact_check.source_key && <span className="text-muted"> ({f.fact_check.source_key})</span>}
                  </div>
                )}
                <p className="mt-1">
                  <span className="text-muted">→ </span>
                  {f.recommendation_ru}
                  {f.training_module && <span className="text-muted"> · {f.training_module}</span>}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="card">
        <header className="flex h-9 items-center border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-muted">
          {t('compliance.script')} <span className="ml-2 font-mono normal-case">{r.script_compliance?.script_code}</span>
        </header>
        <ol className="flex flex-wrap gap-2 p-3">
          {steps.map((s) => (
            <li key={s.code} className="flex items-center gap-1.5 text-xs">
              <Badge tone={s.status === 'done' ? 'ok' : s.status === 'missed' ? 'danger' : 'neutral'}>{tEnum('compliance.step', s.code)}</Badge>
              <span className="text-muted">
                {tEnum('compliance.stepStatus', s.status)}
                {s.evidence_turn_seq ? ` · #${s.evidence_turn_seq}` : ''}
              </span>
            </li>
          ))}
        </ol>
      </section>
      <section className="card p-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t('compliance.actionPlan')}</h3>
        <p className="mt-1 text-sm">{r.action_plan_ru}</p>
      </section>
    </div>
  )
}

function StatsTable() {
  const { t } = useTranslation()
  const q = useComplianceStats({ run_id: 'all' })
  if (q.isPending) return <SkeletonRows />
  if (q.isError) return <ErrorBox error={q.error} />
  if (!q.data.length) return <Empty title={t('common.empty')} />
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
        <tr>
          <th className="px-2 py-1">ВСП</th>
          <th className="px-2 py-1">Сотрудник</th>
          <th className="num px-2 py-1 text-right">{t('compliance.sessions')}</th>
          <th className="num px-2 py-1 text-right">{t('compliance.triggers')}</th>
          <th className="num px-2 py-1 text-right">{t('compliance.alerts')}</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {q.data.map((r) => (
          <tr key={r.employee_id}>
            <td className="px-2 py-1 font-mono text-xs">{r.branch_code}</td>
            <td className="px-2 py-1">{r.display_name}</td>
            <td className="num px-2 py-1 text-right">{r.sessions}</td>
            <td className="num px-2 py-1 text-right">
              {r.triggers_confirmed}
              <span className="text-muted"> / {r.triggers_dismissed}</span>
            </td>
            <td className="num px-2 py-1 text-right">
              {r.alerts}
              {(r.false_alerts ?? 0) > 0 && <span className="text-muted"> ({r.false_alerts})</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
