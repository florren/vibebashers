export function compactMoney(value: number | null | undefined, language: string) {
  return value == null ? '—' : new Intl.NumberFormat(language.startsWith('en') ? 'en-US' : 'ru-RU', { notation: 'compact', style: 'currency', currency: 'RUB', maximumFractionDigits: 2 }).format(value)
}
