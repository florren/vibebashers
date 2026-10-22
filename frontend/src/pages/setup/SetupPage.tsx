import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { clsx } from 'clsx'
import { Check, ChevronLeft, ChevronRight, Download, Upload } from 'lucide-react'
import {
  useEconomicsSettings,
  useFinishSetup,
  useGenerateStatus,
  useGifts,
  useImportSettings,
  useLlmProfiles,
  useLlmProfileOps,
  usePsychotypes,
  useRefs,
  useRoutingRules,
  useSaveSetting,
  useSaveSetup,
  useSetupPayload,
  useSetupStatus,
  useSlaMatrix,
  useStartGenerate,
  useTemplates,
  useTestLlm,
  useTestTgBot,
  useSttProviders,
  useSttTest,
} from '@/shared/api/hooks'
import type { EconomicsSettingsT, GiftCatalogItem, LlmProfileT, NotificationTemplateT, PsychotypeSettings, RoutingRule, SetupPayload, SlaCell } from '@/shared/api/client'
import { tEnum } from '@/shared/i18n'
import { Badge, ErrorBox, Section, SkeletonRows } from '@/shared/ui'
import { EnvEditor } from './EnvEditor'

const STEP_KEYS = ['llm', 'bank', 'sim', 'channels', 'policies', 'sla', 'economics', 'templates', 'generate'] as const
type StepKey = (typeof STEP_KEYS)[number]
const ALL_CHANNELS = ['chat', 'call', 'email', 'telegram', 'social', 'branch', 'review_portal', 'abs']

export function SetupPage() {
  const { t } = useTranslation()
  const [sp, setSp] = useSearchParams()
  const status = useSetupStatus()
  const payload = useSetupPayload()
  const [step, setStep] = useState<number>(() => Math.max(0, (Number(sp.get('step')) || 1) - 1))
  useEffect(() => {
    if (!sp.get('step') && status.data) setStep(Math.max(0, (status.data.current_step ?? 1) - 1))
  }, [status.data, sp])
  const go = (i: number) => {
    const n = Math.min(STEP_KEYS.length - 1, Math.max(0, i))
    setStep(n)
    setSp({ step: String(n + 1) }, { replace: true })
  }
  const done = new Set(status.data?.steps_done ?? [])
  const key: StepKey = STEP_KEYS[step] ?? 'llm'
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">{t('setup.title')}</h1>
        {status.data?.completed ? <Badge tone="ok">{t('setup.completed')}</Badge> : <Badge tone="warn">{t('setup.notCompleted')}</Badge>}
        <ExportImport />
      </div>
      <ol className="flex flex-wrap gap-1 text-xs">
        {STEP_KEYS.map((k, i) => (
          <li key={k}>
            <button
              className={clsx('flex items-center gap-1 rounded-full border px-2.5 py-1', i === step ? 'border-brand bg-brand text-white' : done.has(i + 1) ? 'border-ok/40 bg-ok/10 text-ink' : 'border-line text-muted hover:text-ink')}
              onClick={() => go(i)}
            >
              {done.has(i + 1) && i !== step ? <Check size={11} /> : <span className="num">{i + 1}</span>}
              {t(`setup.steps.${k}`)}
            </button>
          </li>
        ))}
      </ol>
      {payload.error && <ErrorBox error={payload.error} />}
      {payload.isLoading && <SkeletonRows n={6} />}
      {payload.data && (
        <div className="card p-4">
          <h2 className="mb-1 text-base font-semibold">{t(`setup.steps.${key}`)}</h2>
          <p className="mb-3 text-sm text-muted">{t(`setup.hint.${key}`)}</p>
          {key === 'llm' && <StepLlm p={payload.data} />}
          {key === 'bank' && <StepBank p={payload.data} />}
          {key === 'sim' && <StepSim p={payload.data} />}
          {key === 'channels' && <StepChannels p={payload.data} />}
          {key === 'policies' && <StepPolicies p={payload.data} />}
          {key === 'sla' && <StepSla />}
          {key === 'economics' && <StepEconomics />}
          {key === 'templates' && <StepTemplates />}
          {key === 'generate' && <StepGenerate completed={!!status.data?.completed} />}
        </div>
      )}
      <div className="flex items-center justify-between">
        <button className="btn btn-sm" disabled={step === 0} onClick={() => go(step - 1)}>
          <ChevronLeft size={14} /> {t('setup.prev')}
        </button>
        <button className="btn btn-sm" disabled={step === STEP_KEYS.length - 1} onClick={() => go(step + 1)}>
          {t('setup.next')} <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}

function SaveBar({ pending, error, ok, onSave, label }: { pending: boolean; error: unknown; ok: boolean; onSave: () => void; label?: string }) {
  const { t } = useTranslation()
  return (
    <div className="mt-3 flex items-center gap-2">
      <button className="btn btn-sm btn-primary" disabled={pending} onClick={onSave}>
        {label ?? t('setup.save')}
      </button>
      {ok && <span className="text-xs text-ok">{t('setup.saved')}</span>}
      {!!error && <ErrorBox error={error} compact />}
    </div>
  )
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs text-muted">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-faint">{hint}</span>}
    </label>
  )
}

