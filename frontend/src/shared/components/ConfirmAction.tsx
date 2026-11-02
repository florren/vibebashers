import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Modal } from '@/shared/ui'

/** Подтверждение не отменяет серверную валидацию, HITL или правила денежных действий. */
export function ConfirmAction({ open, title, consequence, onCancel, onConfirm, pending = false }: { open: boolean; title: string; consequence: string; onCancel: () => void; onConfirm: () => void; pending?: boolean }) {
  const { t } = useTranslation()
  const id = useId()
  return <Modal open={open} onClose={onCancel} title={title}>
    <p id={id} className="mb-4 text-sm leading-relaxed">{consequence}</p>
    <div className="flex flex-wrap justify-end gap-2">
      <button className="btn" onClick={onCancel}>{t('attention.cancel')}</button>
      <button className="btn btn-primary" aria-describedby={id} disabled={pending} onClick={onConfirm}>{t('attention.confirm')}</button>
    </div>
  </Modal>
}
