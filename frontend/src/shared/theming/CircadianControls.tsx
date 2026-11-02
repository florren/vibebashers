import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PHASES, validCoordinates } from './circadian'
import { applyUiTheme } from './apply'
import { useUiTheme } from './store'

export function CircadianControls() {
  const { t } = useTranslation()
  const circadian = useUiTheme((s) => s.circadian)
  const setCircadian = useUiTheme((s) => s.setCircadian)
  const [located, setLocated] = useState(() => { try { return validCoordinates(JSON.parse(localStorage.getItem('cx.ui.location') ?? 'null')) !== null } catch { return false } })
  const [status, setStatus] = useState<'idle' | 'pending' | 'error'>('idle')
  const repaint = () => {
    const s = useUiTheme.getState()
    applyUiTheme(s.theme_pack, s.mode, s.density, s.simTime)
  }
  const locate = () => {
    // Единственная точка запроса координат: явное нажатие после пояснения цели.
    if (!navigator.geolocation) { setStatus('error'); return }
    setStatus('pending')
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      const location = validCoordinates(coords)
      if (!location) { setStatus('error'); return }
      localStorage.setItem('cx.ui.location', JSON.stringify(location))
      setLocated(true)
      setStatus('idle')
      repaint()
    }, () => setStatus('error'), { enableHighAccuracy: false, timeout: 10_000, maximumAge: 3_600_000 })
  }
  return <details className="relative text-xs" data-testid="circadian-controls">
    <summary className="cursor-pointer rounded border border-control-line px-2 py-1">{t('theme.circadian.settings')}</summary>
    <div className="absolute right-0 top-full z-50 mt-1 w-72 max-w-[90vw] space-y-3 rounded border border-control-line bg-surface p-3 shadow-lg">
      <label className="block">{t('theme.circadian.sourceLabel')}
        <select className="input mt-1 w-full" value={circadian.source} onChange={(e) => setCircadian({ ...circadian, source: e.target.value as typeof circadian.source })}>
          {(['sim', 'real', 'fixed'] as const).map((source) => <option key={source} value={source}>{t(`theme.circadian.source.${source}`)}</option>)}
        </select>
      </label>
      {circadian.source === 'fixed' && <label className="block">{t('theme.circadian.phaseLabel')}
        <select className="input mt-1 w-full" value={circadian.fixed_phase} onChange={(e) => setCircadian({ ...circadian, fixed_phase: e.target.value as typeof circadian.fixed_phase })}>
          {PHASES.map((phase) => <option key={phase} value={phase}>{t(`theme.circadian.phase.${phase}`)}</option>)}
        </select>
      </label>}
      {circadian.source !== 'fixed' && <>
        <p>{t('theme.circadian.geoExplanation')}</p>
        <p role="status">{t(located ? 'theme.circadian.localLocation' : 'theme.circadian.moscow')}</p>
        <button type="button" className="btn-secondary text-xs" disabled={status === 'pending'} onClick={locate}>{t(status === 'pending' ? 'theme.circadian.locating' : 'theme.circadian.allowLocation')}</button>
        {located && <button type="button" className="btn-secondary ml-1 text-xs" onClick={() => { localStorage.removeItem('cx.ui.location'); setLocated(false); setStatus('idle'); repaint() }}>{t('theme.circadian.forgetLocation')}</button>}
        {status === 'error' && <p role="alert" className="text-danger">{t('theme.circadian.geoError')}</p>}
      </>}
    </div>
  </details>
}