// ---- 1. LLM --------------------------------------------------------------
function StepLlm({ p }: { p: SetupPayload }) {
  const { t } = useTranslation()
  const profiles = useLlmProfiles()
  const profOps = useLlmProfileOps()
  const test = useTestLlm()
  const save = useSaveSetup()
  const [llm, setLlm] = useState(p.llm ?? {})
  const [newProf, setNewProf] = useState<LlmProfileT>({ code: '', provider: 'openai_compatible', model: '', role: 'bench_only', base_url: null })
  const [testId, setTestId] = useState<number | null>(null)
  const byRole = (role: string) => (profiles.data ?? []).find((x) => x.role === role && x.is_active)
  useEffect(() => {
    if (profiles.data && !llm.main_profile_id) setLlm({ main_profile_id: byRole('main')?.id, fast_profile_id: byRole('fast')?.id, twin_profile_id: byRole('twin')?.id })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profiles.data])
  const sel = (k: 'main_profile_id' | 'fast_profile_id' | 'twin_profile_id') => (
    <select className="input h-8 text-sm" value={llm[k] ?? ''} onChange={(e) => setLlm({ ...llm, [k]: Number(e.target.value) || undefined })}>
      <option value="">—</option>
      {(profiles.data ?? []).map((x) => (
        <option key={x.id} value={x.id}>
          {x.code} · {x.provider} · {x.model}
        </option>
      ))}
    </select>
  )
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t('setup.llm.main')}>{sel('main_profile_id')}</Field>
        <Field label={t('setup.llm.fast')}>{sel('fast_profile_id')}</Field>
        <Field label={t('setup.llm.twin')}>{sel('twin_profile_id')}</Field>
      </div>
      <SaveBar pending={save.isPending} error={save.error} ok={save.isSuccess} onSave={() => save.mutate({ llm })} />

      <Section title={t('setup.llm.profiles')}>
        <table className="w-full text-xs">
          <thead className="text-left text-[11px] uppercase text-muted">
            <tr>
              <th className="px-3 py-1">code</th>
              <th className="px-3 py-1">{t('setup.llm.provider')}</th>
              <th className="px-3 py-1">{t('setup.llm.model')}</th>
              <th className="px-3 py-1">{t('setup.llm.role')}</th>
              <th className="px-3 py-1" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {(profiles.data ?? []).map((x) => (
              <tr key={x.id} className={clsx(!x.is_active && 'opacity-50')}>
                <td className="px-3 py-1 font-mono">{x.code}</td>
                <td className="px-3 py-1">{x.provider}</td>
                <td className="px-3 py-1">{x.model}</td>
                <td className="px-3 py-1">{x.role}</td>
                <td className="flex justify-end gap-1 px-3 py-1">
                  <button className="btn btn-sm" disabled={test.isPending} onClick={() => { setTestId(x.id ?? null); test.mutate({ provider: x.provider, model: x.model, base_url: x.base_url ?? undefined }) }}>
                    {t('setup.llm.test')}
                  </button>
                  <button className="btn btn-sm" onClick={() => profOps.save.mutate({ ...x, id: x.id ?? 0, is_active: !x.is_active })}>
                    {x.is_active ? t('setup.llm.deactivate') : t('setup.llm.activate')}
                  </button>
                  <button className="btn btn-sm" onClick={() => profOps.remove.mutate(x.id ?? 0)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {test.data && (
          <div className={clsx('mx-3 my-2 rounded border px-2 py-1 text-xs', test.data.ok ? 'border-ok/40 bg-ok/10' : 'border-danger/40 bg-danger/10')}>
            {t('setup.llm.testResult', { id: testId ?? '' })}: {test.data.ok ? `OK · ${test.data.latency_ms} мс · ${test.data.model_reported ?? ''}` : test.data.error}
            {test.data.quota && Object.keys(test.data.quota).length > 0 && <span className="text-muted"> · {JSON.stringify(test.data.quota)}</span>}
          </div>
        )}
        {profOps.remove.error && <ErrorBox error={profOps.remove.error} compact />}
        <div className="flex flex-wrap items-end gap-2 border-t border-line p-3">
          <Field label="code"><input className="input h-8 w-32 text-xs" value={newProf.code} onChange={(e) => setNewProf({ ...newProf, code: e.target.value })} /></Field>
          <Field label={t('setup.llm.provider')}>
            <select className="input h-8 text-xs" value={newProf.provider} onChange={(e) => setNewProf({ ...newProf, provider: e.target.value as LlmProfileT['provider'] })}>
              <option value="openai_compatible">openai_compatible</option>
              <option value="gigachat">gigachat</option>
              <option value="mock">mock</option>
            </select>
          </Field>
          <Field label={t('setup.llm.model')}><input className="input h-8 w-56 text-xs" value={newProf.model} onChange={(e) => setNewProf({ ...newProf, model: e.target.value })} /></Field>
          <Field label="base_url"><input className="input h-8 w-56 text-xs" value={newProf.base_url ?? ''} onChange={(e) => setNewProf({ ...newProf, base_url: e.target.value || null })} /></Field>
          <Field label={t('setup.llm.role')}>
            <select className="input h-8 text-xs" value={newProf.role} onChange={(e) => setNewProf({ ...newProf, role: e.target.value as LlmProfileT['role'] })}>
              {['main', 'fast', 'twin', 'bench_only'].map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </Field>
          <button className="btn btn-sm" disabled={!newProf.code || !newProf.model || profOps.add.isPending} onClick={() => profOps.add.mutate(newProf)}>
            {t('setup.llm.addProfile')}
          </button>
          {profOps.add.error && <ErrorBox error={profOps.add.error} compact />}
        </div>
      </Section>

      <EnvEditor
        keys={['LLM_PROVIDER', 'LLM_CHAIN', 'GIGACHAT_AUTH_KEY_1', 'GIGACHAT_AUTH_KEY_2', 'GIGACHAT_MODEL', 'GIGACHAT_SCOPE', 'GIGACHAT_VERIFY_SSL', 'OPENROUTER_API_KEY', 'OPENROUTER_BASE_URL', 'LOCAL_LLM_BASE_URL', 'LLM_RECORD']}
        title={t('setup.llm.env')}
        note={t('setup.llm.envNote')}
      />
    </div>
  )
}

// ---- 2. Bank --------------------------------------------------------------
function StepBank({ p }: { p: SetupPayload }) {
  const { t } = useTranslation()
  const save = useSaveSetup()
  const segments = useRefs('segments')
  const regions = useRefs('regions')
  const [bank, setBank] = useState(p.bank ?? {})
  const shares = bank.segment_shares ?? {}
  const sum = Object.values(shares).reduce((a, b) => a + (Number(b) || 0), 0)
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t('setup.bank.name')}><input className="input h-8" value={bank.name ?? ''} onChange={(e) => setBank({ ...bank, name: e.target.value })} /></Field>
        <Field label={t('setup.bank.profile')} hint={t('setup.bank.profileHint')}>
          <select className="input h-8" value={bank.clients_profile ?? 'demo'} onChange={(e) => setBank({ ...bank, clients_profile: e.target.value as 'lite' | 'demo' | 'stress' })}>
            <option value="lite">lite · 1 000</option>
            <option value="demo">demo · 10 000</option>
            <option value="stress">stress · 50 000</option>
          </select>
        </Field>
        <Field label={t('setup.bank.regions')}>
          <select className="input h-8" value={bank.regions_mode ?? 'all'} onChange={(e) => setBank({ ...bank, regions_mode: e.target.value })}>
            <option value="all">{t('setup.bank.regionsAll')}</option>
            <option value="selected">{t('setup.bank.regionsSelected')}</option>
          </select>
        </Field>
      </div>
      {bank.regions_mode === 'selected' && (
        <Field label={t('setup.bank.regionCodes')}>
          <select multiple className="input text-xs" style={{ height: 160 }} value={bank.region_codes ?? []} onChange={(e) => setBank({ ...bank, region_codes: Array.from(e.target.selectedOptions).map((o) => o.value) })}>
            {(regions.data ?? []).map((r) => <option key={r.code} value={r.code}>{r.name_ru}</option>)}
          </select>
        </Field>
      )}
      <Section title={t('setup.bank.shares')} right={<span className={clsx('text-xs', Math.abs(sum - 1) < 0.01 || sum === 0 ? 'text-muted' : 'text-danger')}>Σ = {sum.toFixed(2)}</span>}>
        <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-3">
          {(segments.data ?? []).map((s) => (
            <Field key={s.code} label={s.name_ru}>
              <input className="input h-8 text-xs" type="number" step="0.01" min="0" max="1" value={shares[s.code] ?? ''} placeholder={String(s.population_share ?? '')} onChange={(e) => setBank({ ...bank, segment_shares: { ...shares, [s.code]: Number(e.target.value) } })} />
            </Field>
          ))}
        </div>
      </Section>
      <SaveBar pending={save.isPending} error={save.error} ok={save.isSuccess} onSave={() => save.mutate({ bank })} />
    </div>
  )
}

// ---- 3. Sim ---------------------------------------------------------------
function StepSim({ p }: { p: SetupPayload }) {
  const { t } = useTranslation()
  const save = useSaveSetup()
  const [sim, setSim] = useState(p.sim ?? {})
  const inten = sim.intensities ?? {}
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t('setup.sim.seed')} hint={t('setup.sim.seedHint')}><input className="input h-8" type="number" value={sim.seed ?? 42} onChange={(e) => setSim({ ...sim, seed: Number(e.target.value) })} /></Field>
        <Field label={t('setup.sim.hourMin')} hint={t('setup.sim.hourMinHint')}><input className="input h-8" type="number" step="0.1" value={sim.sim_hour_real_minutes ?? 0.5} onChange={(e) => setSim({ ...sim, sim_hour_real_minutes: Number(e.target.value) })} /></Field>
        <Field label={t('setup.sim.fault')} hint={t('setup.sim.faultHint')}><input className="input h-8" type="number" step="0.1" value={sim.fault_rate ?? inten.fault ?? 1} onChange={(e) => setSim({ ...sim, fault_rate: Number(e.target.value) })} /></Field>
      </div>
      <Section title={t('setup.sim.intensities')}>
        <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-4">
          {['op', 'client_error', 'signal_noise', 'fault'].map((k) => (
            <Field key={k} label={t(`setup.sim.int.${k}`)}>
              <input className="input h-8 text-xs" type="number" step="0.1" value={inten[k] ?? ''} onChange={(e) => setSim({ ...sim, intensities: { ...inten, [k]: Number(e.target.value) } })} />
            </Field>
          ))}
        </div>
      </Section>
      <SaveBar pending={save.isPending} error={save.error} ok={save.isSuccess} onSave={() => save.mutate({ sim })} />
      <EnvEditor keys={['PROFILE', 'SIM_SEED']} title={t('setup.sim.env')} note={t('setup.sim.envNote')} />
    </div>
  )
}

