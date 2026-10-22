import { format, formatDistanceStrict, parseISO } from 'date-fns'
import { ru } from 'date-fns/locale'

/** Симуляционное время приходит в UTC ISO; показываем как есть (без сдвига на пояс браузера). */
export function simDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const d = parseISO(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export function fmtSim(iso: string | null | undefined, pattern = 'dd.MM HH:mm'): string {
  const d = simDate(iso)
  if (!d) return '—'
  const utc = new Date(d.getTime() + d.getTimezoneOffset() * 60_000)
  return format(utc, pattern, { locale: ru })
}

export function fmtClock(iso: string | null | undefined): string {
  return fmtSim(iso, 'HH:mm')
}

export function fmtDateTime(iso: string | null | undefined): string {
  const d = simDate(iso)
  return d ? format(d, 'dd.MM HH:mm:ss', { locale: ru }) : '—'
}

export function fmtDuration(fromIso: string | null | undefined, toIso: string | null | undefined): string {
  const a = simDate(fromIso)
  const b = simDate(toIso)
  if (!a || !b) return '—'
  return formatDistanceStrict(b, a, { locale: ru })
}

export function fmtRub(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(v)} ₽`
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  return ms < 1000 ? `${ms} мс` : `${(ms / 1000).toFixed(1)} с`
}

export function shortId(n: number | undefined, prefix: string): string {
  return n === undefined ? '—' : `${prefix}-${String(n).padStart(6, '0')}`
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}
