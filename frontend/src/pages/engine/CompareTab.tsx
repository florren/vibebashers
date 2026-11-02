import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { post, type Classification, type AgentRunDetail } from '@/shared/api/client'
import type { paths } from '@/shared/api/types'
import { useAgentRun, useLlmProfiles, useRefs } from '@/shared/api/hooks'
import { Badge, Empty, ErrorBox, Json } from '@/shared/ui'
import i18n, { tEnum } from '@/shared/i18n'
import { comparisonFields, sourceOf } from './compareModel'

export type CompareInput = NonNullable<paths['/api/agent/compare']['post']['requestBody']>['content']['application/json']
export type CompareResult = paths['/api/agent/compare']['post']['responses'][200]['content']['application/json']
const EXAMPLES = ['sarcasm', 'irony', 'typos', 'indirect', 'multiple'] as const

/** Ручное диагностическое сравнение: одна явная отправка, без доменных side effects. */
export function CompareTab() {
  const { t, i18n: lang } = useTranslation()
  const channels = useRefs('channels'), profiles = useLlmProfiles(), qc = useQueryClient()
  const [text, setText] = useState(''), [channel, setChannel] = useState('chat')
  const [client, setClient] = useState(''), [profile, setProfile] = useState('')
  const compare = useMutation({
    mutationFn: async (body: CompareInput) => {
      const result = await post<CompareResult>('/api/agent/compare', body)
      if (!result?.llm || !result.mock) throw new Error(i18n.t('compare.invalidResponse'))
      return result
    },
    retry: false,
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['agent'] }) },
  })
  const active = (profiles.data ?? []).filter(p => p.is_active === true && p.id != null)
  const validClient = client === '' || (/^[1-9]\d*$/.test(client) && Number.isSafeInteger(Number(client)))
  const ready = text.trim().length >= 3 && text.length <= 5000 && validClient && !!channel && (profile === '' || active.some(p => String(p.id) === profile))
  const edit = (fn: () => void) => { compare.reset(); fn() }
  const submit = (event: React.FormEvent) => {
    event.preventDefault(); if (!ready || compare.isPending) return
    compare.mutate({ text: text.trim(), channel_code: channel, ...(client ? { client_id: Number(client) } : {}), ...(profile ? { llm_profile_id: Number(profile) } : {}) })
  }
  return <section className="relative min-w-0 space-y-4 p-3 md:p-4" data-testid="agent-compare" aria-label={t('compare.title')}>
    <header><h1 className="text-lg font-semibold">{t('compare.title')}</h1><p className="mt-1 text-sm text-muted">{t('compare.description')}</p></header>
    <form className="card space-y-3 p-4" onSubmit={submit}>
      <label className="grid gap-1 text-sm">{t('compare.text')}<textarea className="input min-h-28 resize-y py-2" value={text} disabled={compare.isPending} maxLength={5000} onChange={e => edit(() => setText(e.target.value))} /></label>
      <p className="text-xs text-muted">{t('compare.limit', { count: text.length })}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="grid min-w-0 gap-1 text-xs">{t('compare.channel')}<select className="input min-w-0" value={channel} disabled={compare.isPending} onChange={e => edit(() => setChannel(e.target.value))}>{!channels.data?.some(c => c.code === 'chat') && <option value="chat">{t('compare.chat')}</option>}{channels.data?.map(c => <option key={c.code} value={c.code}>{(lang.language === 'en' ? c.name_en : c.name_ru) ?? c.code}</option>)}</select></label>
        <label className="grid min-w-0 gap-1 text-xs">{t('compare.client')}<input className="input min-w-0" inputMode="numeric" value={client} placeholder={t('compare.optionalClient')} disabled={compare.isPending} onChange={e => edit(() => setClient(e.target.value))} /></label>
        <label className="grid min-w-0 gap-1 text-xs">{t('compare.profile')}<select className="input min-w-0" value={profile} disabled={compare.isPending || profiles.isPending} onChange={e => edit(() => setProfile(e.target.value))}><option value="">{t('compare.currentProfile')}</option>{active.map(p => <option key={p.id} value={p.id}>{p.code} · {p.model} · {p.provider}</option>)}</select></label>
      </div>
      {!validClient && <p role="alert" className="text-xs text-danger">{t('compare.invalidClient')}</p>}
      {channels.isError && <ErrorBox error={channels.error} />}{profiles.isError && <ErrorBox error={profiles.error} />}
      <div className="flex flex-wrap items-center gap-2"><button type="submit" className="btn btn-primary" disabled={!ready || compare.isPending}>{t(compare.isPending ? 'compare.pending' : 'compare.submit')}</button><span className="text-xs text-muted">{t('compare.noEffects')}</span></div>
      {compare.isPending && <p role="status" className="text-xs text-info">{t('compare.pendingHint')}</p>}
      {compare.isError && <ErrorBox error={compare.error} />}
    </form>
    <section className="card space-y-2 p-4" aria-label={t('compare.examplesTitle')}><h2 className="text-sm font-semibold">{t('compare.examplesTitle')}</h2><p className="text-xs text-muted">{t('compare.examplesHint')}</p><div className="flex flex-wrap gap-2">{EXAMPLES.map(code => <button key={code} className="btn btn-sm" disabled={compare.isPending} onClick={() => edit(() => setText(t(`compare.examples.${code}.text`)))}>{t(`compare.examples.${code}.label`)}</button>)}</div></section>
    {compare.data && !compare.isPending && <Results result={compare.data} />}
    {!compare.data && !compare.isPending && !compare.isError && <Empty title={t('compare.empty')} />}
  </section>
}
function Results({ result }: { result: CompareResult }) {
  const { t } = useTranslation()
  const left = useAgentRun(result.llm_run_id ?? null), right = useAgentRun(result.mock_run_id ?? null)
  if (!result.llm || !result.mock) return <Empty title={t('compare.invalidResponse')} />
  const rows = comparisonFields(result.llm, result.mock)
  const value = (classification: Classification, key: string) => {
    const raw = classification[key as keyof Classification]
    if (raw == null) return '—'
    const prefix = ({ signal_type: 'signal.type', cause_hypothesis: 'signal.type', criticality: 'incident.criticality', sentiment: 'signal.sentiment' } as Record<string, string>)[key]
    if (typeof raw === 'string' && prefix) return <span title={raw}>{tEnum(prefix, raw)}</span>
    if (typeof raw === 'number' && ['confidence', 'churn_risk', 'product_line_confidence'].includes(key)) return `${Math.round(key === 'churn_risk' ? raw : raw * 100)}%`
    return typeof raw === 'string' || typeof raw === 'number' ? String(raw) : <Json value={raw} className="max-h-40" />
  }
  return <section className="space-y-3" aria-label={t('compare.results')}>
    <p role="status" className="text-sm">{Array.isArray(result.diff) ? t(result.diff.length ? 'compare.differences' : 'compare.equal', { count: result.diff.length }) : t('compare.noDiff')}</p>
    <p className="text-xs text-muted">{t('compare.diffScope')}</p>
    <div className="grid min-w-0 gap-3 md:grid-cols-2">
      <ResultColumn title={t('compare.selected')} classification={result.llm} id={result.llm_run_id} trace={left.data} loading={left.isPending && !!result.llm_run_id} error={left.error} />
      <ResultColumn title={t('compare.mock')} classification={result.mock} id={result.mock_run_id} trace={right.data} loading={right.isPending && !!result.mock_run_id} error={right.error} />
    </div>
    <div className="card relative overflow-x-auto"><table className="w-full min-w-[650px] table-fixed text-left text-xs" aria-label={t('compare.fields')}><thead><tr className="border-b border-line"><th className="w-1/4 p-3">{t('compare.field')}</th><th className="p-3">{t('compare.selected')}</th><th className="p-3">{t('compare.mock')}</th></tr></thead><tbody>{rows.map(({ key, changed }) => <tr key={key} className={`border-b border-line ${changed ? 'bg-warn/10' : ''}`}><th className="break-words p-3 align-top font-normal">{t(`compare.fieldsLabels.${key}`, { defaultValue: key })}{changed && <span className="mt-1 block"><Badge tone="warn">{t('compare.changed')}</Badge></span>}</th><td className="break-words p-3 align-top">{value(result.llm!, key)}</td><td className="break-words p-3 align-top">{value(result.mock!, key)}</td></tr>)}</tbody></table></div>
    <details className="card p-3"><summary className="cursor-pointer text-xs">{t('compare.apiDiff')}</summary><Json value={result.diff} /></details>
  </section>
}
function ResultColumn({ title, classification, id, trace, loading, error }: { title: string; classification: Classification; id?: number; trace?: AgentRunDetail; loading: boolean; error: unknown }) {
  const { t } = useTranslation()
  const step = trace?.steps?.find(s => s.node === 'classify')
  const source = sourceOf(step?.model)
  return <article className="card min-w-0 space-y-3 p-4" aria-label={title}><header className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold">{title}</h2><Badge tone={source === 'mock' || step?.status === 'fallback' ? 'warn' : 'neutral'}>{t(`compare.source.${source}`)}</Badge>{step?.status === 'fallback' && <Badge tone="warn">{t('compare.fallback')}</Badge>}</header>
    <p className="break-words font-mono text-xs">{step?.model ?? (loading ? t('compare.traceLoading') : t('compare.noModel'))}</p>
    <div><h3 className="mb-1 text-xs text-muted">{t('compare.summary')}</h3><p className="whitespace-pre-wrap break-words text-sm">{classification.summary_ru || '—'}</p></div>
    <div><h3 className="mb-1 text-xs text-muted">{t('compare.rationale')}</h3><p className="whitespace-pre-wrap break-words text-sm">{classification.rationale_ru || '—'}</p></div>
    {id != null && <Link className="btn btn-sm" to={`/engine/${id}`}>{t('compare.trace', { id })}</Link>}{error != null && <ErrorBox error={error} />}
  </article>
}
