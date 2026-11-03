import { expect, it } from 'vitest'
import { formatCompactRub } from '../compactMoney'

it.each([
  [null, '—', '—'], [undefined, '—', '—'], [NaN, '—', '—'], [Infinity, '—', '—'],
  [0, '0 ₽', '0 ₽'], [-0, '0 ₽', '0 ₽'],
  [999.99, '999,99 ₽', '999.99 ₽'], [1000, '1 000 ₽', '1,000 ₽'],
  [-456789, '−456 789 ₽', '−456,789 ₽'], [999999.99, '999 999,99 ₽', '999,999.99 ₽'],
  [1000000, '1 млн ₽', '1 m ₽'], [-1234567, '−1,23 млн ₽', '−1.23 m ₽'],
  [999999999, '1 млрд ₽', '1 bn ₽'], [1000000000, '1 млрд ₽', '1 bn ₽'],
  [-1234567890, '−1,23 млрд ₽', '−1.23 bn ₽'],
])('formats server amount %s without changing monetary semantics', (value, ru, en) => {
  expect(formatCompactRub(value as number | null | undefined, 'ru')).toBe(ru)
  expect(formatCompactRub(value as number | null | undefined, 'en')).toBe(en)
})
