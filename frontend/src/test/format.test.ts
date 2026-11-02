import { describe, expect, it } from 'vitest'
import { fmtMs, fmtRub, fmtSim, fmtSimMoscow, shortId } from '@/shared/lib/format'
import { qs } from '@/shared/api/client'
import i18n from '@/shared/i18n'

describe('format', () => {
  it('fmtSim показывает симуляционное время без сдвига пояса', () => {
    expect(fmtSim('2026-11-09T09:18:00+00:00')).toBe('09.11 09:18')
    expect(fmtSim(null)).toBe('—')
  })
  it('operator clock uses Moscow independently of the device timezone and DST', async () => {
    expect(fmtSimMoscow('2026-11-09T06:00:00Z')).toBe('09.11 09:00')
    expect(fmtSimMoscow('2026-11-09T06:00:00Z', 'EEE dd.MM HH:mm')).toBe('пн 09.11 09:00')
    expect(fmtSimMoscow('2026-03-08T06:00:00Z')).toBe('08.03 09:00')
    expect(fmtSimMoscow(null)).toBe('—')
    expect(fmtSimMoscow('invalid')).toBe('—')
    await i18n.changeLanguage('en')
    expect(fmtSimMoscow('2026-11-09T06:00:00Z', 'EEE dd.MM HH:mm')).toBe('Mon 09.11 09:00')
    await i18n.changeLanguage('ru')
  })
  it('fmtMs / fmtRub / shortId', async () => {
    expect(fmtMs(120)).toBe('120 мс')
    expect(fmtMs(2300)).toBe('2.3 с')
    expect(fmtRub(3200)).toMatch(/3\s200 ₽/)
    expect(shortId(42, 'INC')).toBe('INC-000042')
    await i18n.changeLanguage('en')
    expect(fmtMs(120)).toBe('120 ms')
    expect(fmtMs(2300)).toBe('2.3 s')
    expect(fmtRub(3200)).toMatch(/3,200 ₽/)
    await i18n.changeLanguage('ru')
    expect(i18n.language).toBe('ru')
  })
  it('qs пропускает пустые значения и разворачивает массивы', () => {
    expect(qs({ a: 1, b: undefined, c: '', d: ['x', 'y'] })).toBe('?a=1&d=x&d=y')
    expect(qs()).toBe('')
  })
})
