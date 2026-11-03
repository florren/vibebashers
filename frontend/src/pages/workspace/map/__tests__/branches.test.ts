import { describe, expect, it } from 'vitest'
import { BRANCH_STYLE, clusterBranches, coordinate, projectBranches, type BranchPoint, type BranchRecord } from '../branches'

const branch = (code: string, lat: string | null = '55', lon: string | null = '37'): BranchRecord => ({ id: Number(code.slice(-1)), code, name_ru: 'Учебное ВСП', region_code: '77', region_okato: '45', city_name: 'Москва', desks: 1, branch_type: 'standard', branch_status: 'open', lat, lon, address_ru: null, hours_ru: null, opened_sim: null, closed_sim: null, product_line_codes: ['deposits'] })
const point = (code: string, x: number, y = 200): BranchPoint => ({ branch: branch(code), x, y })
const viewport = { scale: 1, x: 0, y: 0, width: 960, height: 540 }

describe('native coordinates and visual clustering', () => {
  it.each(['', ' ', '0x10', 'Infinity', 'NaN', '91', '-91'])('rejects invalid latitude %s without a fake point', value => expect(coordinate(value, 90)).toBeNull())
  it('preserves valid zero/decimal values and counts unlocated records', () => {
    expect(coordinate('0', 90)).toBe(0)
    const source = [branch('VSP-1'), branch('VSP-2', null), branch('VSP-3', '55', '181')]
    const result = projectBranches(source, ([lon, lat]) => [lon, lat])
    expect(result.points.map(p => [p.x, p.y])).toEqual([[37, 55]])
    expect(result.unlocated.map(p => p.code)).toEqual(['VSP-2', 'VSP-3'])
    expect(source[1]!.lat).toBeNull()
  })
  it('merges neighbouring grid cells and splits after actual zoom', () => {
    const source = [point('VSP-1', 43), point('VSP-2', 45), point('VSP-3', 100)]
    expect(clusterBranches(source, viewport, 44).map(c => c.items.length)).toEqual([2, 1])
    expect(clusterBranches(source, { ...viewport, scale: 30 }, 44)).toHaveLength(3)
  })
  it('uses CSS viewport size and keeps every co-located branch accessible', () => {
    const source = [point('VSP-1', 100), point('VSP-2', 160), point('VSP-3', 160)]
    expect(clusterBranches(source, viewport, 44).map(c => c.items.length)).toEqual([1, 2])
    const compact = clusterBranches(source, { ...viewport, width: 320, height: 180 }, 44)
    expect(compact).toHaveLength(1)
    expect(compact[0]!.items.map(p => p.branch.code)).toEqual(['VSP-1', 'VSP-2', 'VSP-3'])
    expect(compact[0]!.anchor).toBe(source[0])
    expect(clusterBranches([...source].reverse(), viewport, 44)).toEqual(clusterBranches(source, viewport, 44))
  })
  it('preserves type data colours and refuses unusable viewport', () => {
    expect(Object.values(BRANCH_STYLE).map(style => style.color)).toEqual(['#6366F1', '#0D9488', '#6B7280', '#D97706'])
    expect(BRANCH_STYLE.mobile.dash).toBe('2 2')
    expect(() => clusterBranches([], { ...viewport, width: 0 }, 44)).toThrow(RangeError)
  })
})
