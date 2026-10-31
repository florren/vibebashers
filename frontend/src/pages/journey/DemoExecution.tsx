import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Schemas } from '@/shared/api/client'
import { ErrorBox } from '@/shared/ui'

type Options = Schemas['DemoExecutionRequest']
type State = Schemas['DemoExecutionState']

export function DemoExecution({ onStarted }: { onStarted?: (ref: string) => void }) {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [scenario, setScenario] = useState('deposit_promo_rate')
  const [outcome, setOutcome] = useState<NonNullable<Options['team_outcome']>>('on_time')
  const [humans, setHumans] = useState(true)
  const [fastManual, setFastManual] = useState(true)
  const [edited, setEdited] = useState(false)
  const state = useQuery({ queryKey: ['demo-execution'], queryFn: () => api<State>('/api/demo/execution'), refetchInterval: 2000 })
  const scenarios = useQuery({ queryKey: ['demo-scenarios'], queryFn: () => api<Schemas['Scenario'][]>('/api/scenarios') })
  const change = useMutation({
    mutationFn: (stop: boolean) => api<State>('/api/demo/execution', { method: stop ? 'DELETE' : 'POST', ...(stop ? {} : { body: JSON.stringify({ mode: 'demo', scenario_id: scenario, team_outcome: outcome, emulate_humans: humans, auto_advance: true } satisfies Options) }) }),
    onSuccess: (data, stop) => { void qc.invalidateQueries({ queryKey: ['demo-execution'] }); if (!stop && data.subject_ref) onStarted?.(data.subject_ref) },
  })
  const apply = useMutation({
    mutationFn: () => api<State>('/api/demo/execution', { method: 'POST', body: JSON.stringify({ mode: 'simulation', team_outcome: outcome, emulate_humans: humans, auto_advance: fastManual } satisfies Options) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['demo-execution'] }) },
  })
  const config = state.data?.configuration
  useEffect(() => {
    if (!edited && config?.mode === 'simulation') {
      setFastManual(config.auto_advance === true)
      setHumans(config.emulate_humans !== false)
      setOutcome((config.team_outcome as typeof outcome) ?? 'on_time')
    }
  }, [config, edited])
  const enabled = config?.enabled === true
  const isolated = enabled && config?.mode === 'demo'
  return <details className="shrink-0 border-b border-line bg-surface px-4 py-2">
    <summary className="cursor-pointer text-sm font-semibold">{t('demoExecution.title')} · {t(`demoExecution.status.${String(config?.status ?? 'idle')}`)}</summary>
    <p className="my-2 text-xs text-muted">{t('demoExecution.hint')}</p>
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs">{t('demoExecution.scenario')}
        <select className="input max-w-md" value={scenario} disabled={isolated || change.isPending || apply.isPending} onChange={e => setScenario(e.target.value)}>
          {(scenarios.data ?? []).filter(s => !['customer_journey', 'search_and_trace'].includes(s.id ?? '')).map(s => <option key={s.id} value={s.id}>{i18n.language.startsWith('en') ? s.title_en : s.title_ru}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">{t('demoExecution.outcome')}
        <select className="input" value={outcome} disabled={isolated || change.isPending || apply.isPending} onChange={e => { setEdited(true); setOutcome(e.target.value as typeof outcome) }}>
          {(['on_time', 'late', 'no_work', 'failed', 'recovered'] as const).map(o => <option key={o} value={o}>{t(`demoExecution.outcomes.${o}`)}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={humans} disabled={isolated || change.isPending || apply.isPending} onChange={e => { setEdited(true); setHumans(e.target.checked) }} />{t('demoExecution.humans')}</label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={fastManual} disabled={isolated || change.isPending || apply.isPending} onChange={e => { setEdited(true); setFastManual(e.target.checked) }} />{t('demoExecution.fastManual')}</label>
      <button className="btn btn-sm" disabled={change.isPending || state.isPending || state.isError || scenarios.isError} onClick={() => change.mutate(isolated)}>{t(isolated ? 'demoExecution.stop' : 'demoExecution.start')}</button>
      <button className="btn btn-sm" disabled={isolated || change.isPending || apply.isPending} onClick={() => apply.mutate()}>{t('demoExecution.applySimulation')}</button>
    </div>
    {state.data?.run_id && Boolean(config?.mode) && <p role="status" className="my-2 text-xs">{t(config?.mode === 'simulation' ? 'demoExecution.simulation' : 'demoExecution.demo')} · SR-{state.data.run_id} · {t(`demoExecution.outcomes.${String(config?.team_outcome)}`)}</p>}
    <p className="my-2 text-xs text-muted">{t('demoExecution.controlsHelp')}</p>
    {config?.mode === 'simulation' && config.auto_advance === true && <p className="my-2 text-xs text-muted">{t('demoExecution.fastHint')}</p>}
    {config?.status === 'paused' && !(config?.mode === 'simulation' && config.auto_advance === true) && <p className="mt-2 text-xs text-muted">{t('demoExecution.pausedHint')}</p>}
    {apply.isError && <ErrorBox error={apply.error} />}
    {Boolean(config?.error) && <p role="alert">{t('demoExecution.error')}: {String(config?.error)}</p>}
    {change.isError && <ErrorBox error={change.error} />}
    {state.isError && <ErrorBox error={state.error} />}
    {scenarios.isError && <ErrorBox error={scenarios.error} />}
  </details>
}
