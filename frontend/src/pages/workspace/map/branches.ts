import type { Schemas } from '@/shared/api/client'

export type BranchRecord = Schemas['BranchRecord']
export type BranchPoint = { branch: BranchRecord; x: number; y: number }
export type BranchCluster = { key: string; items: BranchPoint[]; anchor: BranchPoint }
export type MapViewport = { scale: number; x: number; y: number; width: number; height: number }

/** Decimal-string из API: пустое/hex/Infinity не становятся координатой0. */
export function coordinate(value: string | null, limit: number): number | null {
  if (value == null || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null
  const number = Number(value)
  return Number.isFinite(number) && Math.abs(number) <= limit ? number : null
}

export function projectBranches(branches: readonly BranchRecord[], project: (point: [number, number]) => [number, number] | null) {
  const points: BranchPoint[] = []
  const unlocated: BranchRecord[] = []
  for (const branch of branches) {
    const lat = coordinate(branch.lat, 90), lon = coordinate(branch.lon, 180)
    const point = lat == null || lon == null ? null : project([lon, lat])
    if (!point || !point.every(Number.isFinite)) unlocated.push(branch)
    else points.push({ branch, x: point[0], y: point[1] })
  }
  return { points, unlocated }
}

/** Кластеризуем расстояния в CSS pixels, не в географических градусах.
 * Anchor — исходная точка одного ВСП: не выдаём среднее/случайное смещение за его координаты.
 * Все точки в группе остаются доступны списком, в том числе при одинаковых координатах.
 */
export function clusterBranches(points: readonly BranchPoint[], viewport: MapViewport, spacing: number): BranchCluster[] {
  if (![viewport.scale, viewport.width, viewport.height, spacing].every(value => Number.isFinite(value) && value > 0) || ![viewport.x, viewport.y].every(Number.isFinite)) throw new RangeError('Некорректный viewport карты')
  const ordered = [...points].sort((a, b) => a.branch.code.localeCompare(b.branch.code))
  const ratio = Math.min(viewport.width / 960, viewport.height / 540)
  const pixels = ordered.map(point => ({ x: (point.x * viewport.scale + viewport.x) * ratio, y: (point.y * viewport.scale + viewport.y) * ratio }))
  const roots = ordered.map((_, index) => index)
  const root = (index: number): number => {
    while (roots[index] !== index) { roots[index] = roots[roots[index]!]!; index = roots[index]! }
    return index
  }
  const cells = new Map<string, number[]>()
  for (let index = 0; index < ordered.length; index++) {
    const point = pixels[index]!, column = Math.floor(point.x / spacing), row = Math.floor(point.y / spacing)
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const other of cells.get(`${column + dx}:${row + dy}`) ?? []) {
        if (root(index) !== root(other) && Math.hypot(point.x - pixels[other]!.x, point.y - pixels[other]!.y) < spacing) roots[root(index)] = root(other)
      }
    }
    const key = `${column}:${row}`
    cells.set(key, [...(cells.get(key) ?? []), index])
  }
  const groups = new Map<number, BranchPoint[]>()
  ordered.forEach((point, index) => { const key = root(index); groups.set(key, [...(groups.get(key) ?? []), point]) })
  return [...groups.values()].map(items => ({ key: items.map(point => point.branch.code).join('|'), items, anchor: items[0]! })).sort((a, b) => a.key.localeCompare(b.key))
}

export const BRANCH_STYLE = {
  flagship: { color: '#6366F1', radius: 7, dash: undefined },
  standard: { color: '#0D9488', radius: 5, dash: undefined },
  additional: { color: '#6B7280', radius: 3.5, dash: undefined },
  mobile: { color: '#D97706', radius: 5, dash: '2 2' },
} as const
