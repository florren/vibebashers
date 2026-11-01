import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError } from '@/shared/api/client'
import { useRefs, useSimRuns } from '@/shared/api/hooks'
import { IdLink } from '@/shared/components/IdLink'
import { tEnum } from '@/shared/i18n'
import { fmtRub, fmtSim } from '@/shared/lib/format'
import { Badge, ErrorBox, KV, Section, Skeleton } from '@/shared/ui'
import { incidentStatusTone, signalStatusTone } from '@/shared/ui/tones'
import { SignalDrawer } from '@/pages/workspace/SignalDrawer'
import { useClient360 } from './query'

const text = (row: Record<string, unknown> | undefined, key: string) => typeof row?.[key] === 'string' ? row[key] as string : undefined
const number = (row: Record<string, unknown> | undefined, key: string) => typeof row?.[key] === 'number' && Number.isFinite(row[key]) ? row[key] as number : undefined
const object = (value: unknown): Record<string, unknown> | undefined => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined

export function Client360Page() {
  const { id: raw } = useParams()
  const id = raw && /^[1-9]\d*$/.test(raw) && Number.isSafeInteger(Number(raw)) ? Number(raw) : null
  const [params, setParams] = useSearchParams()
  const scope = params.get('run_id') || 'current'
  const hours = Number(params.get('ops_hours') || 72)
  return <Client360Profile id={id} runId={scope} hours={Number.isInteger(hours) && hours >= 1 && hours <= 720 ? hours : 72} onScope={(runId, opsHours) => setParams({ run_id: runId, ops_hours: String(opsHours) })} />
}

