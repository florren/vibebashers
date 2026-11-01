import { Search } from 'lucide-react'
import { JourneyLink } from './JourneyLink'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { ROUTES } from '@/shared/routes'
import { searchObjects } from '@/shared/api/trace'

export function GlobalSearch({ inline = false, compact = false }: { inline?: boolean; compact?: boolean }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(inline)
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)
  const [filter, setFilter] = useState('')
  const field = useRef<HTMLInputElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(input.trim())
      setSelected(0)
    }, 200)
    return () => clearTimeout(timer)
  }, [input])
  useEffect(() => {
    if (inline) return
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (
        (e.key === 'k' && (e.ctrlKey || e.metaKey)) ||
        (e.key === '/' && !(el instanceof Element && el.closest('input,textarea,[contenteditable="true"]')))
      ) {
        e.preventDefault()
        setOpen(true)
      }
      if (e.key === 'Escape' && open && !e.defaultPrevented) {
        setOpen(false)
        trigger.current?.focus()
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [inline, open])
  useEffect(() => {
    if (open) field.current?.focus()
  }, [open])
  const result = useQuery({
    queryKey: ['search', query],
    queryFn: ({ signal }) => searchObjects(query, signal),
    enabled: open && query.length > 0,
  })
  const hits = (result.data?.hits ?? []).filter((h) => !filter || h.kind === filter)
  const close = () => {
    if (!inline) {
      setOpen(false)
      trigger.current?.focus()
    }
  }
  const choose = (i: number) => {
    const hit = hits[i]
    if (hit) {
      navigate(hit.trace_href ?? ROUTES.traceObject(hit.kind, hit.ref))
      close()
    }
  }
  const content = (
    <div className="space-y-3 p-4">
      <div className="flex gap-2">
        <input
          ref={field}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t('traceUi.searchPlaceholder')}
          aria-label={t('traceUi.search')}
          role="combobox"
          aria-expanded={!!hits.length}
          aria-controls="trace-search-results"
          aria-activedescendant={hits[selected] ? `trace-hit-${selected}` : undefined}
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface p-2 text-ink"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault()
              setSelected((i) => (hits.length ? (i + (e.key === 'ArrowDown' ? 1 : -1) + hits.length) % hits.length : 0))
            }
            if (e.key === 'Enter') {
              e.preventDefault()
              choose(selected)
            }
            if (e.key === 'Tab' && !inline) {
              e.preventDefault()
              field.current?.focus()
            }
          }}
        />
        {!inline && (
          <button className="btn" onClick={close} aria-label={t('traceUi.close')}>
            ×
          </button>
        )}
      </div>
      <div className="flex gap-2">
        {(
          [
            ['', t('traceUi.all')],
            ['signal', 'SIG'],
            ['incident', 'INC'],
            ['client', 'CL'],
          ] as const
        ).map(([kind, label]) => (
          <button
            key={kind}
            type="button"
            aria-pressed={filter === kind}
            className="btn btn-sm"
            onClick={() => {
              setFilter(kind)
              setSelected(0)
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {result.isFetching && <p role="status">{t('traceUi.loading')}</p>}
      {result.isError && (
        <p role="alert">
          {t('traceUi.searchError')}{' '}
          <button className="btn" onClick={() => void result.refetch()}>
            {t('traceUi.retry')}
          </button>
        </p>
      )}
      {result.data && !hits.length && <p>{t('traceUi.emptySearch', { q: query })}</p>}
      {result.data?.parsed.kind === 'number' && hits.length > 1 && <p>{t('traceUi.ambiguous')}</p>}
      <div id="trace-search-results" role="listbox" aria-label={t('traceUi.results')} className="max-h-96 overflow-auto">
        {hits.map((h, i) => (
          <div key={`${h.kind}:${h.ref}`}>
            {(i === 0 || hits[i - 1]?.kind !== h.kind) && (
              <h3 className="mt-3 text-xs font-semibold text-muted">{t('traceUi.kind.' + h.kind, { defaultValue: h.kind })}</h3>
            )}
            <button
              id={`trace-hit-${i}`}
              role="option"
              aria-selected={selected === i}
              className={`my-1 block w-full rounded-lg border p-3 text-left ${selected === i ? 'border-brand bg-raised' : 'border-line'}`}
              onMouseEnter={() => setSelected(i)}
              onClick={() => choose(i)}
            >
              <strong>{h.ref}</strong> · {h.title_ru}
              <small className="block text-muted">
                {h.run_id} · {h.status} {h.snippet_ru}
              </small>
            </button>
            {['signal', 'incident', 'post', 'transcript'].includes(h.kind) && <JourneyLink reference={h.ref} onClick={close} />}
          </div>
        ))}
      </div>
    </div>
  )
  if (inline) return content
  return (
    <>
      <button ref={trigger} type="button" className="btn btn-sm shrink-0" aria-label={compact ? t('traceUi.search') : undefined} onClick={() => setOpen(true)}>
        {compact ? <Search size={19} /> : <>{t('traceUi.search')} <kbd>Ctrl+K</kbd></>}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 grid place-items-start bg-black/40 pt-[10vh]" onClick={close}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('traceUi.search')}
            className="mx-auto w-[min(640px,95vw)] rounded-xl border border-line bg-surface shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            {content}
          </div>
        </div>
      )}
    </>
  )
}
