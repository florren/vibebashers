export { formatCompactRub as compactMoney } from '@/shared/lib/compactMoney'

export function cabinetPercent(value: number | null, language: string): string {
  return value == null ? '—' : new Intl.NumberFormat(language.startsWith('en') ? 'en-US' : 'ru-RU', { style: 'percent', maximumFractionDigits: 1 }).format(value)
}
