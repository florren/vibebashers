import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { QrCode } from 'lucide-react'
import { api } from '@/shared/api/client'
import type { paths } from '@/shared/api/types'
import { Modal } from '@/shared/ui'

type Health = paths['/api/health']['get']['responses'][200]['content']['application/json']

export function BotQrButton({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [failed, setFailed] = useState(false)
  const q = useQuery({ queryKey: ['bot-readiness'], queryFn: () => api<Health>('/api/health'), refetchInterval: 5000, retry: false })
  const username = q.data?.tgbot_username
  if (q.isError || q.data?.tgbot !== 'running' || !username) return null
  return <>
    <button className={compact ? 'btn mobile-icon' : 'btn btn-sm'} aria-label={t('botQr.open')} title={t('botQr.open')} onClick={() => { setFailed(false); setOpen(true) }}>{compact ? <QrCode size={20} /> : t('botQr.open')}</button>
    <Modal open={open} onClose={() => setOpen(false)} title={t('botQr.title')} width="max-w-2xl">
      <div className="space-y-3 p-5 text-center">
        <p className="text-sm text-muted">{t('botQr.instructions')}</p>
        {open && !failed && <img className="mx-auto aspect-square w-full max-w-[480px] bg-white p-4" width={480} height={480} src="/api/public/bot/qr" alt={t('botQr.alt')} onError={() => setFailed(true)} />}
        {failed && <p role="alert" className="text-sm text-danger">{t('botQr.unavailable')}</p>}
        <p className="font-mono text-lg">@{username}</p>
        <p className="text-sm text-muted">{t('botQr.fictional')}</p>
      </div>
    </Modal>
  </>
}
