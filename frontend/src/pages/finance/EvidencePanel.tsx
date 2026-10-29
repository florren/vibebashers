import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, post, type Schemas } from '@/shared/api/client'
import { ErrorBox, Skeleton } from '@/shared/ui'
import { fmtSim } from '@/shared/lib/format'
import { formatMoney } from './money'

type Assessment = Schemas['FinanceAssessment']
type Proof = Schemas['FinanceCaseProof']
type Detail = Schemas['FinancialImpactDetail']
type EvidenceBody = Schemas['FinanceEvidenceBody']
type Period = Schemas['FinancialImpactTotal']['period']

export function EvidencePanel({ runId, period, start, end }: { runId: number | null; period: Period; start: string; end: string }) {
  const { t } = useTranslation()
  const q = useQuery({
    queryKey: ['metrics', 'finance-assessment', runId, period, start, end],
    queryFn: () => api<Assessment>('/api/v1/finance/impact/assessment', { query: { run_id: runId ?? 'current', period,
      ...(period === 'custom' ? { start_date: `${start}:00Z`, end_date: `${end}:00Z` } : {}),
    } }), enabled: runId !== null, refetchInterval: 5000,
  })
  return <section className="card p-4" aria-label={t('financeProof.title')}>
    <h2 className="text-lg font-semibold">{t('financeProof.title')}</h2>
    <p className="my-2 text-xs text-muted">{t('financeProof.boundary')}</p>
    {runId === null && <p className="text-muted">{t('finance.empty')}</p>}
    {q.isLoading && <Skeleton className="h-32" />}
    {q.error && <ErrorBox error={q.error} />}
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">{q.data?.contours.map((c) => <div className="min-w-0 rounded-lg border border-line p-4" key={c.scope}>
      <h3 className="font-semibold">{t(`financeProof.scope.${c.scope}`)}</h3>
      <p className="my-2 text-xs text-muted">{t(`financeProof.scopeHint.${c.scope}`)}</p>
      <p className="text-xs text-muted">{t('financeProof.uniqueRisk')}</p>
      <p className="num my-2 text-3xl">{c.risk_total_rub === null ? t('financeProof.unknown') : formatMoney(c.risk_total_rub)}</p>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <dt className="text-muted">{t('finance.net')}</dt><dd className="num text-right">{c.net_rub === null ? '—' : formatMoney(c.net_rub)}</dd>
        <dt className="text-muted">{t('financeProof.fine')}</dt><dd className="num text-right">{c.fine_rub === null ? '—' : formatMoney(c.fine_rub)}</dd>
        <dt className="text-muted">{t('financeProof.combined')}</dt><dd className="num text-right">{c.combined_net_rub === null ? '—' : formatMoney(c.combined_net_rub)}</dd>
      </dl>
      <p className="mt-3 text-xs text-muted">{t('financeProof.coverage', { known: c.known_clients, unknown: c.unknown_clients, unidentified: c.unidentified_cases, duplicates: c.duplicate_cases })}</p>
      <p className="mt-2 text-xs text-muted">{t('financeProof.deals', { accepted: c.qualified_deals, excluded: c.excluded_deals })}</p>
      {c.risk_total_rub === null && <p className="mt-2 text-xs text-warn">{t('financeProof.partial', { amount: formatMoney(c.known_risk_rub) })}</p>}
      {c.calibration ? <div className="mt-3 break-words text-xs text-muted">
        <p>{c.calibration.id} · {c.calibration.model} · {c.calibration.score_pipeline}</p>
        <p>{t('financeProof.validation', { train: c.calibration.train_n, n: c.calibration.metrics.validation_n, raw: c.calibration.metrics.raw_brier.toFixed(4), calibrated: c.calibration.metrics.calibrated_brier.toFixed(4), ece: c.calibration.metrics.ece.toFixed(4) })}</p>
        <p className="mt-1">{t('financeProof.cutoff')}: {fmtSim(c.calibration.cutoff_sim)}</p>
        <p className="mt-1 font-mono">SHA256 {c.calibration.dataset_sha256}</p>
      </div> : <p className="mt-3 text-xs text-warn">{t('financeProof.noCalibration')}</p>}
      {c.fine_policy ? <p className="mt-2 break-words text-xs text-muted">{c.fine_policy.id} · {c.fine_policy.basis_ref}</p> : <p className="mt-2 text-xs text-warn">{t('financeProof.noPolicy')}</p>}
      {Object.keys(c.reasons).length > 0 && <details className="mt-3 text-xs"><summary className="cursor-pointer">{t('financeProof.exclusions')}</summary><ul className="mt-2 list-inside list-disc text-muted">{Object.entries(c.reasons).map(([reason, count]) => <li key={reason}>{t(`financeProof.reasons.${reason}`, { defaultValue: reason })}: {count}</li>)}</ul></details>}
    </div>)}</div>
  </section>
}

