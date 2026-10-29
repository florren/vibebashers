import { geoConicConformal, geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import type { FeatureCollection, Geometry } from 'geojson'
import type { Topology, GeometryCollection } from 'topojson-specification'
import topoRaw from './russia-regions.topo.json'

type RegionProps = { code: string; name: string }
const topo = topoRaw as unknown as Topology<{ regions: GeometryCollection<RegionProps> }>
export const RUSSIA = feature(topo, topo.objects.regions) as FeatureCollection<Geometry, RegionProps>
export const MAP_WIDTH = 960
export const MAP_HEIGHT = 540

/** Вписываем и полигоны, и центроиды: регионы без полигона не должны оказаться за краем SVG. */
export function russiaProjection(points: [number, number][] = []) {
  const extent: FeatureCollection = {
    type: 'FeatureCollection',
    features: [...RUSSIA.features, ...points.map((coordinates) => ({
      type: 'Feature' as const,
      properties: {},
      geometry: { type: 'Point' as const, coordinates },
    }))],
  }
  const projection = geoConicConformal()
    .rotate([-105, 0]).center([0, 63]).parallels([52, 64])
    .fitExtent([[16, 16], [MAP_WIDTH - 16, MAP_HEIGHT - 16]], extent)
  return { projection, path: geoPath(projection) }
}
