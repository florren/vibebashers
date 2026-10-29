import { describe, expect, it } from 'vitest'
import { MAP_HEIGHT, MAP_WIDTH, RUSSIA, russiaProjection } from '../russia'

describe('проекция карты', () => {
  it('вписывает каждый полигон целиком, включая южные регионы и Чукотку', () => {
    const { path } = russiaProjection()
    expect(RUSSIA.features).toHaveLength(83)
    for (const region of RUSSIA.features) {
      const [[left, top], [right, bottom]] = path.bounds(region)
      expect(left, region.properties.code).toBeGreaterThanOrEqual(15.99)
      expect(top, region.properties.code).toBeGreaterThanOrEqual(15.99)
      expect(right, region.properties.code).toBeLessThanOrEqual(MAP_WIDTH - 15.99)
      expect(bottom, region.properties.code).toBeLessThanOrEqual(MAP_HEIGHT - 15.99)
    }
  })

  it('сохраняет запас вокруг маркеров регионов без полигонов', () => {
    const points: [number, number][] = [[34.1, 44.6], [33.5, 44.6], [37.8, 48], [39.3, 48.6], [35.2, 47.8], [32.6, 46.6]]
    const { projection, path } = russiaProjection(points)
    for (const coordinates of points) {
      const [x, y] = projection(coordinates)!
      expect(x - 6).toBeGreaterThanOrEqual(0)
      expect(y - 6).toBeGreaterThanOrEqual(0)
      expect(x + 6).toBeLessThanOrEqual(MAP_WIDTH)
      expect(y + 6).toBeLessThanOrEqual(MAP_HEIGHT)
    }
    const [[left, top], [right, bottom]] = path.bounds(RUSSIA)
    expect(left).toBeGreaterThanOrEqual(0)
    expect(top).toBeGreaterThanOrEqual(0)
    expect(right).toBeLessThanOrEqual(MAP_WIDTH)
    expect(bottom).toBeLessThanOrEqual(MAP_HEIGHT)
  })
})
