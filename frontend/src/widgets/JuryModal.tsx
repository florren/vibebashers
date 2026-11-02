import { JourneyLink } from '@/shared/components/JourneyLink'
import { type FormEvent, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useClients, useJury, useRefs } from '@/shared/api/hooks'
import type { RefRow } from '@/shared/api/hooks'
import type { Schemas } from '@/shared/api/client'
import { ROUTES } from '@/shared/routes'
import { ErrorBox, Modal } from '@/shared/ui'
import { VoiceInput } from '@/shared/audio/VoiceInput'

const ANON_CHANNELS = new Set(['social', 'review_portal', 'landing'])
const positiveId = (value: string) => /^[0-9]+$/.test(value) && Number(value) > 0 && Number.isSafeInteger(Number(value))

/** Режим жюри: прежний POST /api/signals, город и voice_meta из существующего DTO. */
export function JuryModal({ open, onClose, onSignal }: { open: boolean; onClose: () => void; onSignal?: (id: number) => void }) {
  const { t, i18n } = useTranslation(), id = useId()
  const channels = useRefs('channels'), cities = useRefs('cities'), segments = useRefs('segments')
  const [channel, setChannel] = useState('chat'), [text, setText] = useState('')
  const [clientChoice, setClientChoice] = useState(''), [manualId, setManualId] = useState('')
  const [handle, setHandle] = useState(''), [segment, setSegment] = useState(''), [cityId, setCityId] = useState('')
  const [voice, setVoice] = useState<Schemas['VoiceMeta'] | null>(null)
  const clients = useClients({ segment: segment || undefined }, open)
  const jury = useJury()
  const reportedSignal = jury.data?.signal_id, reportedAgent = jury.data?.agent_run_id
  const signalId = typeof reportedSignal === 'number' && Number.isSafeInteger(reportedSignal) && reportedSignal > 0 ? reportedSignal : null
  const agentId = typeof reportedAgent === 'number' && Number.isSafeInteger(reportedAgent) && reportedAgent > 0 ? reportedAgent : null
  const label = (row: RefRow) => i18n.language.startsWith('en') ? row.name_en ?? row.name_ru : row.name_ru
  const candidate = clientChoice === 'manual' ? manualId.trim() : clientChoice
  const invalidClient = clientChoice === 'manual' && !positiveId(candidate)
  const length = [...text.trim()].length, invalidText = length < 3 || length > 5000
  const city = cities.data?.find(row => String(row.id) === cityId)
  const invalidCity = Boolean(cityId) && !city
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (invalidText || invalidClient || invalidCity || jury.isPending) return
    const nick = ANON_CHANNELS.has(channel) ? handle.trim() : ''
    jury.mutate({
      channel_code: channel, text: text.trim(), client_id: candidate ? Number(candidate) : null,
      ...(nick || city ? { external_contact: {
        ...(nick ? { nick } : {}),
        ...(city ? { city_id: Number(city.id), ...(typeof city.region_code === 'string' ? { region_code: city.region_code } : {}) } : {}),
      } } : {}),
      ...(voice ? { voice_meta: { ...voice, edited: text.trim() !== voice.transcript_raw.trim() } } : {}),
    })
  }
  const close = () => { jury.reset(); onClose() }
  return <Modal open={open} onClose={close} title={t('jury.title')} width="max-w-2xl">
    <form className="min-w-0 space-y-4" onSubmit={submit} aria-describedby={`${id}-hint ${id}-privacy`}>
      <div className="grid min-w-0 gap-3 sm:grid-cols-3">
        <label className="block min-w-0"><span className="mb-1 block text-sm">{t('jury.channel')}</span>
          <select className="input w-full" value={channel} onChange={event => setChannel(event.target.value)} disabled={jury.isPending}>
            {(channels.data ?? [{ code: 'chat', name_ru: 'Чат', name_en: 'Chat' }]).map(row => <option key={row.code} value={row.code}>{label(row)}</option>)}
          </select>
        </label>
        <label className="block min-w-0"><span className="mb-1 block text-sm">{t('jury.clientLabel')}</span>
          <select className="input w-full" value={clientChoice} onChange={event => setClientChoice(event.target.value)} disabled={jury.isPending}>
            <option value="">{t('jury.unknownClient')}</option>
            {(clients.data ?? []).map(client => <option key={client.id} value={String(client.id)}>{client.display_name} · {client.city_name ?? client.public_id}</option>)}
            {clientChoice && clientChoice !== 'manual' && !clients.data?.some(client => String(client.id) === clientChoice) && <option value={clientChoice}>#{clientChoice}</option>}
            <option value="manual">{t('jury.manualClient')}</option>
          </select>
        </label>
        <label className="block min-w-0"><span className="mb-1 block text-sm">{t('jury.city')}</span>
          <select className="input w-full" value={cityId} onChange={event => setCityId(event.target.value)} disabled={jury.isPending}>
            <option value="">{t('jury.unspecifiedCity')}</option>
            {invalidCity && <option value={cityId}>{t('jury.unavailableCity', { id: cityId })}</option>}
            {(cities.data ?? []).map(row => <option key={String(row.id)} value={String(row.id)}>{row.name_ru}</option>)}
          </select>
        </label>
      </div>
      {invalidCity && <p className="text-sm text-danger" role="alert">{t('jury.unavailableCity', { id: cityId })}</p>}
      {clientChoice === 'manual' && <div className="block"><label htmlFor={`${id}-client`} className="mb-1 block text-sm">{t('jury.clientId')}</label>
        <input id={`${id}-client`} className="input w-full" inputMode="numeric" value={manualId} onChange={event => setManualId(event.target.value)} aria-invalid={invalidClient} aria-describedby={invalidClient ? `${id}-client-error` : undefined} disabled={jury.isPending}/>
        {invalidClient && <span id={`${id}-client-error`} className="mt-1 block text-sm text-danger">{t('jury.invalidClient')}</span>}
      </div>}
      <details className="min-w-0 rounded border border-line p-3"><summary className="cursor-pointer text-sm">{t('jury.optionalFilters')}</summary>
        <label className="mt-3 block"><span className="mb-1 block text-sm">{t('jury.segment')}</span>
          <select className="input w-full" value={segment} onChange={event => { setSegment(event.target.value); setClientChoice('') }} disabled={jury.isPending}>
            <option value="">{t('jury.anySegment')}</option>{(segments.data ?? []).map(row => <option key={row.code} value={row.code}>{label(row)}</option>)}
          </select>
        </label>
        <p className="mt-2 text-sm text-muted">{t('jury.clientListHint')}</p>
        {ANON_CHANNELS.has(channel) && <label className="mt-3 block"><span className="mb-1 block text-sm">{t('jury.handle')}</span><input className="input w-full" value={handle} onChange={event => setHandle(event.target.value)} placeholder="@nick" disabled={jury.isPending}/></label>}
      </details>
      {channels.isError && <ErrorBox error={channels.error} compact/>}{cities.isError && <ErrorBox error={cities.error} compact/>}{clients.isError && <ErrorBox error={clients.error} compact/>}
      <div className="block"><div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm"><label htmlFor={`${id}-text`}>{t('jury.text')}</label>
        {!jury.isPending && <VoiceInput onText={transcript => setText(previous => previous ? `${previous} ${transcript}` : transcript)} onVoice={setVoice}/>}
      </div>
        <textarea id={`${id}-text`} className="input h-36 w-full resize-y py-2" value={text} onChange={event => setText(event.target.value)} placeholder={t('jury.placeholder')} aria-describedby={`${id}-hint ${id}-privacy ${id}-length`} aria-invalid={length > 5000} autoFocus disabled={jury.isPending}/>
      </div>
      <p id={`${id}-hint`} className="text-sm text-muted">{t('jury.agentHint')}</p>
      <p id={`${id}-privacy`} className="text-sm text-muted">{t('jury.privacyHint')}</p>
      <p id={`${id}-length`} className={length > 5000 ? 'text-sm text-danger' : 'text-sm text-muted'}>{t('jury.lengthHint', { count: length })}</p>
      {jury.isError && <ErrorBox error={jury.error} compact/>}
      {jury.data && <section className="space-y-3 rounded-lg border border-ok/30 bg-ok/5 p-3" aria-label={t('jury.resultTitle')}>
        <p role="status" className="text-sm text-ok">{signalId === null ? t('jury.resultMissingId') : agentId === null ? t('jury.resultPending', { id: signalId }) : t('jury.result', { id: signalId, run: agentId })}</p>
        <div className="flex flex-wrap gap-2">
          {signalId !== null && <><JourneyLink reference={`SIG-${String(signalId).padStart(6, '0')}`} onClick={close}/><Link className="btn btn-sm" to={ROUTES.traceObject('signal', String(signalId))} onClick={close}>{t('jury.openTrace')}</Link>
            {onSignal && <button type="button" className="btn btn-sm" onClick={() => { onSignal(signalId); close() }}>{t('jury.openSignal')}</button>}</>}
          {agentId !== null && <Link className="btn btn-sm" to={`/engine/${agentId}`} onClick={close}>{t('jury.openRun')}</Link>}
        </div>
      </section>}
      <div className="flex flex-wrap justify-end gap-2"><button type="button" className="btn" onClick={close}>{t('common.close')}</button><button type="submit" className="btn btn-primary" disabled={jury.isPending || invalidText || invalidClient || invalidCity}>{jury.isPending ? t('jury.sending') : t('jury.send')}</button></div>
    </form>
  </Modal>
}