// ---- 4. Channels ---------------------------------------------------------------
function StepChannels({ p }: { p: SetupPayload }) {
  const { t } = useTranslation()
  const save = useSaveSetup()
  const tg = useTestTgBot()
  const [ch, setCh] = useState(p.channels ?? {})
  const [token, setToken] = useState('')
  const enabled = new Set(ch.enabled ?? [])
  const toggle = (c: string) => {
    const n = new Set(enabled)
    if (n.has(c)) n.delete(c)
    else n.add(c)
    setCh({ ...ch, enabled: Array.from(n) })
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {ALL_CHANNELS.map((c) => (
          <button key={c} className={clsx('chip', enabled.has(c) && 'chip-on')} onClick={() => toggle(c)}>
            {tEnum('channel', c)}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!ch.mailpit} onChange={(e) => setCh({ ...ch, mailpit: e.target.checked })} /> {t('setup.channels.mailpit')}</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!ch.tgbot_enabled} onChange={(e) => setCh({ ...ch, tgbot_enabled: e.target.checked })} /> {t('setup.channels.tgbot')}</label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('setup.channels.tgToken')} hint={t('setup.channels.tgHint')}><input className="input h-8 w-80 text-xs" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} /></Field>
        <button className="btn btn-sm" disabled={tg.isPending} onClick={() => tg.mutate(token)}>{t('setup.channels.tgTest')}</button>
        {tg.data && <span className={clsx('text-xs', tg.data.ok ? 'text-ok' : 'text-danger')}>{tg.data.ok ? `@${tg.data.username}` : tg.data.error}</span>}
      </div>
      <SaveBar pending={save.isPending} error={save.error} ok={save.isSuccess} onSave={() => save.mutate({ channels: ch })} />
      <EnvEditor keys={['TELEGRAM_BOT_TOKEN', 'MAILPIT_ENABLED', 'STT_PROVIDER', 'STT_MODEL_PATH', 'APP_LANG']} title={t('setup.channels.env')} note={t('setup.channels.envNote')} />
      <SttCheck />
    </div>
  )
}

