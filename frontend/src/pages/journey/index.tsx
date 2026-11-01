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
            to={`${reference ? ROUTES.journeyObject(reference) : ROUTES.journey}${m === 'follow' ? '' : `?mode=${m}`}`}
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
              onChange={(e) => nav(e.target.checked ? ROUTES.journey : ROUTES.journeyObject(reference!))}
            />
            {t('journeyModes.autoFollow')}
          </label>
        )}
      </nav>
      <DemoExecution onStarted={reference => nav(ROUTES.journeyObject(reference))} />
      <SignalPicker onSelect={reference => nav(`${ROUTES.journeyObject(reference)}${mode === 'follow' ? '' : `?mode=${mode}`}`)} />
      {mode === 'follow' ? (
        <LiveJourney onSubject={setSubject} />
      ) : reference ? (
        <div className="min-h-0 flex-1 overflow-auto">
          <RecordedJourney key={`${mode}:${reference}`} reference={reference} mode={mode} />
        </div>
      ) : (
        <p className="p-5">{t('journeyModes.choose')}</p>
      )}
    </div>
  )
}
