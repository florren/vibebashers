import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Schemas } from '@/shared/api/client'
import { ErrorBox } from '@/shared/ui'

export type JourneyOptions = Pick<Schemas['DemoExecutionRequest'], 'scenario_id' | 'team_outcome' | 'emulate_humans' | 'auto_advance'>
export const DEFAULT_JOURNEY_OPTIONS: JourneyOptions = { scenario_id: 'deposit_promo_rate', team_outcome: 'on_time', emulate_humans: true, auto_advance: true }

/** Локальный draft: применяется только при отправке текста из Journey. */
export function DemoExecution({ value = DEFAULT_JOURNEY_OPTIONS, onChange }: { value?: JourneyOptions; onChange?: (value: JourneyOptions) => void }) {
  const { t, i18n } = useTranslation()
  const scenarios = useQuery({ queryKey: ['demo-scenarios'], queryFn: () => api<Schemas['Scenario'][]>('/api/scenarios') })
  const change = (patch: Partial<JourneyOptions>) => onChange?.({ ...value, ...patch })
  return <details className="shrink-0 border-b border-line bg-surface px-4 py-2">
    <summary className="cursor-pointer text-sm font-semibold">{t('journeyProfile.title')}</summary>
    <p className="my-2 text-xs text-muted">{t('journeyProfile.hint')}</p>
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs">{t('demoExecution.scenario')}
        <select className="input max-w-md" value={value.scenario_id ?? ''} onChange={e => change({ scenario_id: e.target.value || null })}>
          <option value="">{t('journeyProfile.noScenario')}</option>
          {(scenarios.data ?? []).filter(s => !['customer_journey', 'search_and_trace'].includes(s.id ?? '')).map(s => <option key={s.id} value={s.id}>{i18n.language.startsWith('en') ? s.title_en : s.title_ru}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">{t('demoExecution.outcome')}
        <select className="input" value={value.team_outcome} onChange={e => change({ team_outcome: e.target.value as JourneyOptions['team_outcome'] })}>
          {(['on_time', 'late', 'no_work', 'failed'] as const).map(o => <option key={o} value={o}>{t(`demoExecution.outcomes.${o}`)}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={value.emulate_humans} onChange={e => change({ emulate_humans: e.target.checked })} />{t('demoExecution.humans')}</label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={value.auto_advance} onChange={e => change({ auto_advance: e.target.checked })} />{t('demoExecution.fastManual')}</label>
    </div>
    {scenarios.isError && <ErrorBox error={scenarios.error} />}
  </details>
}
