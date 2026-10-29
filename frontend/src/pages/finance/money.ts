import i18n from '@/shared/i18n'

/** Денежный результат и обоснование всегда показывают копейки. */
export function formatMoney(value: number | null | undefined, maximumFractionDigits = 2): string {
  if (value == null) return '—'
  return new Intl.NumberFormat(i18n.language.startsWith('en') ? 'en-US' : 'ru-RU', {
    style: 'currency', currency: 'RUB', minimumFractionDigits: 2, maximumFractionDigits,
  }).format(value)
}