// ---- 5. Policies ---------------------------------------------------------------
const HITL_KEYS = ['clarification_threshold', 'fraud_amount_rub', 'repeat_hitl_count', 'escalation_negativity', 'escalation_signals_7d', 'refund_autonomy_limit_rub', 'refund_autonomy_limit_premium_rub', 'mass_refund_threshold'] as const
function StepPolicies({ p }: { p: SetupPayload }) {
  const { t } = useTranslation()
  const save = useSaveSetup()
  const [pol, setPol] = useState(p.policies ?? {})
  const rules = (pol.hitl_rules ?? {}) as Record<string, number>
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label={t('setup.policies.confidence')} hint={t('setup.policies.confidenceHint')}>
          <input className="input h-8" type="number" step="0.05" min="0" max="1" value={pol.confidence_threshold ?? 0.75} onChange={(e) => setPol({ ...pol, confidence_threshold: Number(e.target.value) })} />
        </Field>
        <Field label={t('setup.policies.dedup')} hint={t('setup.policies.dedupHint')}>
          <input className="input h-8" type="number" min="0" max="72" value={pol.dedup_window_hours ?? 4} onChange={(e) => setPol({ ...pol, dedup_window_hours: Number(e.target.value) })} />
        </Field>
      </div>
      <Section title={t('setup.policies.hitl')}>
        <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-4">
          {HITL_KEYS.map((k) => (
            <Field key={k} label={t(`setup.policies.rule.${k}`)}>
              <input className="input h-8 text-xs" type="number" step="any" value={rules[k] ?? ''} placeholder={t('setup.policies.default')} onChange={(e) => setPol({ ...pol, hitl_rules: { ...rules, [k]: Number(e.target.value) } })} />
            </Field>
          ))}
        </div>
      </Section>
      <SaveBar pending={save.isPending} error={save.error} ok={save.isSuccess} onSave={() => save.mutate({ policies: pol })} />
    </div>
  )
}

