import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ROUTES } from '@/shared/routes'

export function IdLink({ kind, value }: { kind: string; value: string | number | null | undefined }) {
  const { t } = useTranslation()
  const [copy, setCopy] = useState<'idle' | 'done' | 'error'>('idle')
  if (value == null || value === '') return <span>—</span>
  const ref = String(value)
  return (
    <span className="inline-flex items-center gap-1 font-mono text-xs" onClick={(e) => e.stopPropagation()}>
      <Link
        to={ROUTES.traceObject(kind, ref)}
        title={t('traceUi.kind.' + kind, { defaultValue: kind })}
        aria-label={t('traceUi.openId', { ref })}
        className="text-brand hover:underline"
      >
        {ref}
      </Link>
      <button
        type="button"
        className="rounded px-1 text-muted hover:bg-raised"
        aria-label={t('traceUi.copyId', { ref })}
        onClick={() => {
          void navigator.clipboard.writeText(ref).then(
            () => setCopy('done'),
            () => setCopy('error'),
          )
        }}
      >
        ⧉
      </button>
      <span role="status" className="sr-only">
        {copy === 'done' ? t('traceUi.copied') : copy === 'error' ? t('traceUi.copyError') : ''}
      </span>
    </span>
  )
}
