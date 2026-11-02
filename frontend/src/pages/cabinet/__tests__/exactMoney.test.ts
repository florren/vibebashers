import { expect, it } from 'vitest'
import { formatExactRub } from '@/shared/lib/exactMoney'

it('preserves every cent above Number/Excel precision while formatting compact presentation', () => {
  const ru = formatExactRub('10999999999999.89', 'ru')
  expect(ru.exact.replace(/\s/g,'')).toBe('10999999999999,89₽')
  expect(ru.compact).toContain('млрд')
  expect(formatExactRub('900719925474099.93','en').exact).toBe('900,719,925,474,099.93 ₽')
})
it('handles known zero, missing values, negative sign, scales and display rounding without altering exact values', () => {
  expect(formatExactRub(null,'ru')).toEqual({ compact:'—',exact:'—' })
  expect(formatExactRub('0','en')).toEqual({ compact:'0 ₽',exact:'0.00 ₽' })
  expect(formatExactRub('-0.00','en').exact).toBe('0.00 ₽')
  expect(formatExactRub('-1234567.89','en').compact).toBe('−1.23 m ₽')
  expect(formatExactRub('999999999.99','en').compact).toBe('1 bn ₽')
  expect(formatExactRub('12.3456','en').exact).toBe('12.3456 ₽')
  expect(formatExactRub('1e20','en').exact).toBe('—')
})
