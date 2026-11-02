import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ROUTES } from '@/shared/routes'
import { DemoExecution } from './DemoExecution'
import { SignalPicker } from './SignalPicker'
import { LiveJourney } from './LiveJourney'
import { RecordedJourney } from './RecordedJourney'
import type { JourneyMode } from './playback'

export function JourneyPage() {
  const { t } = useTranslation()
  const { ref } = useParams()
  const [params] = useSearchParams()
  const runId = params.get('run_id') ?? undefined
  const href = (reference?: string, mode: JourneyMode = 'follow') => {
    const query = new URLSearchParams()
    if (runId !== undefined) query.set('run_id', runId)
    if (mode !== 'follow') query.set('mode', mode)
    return `${reference ? ROUTES.journeyObject(reference) : ROUTES.journey}${query.size ? '?' + query.toString() : ''}`
  }
  const nav = useNavigate()
  const requestedMode = params.get('mode')
  const mode: JourneyMode = requestedMode === 'replay' || requestedMode === 'presenter' ? requestedMode : 'follow'
  const [subject, setSubject] = useState<string>()
  const reference = ref ?? subject
  return (
    <div className="journey-page flex h-full min-h-0 flex-col">
      <nav aria-label={t('journeyModes.modes')} className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-surface px-4 py-2">
        {(['follow', 'replay', 'presenter'] as const).map((m) => (
          <Link
            key={m}
            aria-current={mode === m ? 'page' : undefined}
            aria-disabled={m !== 'follow' && !reference}
            className={`btn btn-sm ${mode === m ? 'border-brand text-brand' : ''}`}
            to={href(reference, m)}
            onClick={(e) => {
              if (m !== 'follow' && !reference) e.preventDefault()
            }}
          >
            {t(`journeyModes.${m}`)}
          </Link>
        ))}
        {mode === 'follow' && (
          <label className="ml-auto flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={!ref}
              disabled={!reference}
              onChange={(e) => nav(href(e.target.checked ? undefined : reference))}
            />
            {t('journeyModes.autoFollow')}
          </label>
        )}
      </nav>
      {runId === undefined && <DemoExecution onStarted={reference => nav(ROUTES.journeyObject(reference))} />}
      <SignalPicker runId={runId} onSelect={reference => nav(href(reference, mode))} />
      {mode === 'follow' ? (
        <LiveJourney key={runId ?? 'legacy'} onSubject={setSubject} runId={runId} />
      ) : reference ? (
        <div className="min-h-0 flex-1 overflow-auto">
          <RecordedJourney key={`${mode}:${reference}:${runId ?? 'legacy'}`} reference={reference} mode={mode} runId={runId} />
        </div>
      ) : (
        <p className="p-5">{t('journeyModes.choose')}</p>
      )}
    </div>
  )
}
