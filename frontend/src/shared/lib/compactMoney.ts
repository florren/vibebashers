/** Только форматирование готовой серверной суммы; формулу dCLTV здесь не считаем. */
export function formatCompactRub(value: number | null | undefined, language: string): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const ru = !language.startsWith('en'), magnitude = Math.abs(value)
  let scale = magnitude >= 1e9 ? 1e9 : magnitude >= 1e6 ? 1e6 : 1
  // Округлённые 1000 млн показываем как 1 млрд, не изменяя исходную сумму.
  if (scale === 1e6 && Number((magnitude / scale).toFixed(2)) >= 1000) scale = 1e9
  const suffix = scale === 1e9 ? (ru ? ' млрд' : ' bn') : scale === 1e6 ? (ru ? ' млн' : ' m') : ''
  const number = new Intl.NumberFormat(ru ? 'ru-RU' : 'en-US', { maximumFractionDigits: 2 }).format(value === 0 ? 0 : value / scale).replace(/^-/, '−')
  return `${number}${suffix} ₽`
}
