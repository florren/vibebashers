import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useMobileLayout } from './device-store'

/** Фильтры сохраняют состояние при сворачивании и переключении устройства. */
export function ResponsiveFilters({ children, active = false, title }: { children: ReactNode; active?: boolean; title?: string }) {
  const mobile = useMobileLayout()
  const [expanded, setExpanded] = useState(false)
  const { t } = useTranslation()
  return <details className="responsive-filters" open={!mobile || expanded} onToggle={e => { if (mobile) setExpanded(e.currentTarget.open) }}>
    <summary className="filter-summary cursor-pointer font-medium">{title ?? t('device.filters')}{active ? ` · ${t('device.filtersActive')}` : ''}</summary>
    <div className="space-y-4">{children}</div>
  </details>
}