// ---- 6. SLA + routing ---------------------------------------------------------------
function StepSla() {
  const { t } = useTranslation()
  const sla = useSlaMatrix()
  const routing = useRoutingRules()
  const teams = useRefs('teams')
  const saveSla = useSaveSetting<SlaCell[]>('sla', '/api/settings/sla-matrix')
  const saveRouting = useSaveSetting<RoutingRule[]>('routing', '/api/settings/routing-rules')
  const [cells, setCells] = useState<SlaCell[] | null>(null)
  const [rulesText, setRulesText] = useState<string | null>(null)
  const [jsonErr, setJsonErr] = useState<string | null>(null)
  const data = cells ?? sla.data ?? []
  const upd = (i: number, patch: Partial<SlaCell>) => setCells(data.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const order = ['easy', 'medium', 'hard']
  const crit = ['low', 'medium', 'high']
  return (
    <div className="flex flex-col gap-4">
      <Section title={t('setup.sla.matrix')} right={<span className="text-xs text-muted">{t('setup.sla.unit')}</span>}>
        <table className="w-full text-xs">
          <thead className="text-[11px] uppercase text-muted">
            <tr>
              <th className="px-3 py-1 text-left">{t('setup.sla.complexity')}</th>
              {crit.map((c) => <th key={c} className="px-3 py-1 text-left">{tEnum('incident.criticality', c)}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {order.map((cx) => (
              <tr key={cx}>
                <td className="px-3 py-1.5 font-medium">{tEnum('incident.complexity', cx)}</td>
                {crit.map((cr) => {
                  const i = data.findIndex((c) => c.complexity === cx && c.criticality === cr)
                  const c = data[i]
                  if (!c) return <td key={cr} className="px-3 py-1.5 text-muted">—</td>
                  return (
                    <td key={cr} className="px-3 py-1.5">
                      <div className="flex flex-wrap items-center gap-1">
                        <input className="input h-7 w-14 text-xs" type="number" min={1} max={10} value={c.fix_days} title={t('setup.sla.fix')} onChange={(e) => upd(i, { fix_days: Number(e.target.value) })} />
                        <span className="text-muted">д ·</span>
                        <input className="input h-7 w-14 text-xs" type="number" min={0} value={c.take_hours} title={t('setup.sla.take')} onChange={(e) => upd(i, { take_hours: Number(e.target.value) })} />
                        <span className="text-muted">ч ·</span>
                        <input className="input h-7 w-20 text-xs" value={(c.report_days ?? []).join(',')} title={t('setup.sla.reports')} placeholder="1,3" onChange={(e) => upd(i, { report_days: e.target.value.split(',').map((x) => Number(x.trim())).filter((x) => x > 0) })} />
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="px-3 py-2 text-[11px] text-faint">{t('setup.sla.legend')}</p>
        <div className="px-3 pb-3"><SaveBar pending={saveSla.isPending} error={saveSla.error} ok={saveSla.isSuccess} onSave={() => saveSla.mutate(data)} /></div>
      </Section>
      <Section title={t('setup.sla.routing')} right={<span className="text-xs text-muted">{t('setup.sla.teams', { n: (teams.data ?? []).length })}</span>}>
        <div className="p-3">
          <textarea
            className="input w-full resize-y font-mono text-[11px]" style={{ height: 256 }}
            value={rulesText ?? JSON.stringify(routing.data ?? [], null, 2)}
            onChange={(e) => { setRulesText(e.target.value); setJsonErr(null) }}
          />
          <p className="mt-1 text-[11px] text-faint">{t('setup.sla.routingHint')}</p>
          {jsonErr && <div className="text-xs text-danger">{jsonErr}</div>}
          <SaveBar
            pending={saveRouting.isPending}
            error={saveRouting.error}
            ok={saveRouting.isSuccess}
            onSave={() => {
              try {
                saveRouting.mutate(JSON.parse(rulesText ?? JSON.stringify(routing.data ?? [])) as RoutingRule[])
              } catch (e) {
                setJsonErr(String(e))
              }
            }}
          />
        </div>
      </Section>
    </div>
  )
}

// ---- 7. Economics ---------------------------------------------------------------
const RF_KEYS = ['closed_in_sla_with_gift', 'closed_in_sla', 'closed_late', 'closed_with_regression', 'open', 'rejected', 'churned'] as const
function StepEconomics() {
  const { t } = useTranslation()
  const q = useEconomicsSettings()
  const save = useSaveSetting<EconomicsSettingsT>('economics', '/api/settings/economics')
  const [e, setE] = useState<EconomicsSettingsT | null>(null)
  const d = e ?? q.data
  if (!d) return <SkeletonRows n={4} />
  const rf = (d.retention_factors ?? {}) as Record<string, number>
  const rates = d.rates ?? []
  const setRate = (i: number, v: number) => setE({ ...d, rates: rates.map((r, j) => (j === i ? { ...r, rate_rub: v } : r)) })
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-4">
        <Field label={t('setup.econ.detractor')}><input className="input h-8" type="number" step="0.01" min="0" max="1" value={d.detractor_share ?? 0.1} onChange={(ev) => setE({ ...d, detractor_share: Number(ev.target.value) })} /></Field>
        <Field label={t('setup.econ.noReturn')}><input className="input h-8" type="number" step="0.01" min="0" max="1" value={d.no_return_share ?? 0.5} onChange={(ev) => setE({ ...d, no_return_share: Number(ev.target.value) })} /></Field>
        <Field label={t('setup.econ.misselling')}><input className="input h-8" type="number" step="100" value={d.misselling_case_cost_rub ?? ''} onChange={(ev) => setE({ ...d, misselling_case_cost_rub: Number(ev.target.value) })} /></Field>
        <Field label={t('setup.econ.mode')}>
          <select className="input h-8" value={d.calibration_mode ?? 'manual'} onChange={(ev) => setE({ ...d, calibration_mode: ev.target.value as 'manual' | 'simulated' })}>
            <option value="manual">{t('setup.econ.modeManual')}</option>
            <option value="simulated">{t('setup.econ.modeSim')}</option>
          </select>
        </Field>
      </div>
      <Section title={t('setup.econ.retention')}>
        <div className="grid gap-2 p-3 sm:grid-cols-3 lg:grid-cols-4">
          {RF_KEYS.map((k) => (
            <Field key={k} label={tEnum('outcome', k)}>
              <input className="input h-8 text-xs" type="number" step="0.05" min="0" max="1" value={rf[k] ?? ''} onChange={(ev) => setE({ ...d, retention_factors: { ...rf, [k]: Number(ev.target.value) } })} />
            </Field>
          ))}
        </div>
      </Section>
      <Section title={t('setup.econ.rates', { n: rates.length })}>
        <div className="grid gap-x-4 gap-y-1 p-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
          {rates.map((r, i) => (
            <label key={r.code} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate" title={JSON.stringify(r.maps_to)}>{r.name_ru} <span className="font-mono text-faint">{r.code}</span></span>
              <input className="input h-7 w-24 text-right text-xs" type="number" step="0.01" value={r.rate_rub} onChange={(ev) => setRate(i, Number(ev.target.value))} />
              <span className="text-muted">₽</span>
            </label>
          ))}
        </div>
      </Section>
      <p className="text-[11px] text-faint">{t('setup.econ.formula')}</p>
      <SaveBar pending={save.isPending} error={save.error} ok={save.isSuccess} onSave={() => save.mutate(d)} />
    </div>
  )
}

// ---- 8. Templates, gifts, psychotypes ---------------------------------------------------------------
function StepTemplates() {
  const { t } = useTranslation()
  const tpl = useTemplates()
  const gifts = useGifts()
  const ps = usePsychotypes()
  const saveTpl = useSaveSetting<NotificationTemplateT[]>('templates', '/api/settings/templates')
  const saveGifts = useSaveSetting<GiftCatalogItem[]>('gifts', '/api/settings/gifts')
  const savePs = useSaveSetting<PsychotypeSettings>('psychotypes', '/api/settings/psychotypes')
  const [tplEdit, setTplEdit] = useState<NotificationTemplateT[] | null>(null)
  const [giftText, setGiftText] = useState<string | null>(null)
  const [mix, setMix] = useState<Record<string, Record<string, number>> | null>(null)
  const [filter, setFilter] = useState('')
  const templates = useMemo(() => tplEdit ?? tpl.data ?? [], [tplEdit, tpl.data])
  const codes = useMemo(() => Array.from(new Set(templates.map((x) => x.code))).sort(), [templates])
  const shown = templates.filter((x) => !filter || x.code === filter)
  const updTpl = (id: number | undefined, body: string) => setTplEdit(templates.map((x) => (x.id === id ? { ...x, body } : x)))
  const segMix = mix ?? ps.data?.segment_mix ?? {}
  const ptCodes = (ps.data?.psychotypes ?? []).map((x) => x.code)
  return (
    <div className="flex flex-col gap-4">
      <Section
        title={t('setup.tpl.templates', { n: templates.length })}
        right={
          <select className="input h-7 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">{t('common.all')}</option>
            {codes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        }
      >
        <ul className="max-h-96 divide-y divide-line overflow-y-auto">
          {shown.slice(0, 60).map((x) => (
            <li key={x.id ?? `${x.code}-${x.channel_code}-${x.segment_code}`} className="flex flex-col gap-1 px-3 py-2 text-xs">
              <div className="flex items-center gap-2 text-muted">
                <span className="font-mono text-ink">{x.code}</span>
                <span>{tEnum('channel', x.channel_code)}</span>
                {x.segment_code && <span>{x.segment_code}</span>}
                <span>{x.lang}</span>
                {(x.variables ?? []).length > 0 && <span className="text-faint">{'{{'}{(x.variables ?? []).join('}}, {{')}{'}}'}</span>}
              </div>
              <textarea className="input w-full resize-y text-xs" style={{ height: 56 }} value={x.body} onChange={(e) => updTpl(x.id, e.target.value)} />
            </li>
          ))}
          {shown.length > 60 && <li className="px-3 py-2 text-xs text-muted">{t('setup.tpl.more', { n: shown.length - 60 })}</li>}
        </ul>
        <div className="px-3 pb-3"><SaveBar pending={saveTpl.isPending} error={saveTpl.error} ok={saveTpl.isSuccess} onSave={() => saveTpl.mutate(templates)} /></div>
      </Section>
      <Section title={t('setup.tpl.gifts', { n: (gifts.data ?? []).length })}>
        <div className="p-3">
          <textarea className="input w-full resize-y font-mono text-[11px]" style={{ height: 192 }} value={giftText ?? JSON.stringify(gifts.data ?? [], null, 2)} onChange={(e) => setGiftText(e.target.value)} />
          <p className="mt-1 text-[11px] text-faint">{t('setup.tpl.giftsHint')}</p>
          <SaveBar
            pending={saveGifts.isPending}
            error={saveGifts.error}
            ok={saveGifts.isSuccess}
            onSave={() => {
              try {
                saveGifts.mutate(JSON.parse(giftText ?? JSON.stringify(gifts.data ?? [])) as GiftCatalogItem[])
              } catch {
                /* показывается ошибкой ниже */
              }
            }}
          />
        </div>
      </Section>
      <Section title={t('setup.tpl.psychotypes')}>
        <div className="overflow-x-auto p-3">
          <table className="text-xs">
            <thead className="text-[11px] uppercase text-muted">
              <tr>
                <th className="px-2 py-1 text-left">{t('setup.tpl.segment')}</th>
                {ptCodes.map((c) => <th key={c} className="px-2 py-1 text-left">{(ps.data?.psychotypes ?? []).find((x) => x.code === c)?.name_ru ?? c}</th>)}
                <th className="px-2 py-1">Σ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {Object.entries(segMix).map(([seg, shares]) => {
                const sum = Object.values(shares).reduce((a, b) => a + b, 0)
                return (
                  <tr key={seg}>
                    <td className="px-2 py-1 font-medium">{seg}</td>
                    {ptCodes.map((c) => (
                      <td key={c} className="px-2 py-1">
                        <input className="input h-7 w-16 text-xs" type="number" step="0.05" min="0" max="1" value={shares[c] ?? 0} onChange={(e) => setMix({ ...segMix, [seg]: { ...shares, [c]: Number(e.target.value) } })} />
                      </td>
                    ))}
                    <td className={clsx('num px-2 py-1', Math.abs(sum - 1) > 0.01 ? 'text-danger' : 'text-ok')}>{sum.toFixed(2)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="mt-1 text-[11px] text-faint">{t('setup.tpl.psHint')}</p>
          <SaveBar pending={savePs.isPending} error={savePs.error} ok={savePs.isSuccess} onSave={() => savePs.mutate({ psychotypes: ps.data?.psychotypes ?? [], segment_mix: segMix })} />
        </div>
      </Section>
    </div>
  )
}

// ---- 9. Generate + finish ---------------------------------------------------------------
function StepGenerate({ completed }: { completed: boolean }) {
  const { t } = useTranslation()
  const start = useStartGenerate()
  const finish = useFinishSetup()
  const [body, setBody] = useState({ profile: 'demo' as 'lite' | 'demo' | 'stress', seed: 42, reset_history: false })
  const [polling, setPolling] = useState(false)
  const st = useGenerateStatus(polling)
  useEffect(() => {
    const running = st.data?.status === 'running'
    if (running !== polling && st.data) setPolling(running)
  }, [st.data, polling])
  const cov = (st.data?.coverage ?? null) as Record<string, unknown> | null
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('setup.gen.profile')}>
          <select className="input h-8" value={body.profile} onChange={(e) => setBody({ ...body, profile: e.target.value as typeof body.profile })}>
            <option value="lite">lite</option>
            <option value="demo">demo</option>
            <option value="stress">stress</option>
          </select>
        </Field>
        <Field label={t('setup.gen.seed')}><input className="input h-8 w-28" type="number" value={body.seed} onChange={(e) => setBody({ ...body, seed: Number(e.target.value) })} /></Field>
        <label className="flex h-8 items-center gap-2 text-sm"><input type="checkbox" checked={body.reset_history} onChange={(e) => setBody({ ...body, reset_history: e.target.checked })} /> {t('setup.gen.reset')}</label>
        <button className="btn btn-sm btn-primary" disabled={start.isPending || st.data?.status === 'running'} onClick={() => { start.mutate(body); setPolling(true) }}>
          {t('setup.gen.start')}
        </button>
        {start.error && <ErrorBox error={start.error} compact />}
      </div>
      <p className="text-[11px] text-faint">{t('setup.gen.resetHint')}</p>
      {st.data && st.data.status !== 'idle' && (
        <div className="card p-3">
          <div className="mb-1 flex items-center gap-2 text-xs">
            <Badge tone={st.data.status === 'done' ? 'ok' : st.data.status === 'failed' ? 'danger' : 'info'}>{t(`setup.gen.status.${st.data.status}`)}</Badge>
            <span className="num text-muted">{Math.round((st.data.progress ?? 0) * 100)}%</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded bg-raised"><div className="h-1.5 bg-brand transition-all" style={{ width: `${(st.data.progress ?? 0) * 100}%` }} /></div>
          </div>
          <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] text-muted">{(st.data.log ?? []).slice(-40).join('\n')}</pre>
        </div>
      )}
      {cov && (
        <Section title={t('setup.gen.coverage')}>
          <div className="grid gap-3 p-3 text-xs md:grid-cols-3">
            <div>
              <div className="mb-1 text-muted">{t('setup.gen.slaCells')} {cov.sla_cells_ok ? <Badge tone="ok">ok</Badge> : <Badge tone="warn">{t('setup.gen.gaps')}</Badge>}</div>
              <ul className="num font-mono">{Object.entries((cov.sla_cells as Record<string, number>) ?? {}).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>
            </div>
            <div>
              <div className="mb-1 text-muted">{t('setup.gen.styles')}</div>
              <ul className="num font-mono">{Object.entries((cov.styles as Record<string, number>) ?? {}).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>
            </div>
            <div>
              <div className="mb-1 text-muted">{t('setup.gen.other')}</div>
              <ul className="num font-mono">
                {Object.entries(cov).filter(([, v]) => typeof v !== 'object').map(([k, v]) => <li key={k}>{k}: {String(v)}</li>)}
              </ul>
            </div>
          </div>
        </Section>
      )}
      <div className="flex items-center gap-3 border-t border-line pt-3">
        <button className="btn btn-sm btn-primary" disabled={finish.isPending || completed} onClick={() => finish.mutate()}>
          {completed ? t('setup.completed') : t('setup.finish')}
        </button>
        <span className="text-xs text-muted">{t('setup.finishHint')}</span>
      </div>
    </div>
  )
}

// ---- export / import ---------------------------------------------------------------
function ExportImport() {
  const { t } = useTranslation()
  const imp = useImportSettings()
  const onFile = (f: File | undefined) => {
    if (!f) return
    void f.text().then((txt) => imp.mutate(JSON.parse(txt)))
  }
  return (
    <div className="ml-auto flex items-center gap-2">
      <a className="btn btn-sm" href="/api/settings/export" download="cx-pulse-settings.json">
        <Download size={13} /> {t('setup.export')}
      </a>
      <label className="btn btn-sm cursor-pointer">
        <Upload size={13} /> {t('setup.import')}
        <input type="file" accept="application/json" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />
      </label>
      {imp.isSuccess && <span className="text-xs text-ok">{t('setup.imported')}</span>}
      {imp.error && <ErrorBox error={imp.error} compact />}
    </div>
  )
}

function SttCheck() {
  const { t } = useTranslation()
  const prov = useSttProviders()
  const test = useSttTest()
  return (
    <Section title={t('setup.stt.title')}>
      <table className="w-full text-xs">
        <tbody className="divide-y divide-line">
          {(prov.data ?? []).map((p) => (
            <tr key={p.code}>
              <td className="px-3 py-1.5 font-mono">{p.code}</td>
              <td className="px-3 py-1.5">{p.label_ru}</td>
              <td className="px-3 py-1.5">
                <Badge tone={p.available ? 'ok' : 'neutral'}>{p.available ? t('setup.stt.available') : t('setup.stt.unavailable')}</Badge> {p.is_default && <Badge tone="brand">{t('setup.stt.default')}</Badge>}{' '}
                {p.external_service && <Badge tone="warn">{t('live.external')}</Badge>}
              </td>
              <td className="px-3 py-1.5 text-muted">{p.model ?? p.note_ru}</td>
              <td className="px-3 py-1.5 text-right">
                {p.available && p.code !== 'browser' && (
                  <button className="btn btn-sm" disabled={test.isPending} onClick={() => test.mutate(p.code!)}>
                    {t('setup.stt.test')}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {test.error && (
        <div className="px-3 pb-2">
          <ErrorBox error={test.error} compact />
        </div>
      )}
      {test.data && (
        <div className="border-t border-line px-3 py-2 text-xs">
          <span className={test.data.ok ? 'text-ok' : 'text-danger'}>{test.data.ok ? t('setup.stt.ok') : t('setup.stt.fail')}</span>
          {test.data.text && (
            <>
              {' '}
              · «{test.data.text}» · WER {test.data.wer} · {test.data.latency_ms} мс
            </>
          )}
          {test.data.note_ru && <> · {test.data.note_ru}</>}
        </div>
      )}
      <p className="px-3 pb-2 text-[11px] text-faint">{t('setup.stt.note')}</p>
    </Section>
  )
}