export function CaseEvidence({ detail }: { detail: Detail }) {
  const { t } = useTranslation()
  const proof = detail.proof
  if (!proof) return null
  return <section className="space-y-3 border-t border-line pt-3">
    <h3 className="font-semibold">{t('financeProof.provenance')}</h3>
    {proof.risks.map((risk) => <div className="rounded border border-line p-3" key={risk.scope}>
      <b>{t(`financeProof.scope.${risk.scope}`)}</b>
      <p>{risk.probability === null ? t('financeProof.unknown') : t('financeProof.probability', { p: (risk.probability * 100).toFixed(2) })} · {t(`financeProof.reasons.${risk.reason}`, { defaultValue: risk.reason })}</p>
      <p className="text-xs text-muted">{risk.model ?? '—'} · {risk.prompt_version ?? '—'} · {risk.score_pipeline ?? '—'} · {fmtSim(risk.predicted_sim)}</p>
      {risk.calibration_id && <p className="break-all text-xs text-muted">{risk.calibration_id} · SHA256 {risk.dataset_sha256}</p>}
    </div>)}
    {proof.records.length > 0 && <details><summary>{t('financeProof.history')}</summary><ul className="mt-2 space-y-2 text-xs text-muted">{proof.records.map((record) => <li key={record.id}>{t(`financeProof.scope.${record.scope}`)} · {record.deal_ref} · {t(`financeProof.outcomes.${record.outcome}`)} · {fmtSim(record.intervention_sim)} → {fmtSim(record.deal_closed_sim)} · {record.evidence_ref} · {record.recorded_by}</li>)}</ul></details>}
    {detail.incident_type === 'misselling' && <EvidenceForm detail={detail} proof={proof} />}
  </section>
}

function EvidenceForm({ detail, proof }: { detail: Detail; proof: Proof }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [scope, setScope] = useState<'demo' | 'observed'>('demo')
  const [deal, setDeal] = useState('')
  const [reference, setReference] = useState('')
  const [actor, setActor] = useState('demo_operator')
  const [intervention, setIntervention] = useState('')
  const [closed, setClosed] = useState('')
  const [outcome, setOutcome] = useState<EvidenceBody['outcome']>('unknown')
  const [alert, setAlert] = useState('')
  const [attempt, setAttempt] = useState<{ signature: string; key: string } | null>(null)
  const policy = proof.policies[scope]
  const save = useMutation({
    mutationFn: (body: EvidenceBody) => post<Schemas['FinanceEvidenceResult']>('/api/v1/finance/impact/evidence', body, { run_id: detail.run_id }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['metrics'] }) },
  })
  const valid = !!policy && !!deal.trim() && !!reference.trim() && !!actor.trim() && !!intervention && !!closed && !!alert
  return <details className="rounded border border-line p-3"><summary className="cursor-pointer font-medium">{t('financeProof.record')}</summary>
    <p className="my-2 text-xs text-muted">{t('financeProof.recordHint')}</p>
    <form className="grid gap-3" onChange={() => save.reset()} onSubmit={(event) => {
      event.preventDefault()
      if (!policy || !valid) return
      const fields = { scope, incident_id: detail.incident_id, alert_id: Number(alert), policy_id: policy.id, deal_ref: deal.trim(), evidence_ref: reference.trim(), recorded_by: actor.trim(), intervention_sim: `${intervention}:00Z`, deal_closed_sim: `${closed}:00Z`, outcome }
      const signature = JSON.stringify(fields)
      const key = attempt?.signature === signature ? attempt.key : crypto.randomUUID()
      setAttempt({ signature, key })
      save.mutate({ ...fields, idempotency_key: key })
    }}>
      <label>{t('financeProof.contour')}<select className="input mt-1 w-full" value={scope} onChange={(e) => { setScope(e.target.value as typeof scope); setActor(e.target.value === 'demo' ? 'demo_operator' : '') }}>{(['demo','observed'] as const).map((value) => <option key={value} value={value}>{t(`financeProof.scope.${value}`)}</option>)}</select></label>
      {!policy && <p className="text-xs text-warn">{t('financeProof.noPolicy')}</p>}
      <label>{t('financeProof.alert')}<select className="input mt-1 w-full" value={alert} onChange={(e) => setAlert(e.target.value)}><option value="">{t('financeProof.chooseAlert')}</option>{proof.alerts.map((a) => <option value={a.id} key={a.id}>{a.session_ref} · {a.decision ?? '—'}</option>)}</select></label>
      <label>{t('financeProof.deal')}<input required maxLength={120} className="input mt-1 w-full" value={deal} onChange={(e) => setDeal(e.target.value)} /></label>
      <label>{t('financeProof.intervention')}<input required type="datetime-local" className="input mt-1 w-full" value={intervention} onChange={(e) => setIntervention(e.target.value)} /></label>
      <label>{t('financeProof.closed')}<input required type="datetime-local" className="input mt-1 w-full" value={closed} onChange={(e) => setClosed(e.target.value)} /></label>
      <label>{t('financeProof.outcome')}<select className="input mt-1 w-full" value={outcome} onChange={(e) => setOutcome(e.target.value as typeof outcome)}>{(['unknown','prevented','completed'] as const).map((value) => <option key={value} value={value}>{t(`financeProof.outcomes.${value}`)}</option>)}</select></label>
      <label>{t('financeProof.reference')}<input required maxLength={500} className="input mt-1 w-full" value={reference} onChange={(e) => setReference(e.target.value)} /></label>
      <label>{t('financeProof.actor')}<input required maxLength={120} className="input mt-1 w-full" value={actor} onChange={(e) => setActor(e.target.value)} /></label>
      <button className="btn btn-primary" disabled={!valid || save.isPending}>{t('financeProof.save')}</button>
      {save.error && <ErrorBox error={save.error} />}{save.isSuccess && <p role="status" className="text-ok">{t('financeProof.saved')}</p>}
    </form>
  </details>
}
