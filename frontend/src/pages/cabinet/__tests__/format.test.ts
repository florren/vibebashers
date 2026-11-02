import { expect, it } from 'vitest'
import { cabinetPercent, compactMoney } from '../format'
it('keeps unknown separate from a known zero and localizes percent separators', () => {
  expect(cabinetPercent(null, 'ru')).toBe('—')
  expect(cabinetPercent(0, 'en')).toBe('0%')
  expect(cabinetPercent(.919, 'ru')).toMatch(/^91,9\s?%$/)
  expect(cabinetPercent(.919, 'en')).toBe('91.9%')
})
it('formats large money in locale without inventing a value for missing economics', () => {
  expect(compactMoney(null, 'ru')).toBe('—')
  expect(compactMoney(1230000, 'ru')).toContain('1,23')
  expect(compactMoney(1230000, 'en')).toContain('1.23')
})
