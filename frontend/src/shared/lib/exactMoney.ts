/** Форматирование десятичной суммы, без Number и без расчёта dCLTV. */
export function formatExactRub(value: string | null, language: string): { compact: string; exact: string } {
  const match = value?.match(/^(-?)(\d+)(?:\.(\d+))?$/)
  if (!match) return { compact: '—', exact: '—' }
  const [, sign, integer = '0', fraction = ''] = match
  const base = 10n ** BigInt(fraction.length)
  const raw = BigInt(integer) * base + BigInt(fraction || '0')
  const prefix = sign && raw !== 0n ? '−' : ''
  const ru = !language.startsWith('en'), separator = ru ? ',' : '.'
  const format = new Intl.NumberFormat(ru ? 'ru-RU' : 'en-US')
  const exact = `${prefix}${format.format(BigInt(integer))}${separator}${fraction.padEnd(2, '0')} ₽`
  let scale = raw >= 1_000_000_000n * base ? 1_000_000_000n : raw >= 1_000_000n * base ? 1_000_000n : 1n
  const rounded = (unit: bigint) => (raw * 100n + base * unit / 2n) / (base * unit)
  if (scale === 1_000_000n && rounded(scale) >= 100_000n) scale = 1_000_000_000n
  const scaled = rounded(scale), whole = scaled / 100n, cents = (scaled % 100n).toString().padStart(2, '0').replace(/0+$/, '')
  const suffix = scale === 1_000_000_000n ? ru ? ' млрд' : ' bn' : scale === 1_000_000n ? ru ? ' млн' : ' m' : ''
  return { exact, compact: `${prefix}${format.format(whole)}${cents ? separator + cents : ''}${suffix} ₽` }
}
