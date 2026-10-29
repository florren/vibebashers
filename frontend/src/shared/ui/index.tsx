import { clsx } from 'clsx'
import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError } from '@/shared/api/client'

import type { Tone } from './tones'

const TONE: Record<Tone, string> = {
  neutral: 'bg-raised text-muted border-line',
  ok: 'bg-ok/10 text-ok border-ok/30',
  warn: 'bg-warn/10 text-[#8a6700] dark:text-warn border-warn/30',
  danger: 'bg-danger/10 text-danger border-danger/30',
  info: 'bg-info/10 text-info border-info/30',
  brand: 'bg-brand-soft text-brand border-brand/30',
}

export function Badge({ tone = 'neutral', children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={clsx('inline-flex h-5 items-center whitespace-nowrap rounded-md border px-1.5 text-xs font-medium leading-none', TONE[tone], className)}
    >
      {children}
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded-md bg-raised', className)} aria-hidden />
}

export function SkeletonRows({ n = 6 }: { n?: number }) {
  return (
    <div className="space-y-2 p-3">
      {Array.from({ length: n }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}

export function Empty({ title, hint, icon }: { title: string; hint?: string; icon?: ReactNode }) {
  return (
    <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-1 p-6 text-center">
      {icon && <div className="mb-1 text-faint">{icon}</div>}
      <div className="text-sm font-medium text-muted">{title}</div>
      {hint && <div className="max-w-md text-xs text-faint">{hint}</div>}
    </div>
  )
}

/** Единая обработка ошибок API: 501 → «будет позже, карточка …», остальное — текст Problem. */
export function ErrorBox({ error, compact }: { error: unknown; compact?: boolean }) {
  const { t } = useTranslation()
  if (error instanceof ApiError && error.notImplemented) {
    return <Empty title={t('common.notImplemented')} hint={t('common.notImplementedCard', { card: error.problem?.card ?? '—' })} />
  }
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div className={clsx('rounded-lg border border-danger/30 bg-danger/5 text-danger', compact ? 'px-2 py-1 text-xs' : 'm-3 p-3 text-sm')}>
      {t('common.error')}: {msg}
    </div>
  )
}

export function Section({ title, children, right, className }: { title: ReactNode; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={clsx('card min-w-0', className)}>
      <header className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
        {right}
      </header>
      <div>{children}</div>
    </section>
  )
}

export function KV({ k, v, mono }: { k: ReactNode; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="shrink-0 text-muted">{k}</span>
      <span className={clsx('min-w-0 truncate text-right', mono && 'font-mono text-xs')}>{v ?? '—'}</span>
    </div>
  )
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = 'w-[560px]',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  width?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal>
      <button className="absolute inset-0 bg-black/30" aria-label="close" onClick={onClose} />
      <aside className={clsx('fade-in relative flex h-full max-w-full flex-col border-l border-line bg-surface shadow-2xl', width)}>
        <header className="flex h-11 shrink-0 items-center justify-between border-b border-line px-4">
          <div className="min-w-0 truncate text-sm font-semibold">{title}</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="close">
            <X size={14} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </aside>
    </div>
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
  width = 'max-w-xl',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  width?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-6 pt-[8vh]" role="dialog" aria-modal>
      <button className="fixed inset-0 bg-black/30" aria-label="close" onClick={onClose} />
      <div className={clsx('fade-in relative w-full rounded-xl border border-line bg-surface shadow-2xl', width)}>
        <header className="flex h-11 items-center justify-between border-b border-line px-4">
          <div className="text-sm font-semibold">{title}</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="close">
            <X size={14} />
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  )
}

export function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T
  onChange: (v: T) => void
  items: { id: T; label: ReactNode; count?: number | null }[]
}) {
  return (
    <div className="flex items-end gap-0.5 overflow-x-auto border-b border-line px-1" role="tablist">
      {items.map((it) => (
        <button
          key={it.id}
          role="tab"
          aria-selected={value === it.id}
          onClick={() => onChange(it.id)}
          className={clsx(
            '-mb-px flex h-9 shrink-0 items-center gap-1.5 border-b-2 px-3 text-sm transition',
            value === it.id ? 'border-brand font-medium text-ink' : 'border-transparent text-muted hover:text-ink',
          )}
        >
          {it.label}
          {it.count !== undefined && it.count !== null && <span className="num rounded-full bg-raised px-1.5 text-xs text-muted">{it.count}</span>}
        </button>
      ))}
    </div>
  )
}

/** Полоса SLA: pct — остаток 0..100 (как в API, отрицательное = просрочен); зелёный → жёлтый (<50) → красный (<25 или просрочка). */
export function SlaBar({ pct, breached, className }: { pct: number | null | undefined; breached?: boolean; className?: string }) {
  const p = Math.max(0, Math.min(100, pct ?? 0))
  const over = breached || (pct !== null && pct !== undefined && pct < 0)
  const color = over || p < 25 ? 'bg-danger' : p < 50 ? 'bg-warn' : 'bg-ok'
  return (
    <div
      className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-raised', className)}
      title={over ? 'SLA просрочен' : `${Math.round(p)}% времени SLA осталось`}
    >
      <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${over ? 100 : p}%` }} />
    </div>
  )
}

export function Json({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre className={clsx('overflow-auto whitespace-pre-wrap break-words rounded-lg bg-raised p-2 font-mono text-[11.5px] leading-relaxed text-ink', className)}>
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function Pre({ value, className }: { value: string | null | undefined; className?: string }) {
  if (!value) return <span className="text-faint">—</span>
  return (
    <pre className={clsx('overflow-auto whitespace-pre-wrap break-words rounded-lg bg-raised p-2 font-mono text-[11.5px] leading-relaxed text-ink', className)}>
      {value}
    </pre>
  )
}
