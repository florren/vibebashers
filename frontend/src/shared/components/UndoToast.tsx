import { useLocation } from 'react-router-dom'
import { useUndo } from '@/shared/ui/undo'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

/** Только состояние интерфейса. Здесь нет повторного/обратного запроса к серверу. */
export function UndoToast() {
  const { t } = useTranslation()
  const { entry, dismiss, undo } = useUndo()
  const { pathname } = useLocation()
  useEffect(() => { dismiss() }, [pathname, dismiss])
  useEffect(() => {
    if (!entry) return
    const timer = setTimeout(() => { if (useUndo.getState().entry?.id === entry.id) dismiss() }, Math.max(0, entry.expires - Date.now()))
    return () => clearTimeout(timer)
  }, [entry, dismiss])
  if (!entry) return null
  return <aside className="undo-toast fixed bottom-4 left-4 right-4 z-50 mx-auto flex max-w-lg flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-3 shadow-card" aria-label={t('attention.undoLabel')}>
    <span role="status" className="min-w-0 flex-1 text-sm">{t('attention.localChanged')}</span>
    <button className="btn btn-sm" onClick={undo}>{t('attention.undo')}</button>
    <button className="btn btn-ghost btn-sm" onClick={dismiss} aria-label={t('common.close')}>×</button>
  </aside>
}