/** Профиль разделён на секции; те же query options используются для предварительной загрузки. */
export function Client360Profile({ id, runId, hours, onScope }: { id: number | null; runId: string; hours: number; onScope: (runId: string, hours: number) => void }) {
  const { t, i18n } = useTranslation()
  const en = i18n.language.startsWith('en')
  const query = useClient360(id, runId, hours)
  const runs = useSimRuns()
  const segments = useRefs('segments')
  const products = useRefs('products')
  const catalog = useRefs('gift_catalog')
  const [signalId, setSignalId] = useState<number | null>(null)
  const data = query.data
  const state = data?.current_state
  const closed = data?.incidents?.find(row => row.incident_type === 'account_closure')
  const departed = state?.state === 'churned' || data?.is_active === false
  const refName = (rows: { code: string; name_ru?: string; name_en?: string }[] | undefined, code: string | undefined) => {
    const row = rows?.find(item => item.code === code)
    return (en ? row?.name_en ?? row?.name_ru : row?.name_ru) ?? code ?? '—'
  }
  const fraction = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat(en ? 'en' : 'ru', { style: 'percent', maximumFractionDigits: 0 }).format(value)
  const moneyFormat = new Intl.NumberFormat(en ? 'en' : 'ru', { maximumFractionDigits: 2 })
  const operationMoney = (value: number | undefined) => value == null ? '—' : `${moneyFormat.format(value)} ₽`
  const stateName = (value: string | undefined) => t(`client360.states.${value}`, { defaultValue: t('client360.unknownState') })
  const notFound = id == null || query.error instanceof ApiError && query.error.status === 404
  const change = (scope: string, ops = hours) => onScope(scope, ops)
  return <div className="relative h-full overflow-y-auto p-3 md:p-5">
    <div className="mx-auto max-w-7xl space-y-4">
      <header className="space-y-3">
        <Link to="/?tab=signals" className="btn btn-sm">{t('common.back')}</Link>
        <div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold">{t('client360.title')}{data?.display_name ? ` · ${data.display_name}` : ''}</h1>{data && <IdLink kind="client" value={data.public_id} />}</div>
        <p className="text-sm text-muted">{t('client360.description')}</p>
        <div className="flex flex-wrap gap-3">
          <label className="text-sm">{t('client360.scope')}<select className="input ml-2 max-w-full" value={runId} onChange={event => change(event.target.value)}>
            <option value="current">{t('client360.currentScope')}</option><option value="all">{t('client360.allScope')}</option>
            {!['all', 'current'].includes(runId) && !runs.data?.items?.some(run => String(run.id) === runId) && <option value={runId}>{t('client360.runNumber', { id: runId })}</option>}
            {runs.data?.items?.map(run => <option key={run.id} value={run.id}>{run.label} · {t('client360.runNumber', { id: run.id })}</option>)}
          </select></label>
          <label className="text-sm">{t('client360.operationWindow')}<select className="input ml-2" value={hours} onChange={event => change(runId, Number(event.target.value))}>{![24, 72, 168].includes(hours) && <option value={hours}>{t('client360.hours', { count: hours })}</option>}{[24, 72, 168].map(value => <option key={value} value={value}>{t('client360.hours', { count: value })}</option>)}</select></label>
          <button className="btn btn-sm" disabled={query.isFetching || id == null} onClick={() => void query.refetch()}>{t('client360.refresh')}</button>
        </div>
        <p className="text-xs text-muted">{t('client360.scopeHint')} {t('client360.limitHint')}</p>
      </header>
      {notFound ? <section className="card p-4"><h2>{t('client360.notFound')}</h2></section> : <>
        {query.isPending && <section aria-busy="true" aria-label={t('client360.loading')} className="space-y-3"><Skeleton className="h-40" /><Skeleton className="h-48" /></section>}
        {query.isError && <div role="alert"><ErrorBox error={query.error} /><button className="btn mt-2" onClick={() => void query.refetch()}>{t('client360.retry')}</button></div>}
        {data && <>
          {departed && <section className="rounded-xl border border-danger/40 bg-danger/10 p-4" aria-label={t('client360.departed')}><h2 className="font-semibold">{t('client360.departed')}</h2>{closed?.id != null ? <Link className="mt-2 inline-block text-brand underline" to={`/incidents/${closed.id}`}>{t('client360.closureIncident')} · {closed.public_id}</Link> : <p className="mt-1 text-sm">{t('client360.noClosureInScope')}</p>}</section>}
          <Section title={t('client360.profile')}>
            <div className="grid gap-4 p-4 lg:grid-cols-3">
              <div><KV k={t('client360.segment')} v={refName(segments.data, data.segment_code)} /><KV k={t('client360.city')} v={data.city_name ?? '—'} /><KV k={t('client360.clv')} v={fmtRub(data.clv_estimate_rub)} />
                {['phone_masked', 'email_masked', 'phone', 'email'].map(key => text(data.contacts, key) && <KV key={key} k={t(key.includes('phone') ? 'client360.phone' : 'client360.email')} v={text(data.contacts, key)} />)}
                {text(data.contacts, 'preferred') && <KV k={t('client360.preferredChannel')} v={tEnum('channel', text(data.contacts, 'preferred'))} />}
              </div>
              <div className="space-y-2"><h2 className="font-semibold">{t('client360.state')}</h2><p><Badge>{stateName(state?.state)}</Badge></p><p className="text-xs text-muted">{fmtSim(state?.since_sim)}</p><KV k={t('client360.care')} v={fraction(state?.care_score)} />
                {data.churn_risk != null && <label className="block text-sm">{t('client360.churnRisk')} · {data.churn_risk}%<meter className="mt-1 block h-3 w-full" min={0} max={100} low={40} high={75} optimum={0} value={data.churn_risk} aria-label={t('client360.churnRisk')} /></label>}
              </div>
              <div className="space-y-2"><h2 className="font-semibold">{t('client360.communication')}</h2><p className="text-sm">{en ? data.psychotype?.name_en : data.psychotype?.name_ru}</p><p className="rounded-lg border-l-4 border-brand bg-raised p-3 text-sm leading-relaxed">{en ? t(`client360.hints.${data.psychotype?.code}`, { defaultValue: t('client360.hints.default') }) : data.psychotype?.communication_hint_ru ?? t('client360.hints.default')}</p></div>
            </div>
          </Section>
          <Section title={t('client360.products')}><ul className="divide-y divide-line">{!data.products?.length && <li className="p-4 text-sm text-muted">{t('client360.emptyProducts')}</li>}{data.products?.map((row, index) => <li key={number(row, 'id') ?? index} className="flex flex-wrap items-center justify-between gap-2 p-3"><span>{refName(products.data, text(row, 'product_code'))}</span><Badge>{t(`client360.productStatus.${text(row, 'status')}`, { defaultValue: text(row, 'status') ?? '—' })}</Badge>{text(row, 'card_last4') && <span className="font-mono text-sm">**** {text(row, 'card_last4')}</span>}</li>)}</ul></Section>
          {/* relative удерживает скрытые live-region IdLink внутри горизонтальной прокрутки. */}
          <Section title={t('client360.operations')}><div className="relative overflow-x-auto" tabIndex={0} role="region" aria-label={t('client360.operations')}><table className="w-full min-w-[660px] text-left text-sm"><thead className="bg-raised text-xs text-muted"><tr>{['time', 'product', 'operation', 'amount', 'status', 'fault', 'run'].map(key => <th scope="col" className="p-3" key={key}>{t(`client360.${key}`)}</th>)}</tr></thead><tbody>
            {!data.operations?.length && <tr><td colSpan={7} className="p-4 text-muted">{t('client360.emptyOperations')}</td></tr>}
            {data.operations?.map((row, index) => <tr key={number(row, 'id') ?? index} className={text(row, 'status') === 'failed' ? 'border-t border-line bg-danger/10' : 'border-t border-line'}><td className="p-3 whitespace-nowrap">{fmtSim(text(row, 'started_sim'), 'dd.MM.yyyy HH:mm')}</td><td className="p-3">{refName(products.data, text(row, 'product_code'))}</td><td className="p-3">{t(`client360.operationTypes.${text(row, 'op_type')}`, { defaultValue: text(row, 'op_type') ?? '—' })}<span className="mt-1 block"><IdLink kind="operation" value={number(row, 'id')} /></span></td><td className="p-3 whitespace-nowrap">{operationMoney(number(row, 'amount_rub'))}</td><td className="p-3"><Badge tone={text(row, 'status') === 'failed' ? 'danger' : 'neutral'}>{t(`client360.operationStatus.${text(row, 'status')}`, { defaultValue: text(row, 'status') ?? '—' })}</Badge></td><td className="p-3"><IdLink kind="fault" value={number(row, 'fault_id')} />{text(row, 'error_code') && <span className="mt-1 block font-mono text-xs">{text(row, 'error_code')}</span>}</td><td className="p-3"><IdLink kind="sim_run" value={text(row, 'run_public_id')} /></td></tr>)}
          </tbody></table></div></Section>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title={t('client360.signals')}><ul className="divide-y divide-line">{!data.signals?.length && <li className="p-4 text-sm text-muted">{t('client360.emptySignals')}</li>}{data.signals?.map(row => <li key={row.id} className="space-y-2 p-3"><div className="flex flex-wrap items-center gap-2"><IdLink kind="signal" value={row.public_id} /><Badge tone={signalStatusTone(row.status)}>{tEnum('signal.status', row.status)}</Badge><time dateTime={row.received_sim} className="text-xs text-muted">{fmtSim(row.received_sim, 'dd.MM.yyyy HH:mm')}</time></div><p className="line-clamp-2 text-sm">{row.text}</p><button className="btn btn-sm" disabled={row.id == null} onClick={() => setSignalId(row.id ?? null)}>{t('jury.openSignal')}</button></li>)}</ul></Section>
            <Section title={t('client360.incidents')}><ul className="divide-y divide-line">{!data.incidents?.length && <li className="p-4 text-sm text-muted">{t('client360.emptyIncidents')}</li>}{data.incidents?.map(row => <li key={row.id} className="space-y-2 p-3"><div className="flex flex-wrap items-center gap-2"><IdLink kind="incident" value={row.public_id} /><Badge tone={incidentStatusTone(row.status)}>{tEnum('incident.status', row.status)}</Badge></div><Link className="block text-sm text-brand hover:underline" to={`/incidents/${row.id}`}>{row.title}</Link>{row.incident_type === 'account_closure' && <Badge tone="danger">{t('client360.closureIncident')}</Badge>}</li>)}</ul></Section>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title={t('client360.history')}><ol className="space-y-3 p-4">{!data.state_history?.length && <li className="text-sm text-muted">{t('client360.emptyHistory')}</li>}{data.state_history?.map((row, index) => <li key={number(row, 'id') ?? index} className="border-l-2 border-brand pl-3"><p className="font-medium">{stateName(text(row, 'state'))}</p><time dateTime={text(row, 'since_sim')} className="text-xs text-muted">{fmtSim(text(row, 'since_sim'), 'dd.MM.yyyy HH:mm')}</time><p className="text-sm">{t(`client360.triggers.${text(row, 'trigger')}`, { defaultValue: t('client360.triggers.other') })} · {t('client360.care')}: {fraction(number(row, 'care_score'))}</p><div className="mt-1 flex flex-wrap gap-2"><IdLink kind="sim_run" value={text(row, 'run_public_id')} />{text(row, 'incident_public_id') && <IdLink kind="incident" value={text(row, 'incident_public_id')} />}</div></li>)}</ol></Section>
            <Section title={t('client360.gifts')}><ul className="divide-y divide-line">{!data.gifts?.length && <li className="p-4 text-sm text-muted">{t('client360.emptyGifts')}</li>}{data.gifts?.map(row => { const gift = object(row.payload?.gift); return <li key={row.id} className="space-y-2 p-3"><p className="font-medium">{refName(catalog.data, text(gift, 'gift_code')) !== '—' ? refName(catalog.data, text(gift, 'gift_code')) : row.gift_name ?? t('client360.gift')}</p><Badge tone={row.status === 'done' ? 'ok' : 'neutral'}>{t(`client360.giftStatus.${row.status}`, { defaultValue: row.status ?? '—' })}</Badge>{number(gift, 'points') != null && <p className="text-sm">{t('client360.points', { count: number(gift, 'points') })}</p>}<p className="text-xs text-muted">{fmtSim(row.resolved_sim ?? row.created_sim)}</p><IdLink kind="incident" value={row.incident_public_id} /></li> })}</ul></Section>
          </div>
        </>}
      </>}
    </div>
    <SignalDrawer id={signalId} onClose={() => setSignalId(null)} />
  </div>
}
