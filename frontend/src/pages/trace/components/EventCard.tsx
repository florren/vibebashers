import { useTranslation } from 'react-i18next'
import type { TraceEvent } from '@/shared/api/trace'

import { eventIcon } from './eventIcon'

export function EventCard({ event, onSelect }: { event: TraceEvent; onSelect?: (event: TraceEvent) => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      className="my-2 block w-full rounded-xl border border-line bg-surface p-3 text-left shadow-sm hover:bg-raised"
      onClick={() => onSelect?.(event)}
    >
      <span className="text-xs text-muted">
        {event.actor.label_ru} · {event.ts_sim ? new Date(event.ts_sim).toLocaleString() : '—'}
      </span>
      <strong className="mt-1 block">
        {eventIcon(event.kind)} {event.title_ru}
      </strong>
      <span className="block text-sm">{event.brief_ru}</span>
      <span className="text-xs text-muted">
        {t('traceUi.realTime')}: {new Date(event.ts_real).toLocaleString()}
      </span>
      {event.badges.llm_source && <span className="ml-2 rounded border border-line px-1 text-xs">{event.badges.llm_source}</span>}
      {event.badges.amount_rub != null && (
        <strong className="ml-2">
          {new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(event.badges.amount_rub)}
        </strong>
      )}
      {event.order_warning && <span className="block text-xs text-muted">{t('traceUi.orderWarning')}</span>}
    </button>
  )
}
