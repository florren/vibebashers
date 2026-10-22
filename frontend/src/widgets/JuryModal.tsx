import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useClients, useJury, useRefs } from '@/shared/api/hooks'
import { ErrorBox, Modal } from '@/shared/ui'
import { VoiceInput } from '@/shared/audio/VoiceInput'

const ANON_CHANNELS = new Set(['social', 'review_portal', 'landing'])

/** Режим жюри (ТЗ 11.4): любой текст → POST /api/signals → агент → ссылки на сигнал и прогон. */
export function JuryModal({ open, onClose, onSignal }: { open: boolean; onClose: () => void; onSignal?: (id: number) => void }) {
  const { t } = useTranslation()
  const channels = useRefs('channels')
  const [channel, setChannel] = useState('chat')
  const [text, setText] = useState('')
  const [clientId, setClientId] = useState('')
  const [handle, setHandle] = useState('')
  const [segment, setSegment] = useState('')
  const segments = useRefs('segments')
  const clients = useClients({ segment: segment || undefined }, !!segment)
  const jury = useJury()

  const submit = () => {
    const cid = clientId.trim() ? Number(clientId) : null
    jury.mutate({
      channel_code: channel,
      text: text.trim(),
      client_id: Number.isFinite(cid as number) ? cid : null,
      ...(ANON_CHANNELS.has(channel) && handle.trim() ? { external_contact: { nick: handle.trim() } } : {}),
    })
  }

  const close = () => {
    jury.reset()
    onClose()
  }

  return (
    <Modal open={open} onClose={close} title={t('jury.title')}>
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 flex items-center justify-between text-xs text-muted">
            {t('jury.text')}
            <VoiceInput onText={(tx) => setText((v) => (v ? `${v} ${tx}` : tx))} />
          </span>
          <textarea
            className="input h-28 w-full resize-y py-2"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t('jury.placeholder')}
            autoFocus
          />
        </label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <label className="block">
            <span className="mb-1 block text-xs text-muted">{t('jury.channel')}</span>
            <select className="input w-full" value={channel} onChange={(e) => setChannel(e.target.value)}>
              {(channels.data ?? [{ code: 'chat', name_ru: 'Чат' }]).map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name_ru}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-muted">{t('jury.segment')}</span>
            <select
              className="input w-full"
              value={segment}
              onChange={(e) => {
                setSegment(e.target.value)
                setClientId('')
              }}
            >
              <option value="">{t('jury.anySegment')}</option>
              {(segments.data ?? []).map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name_ru}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-muted">{t('jury.client')}</span>
            {segment ? (
              <select className="input w-full" value={clientId} onChange={(e) => setClientId(e.target.value)}>
                <option value="">—</option>
                {(clients.data ?? []).map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.display_name} · {c.city_name ?? c.public_id}
                  </option>
                ))}
              </select>
            ) : (
              <input className="input w-full" inputMode="numeric" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="ID" />
            )}
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-muted">{t('jury.handle')}</span>
            <input
              className="input w-full"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="@nick"
              disabled={!ANON_CHANNELS.has(channel)}
            />
          </label>
        </div>
        {jury.isError && <ErrorBox error={jury.error} compact />}
        {jury.data && (
          <div className="fade-in flex items-center gap-2 rounded-lg border border-ok/30 bg-ok/5 px-3 py-2 text-[13px]">
            <span className="text-ok">{t('jury.result', { id: jury.data.signal_id, run: jury.data.agent_run_id })}</span>
            <span className="mx-auto" />
            {jury.data.signal_id !== undefined && (
              <button
                className="btn btn-sm"
                onClick={() => {
                  onSignal?.(jury.data.signal_id!)
                  close()
                }}
              >
                {t('jury.openSignal')}
              </button>
            )}
            <Link className="btn btn-sm" to={`/engine/${jury.data.agent_run_id}`} onClick={close}>
              {t('jury.openRun')}
            </Link>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={close}>
            {t('common.close')}
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={jury.isPending || text.trim().length < 3}>
            {jury.isPending ? t('jury.sending') : t('jury.send')}
          </button>
        </div>
      </div>
    </Modal>
  )
}
