import type { CustomSeriesRenderItem, EChartsOption } from 'echarts'
import type { CsiAnalytics } from './api'
import type { CsiPalette } from './palette'

type Text = (key: string) => string
const levels = ['high', 'medium', 'low', 'unknown'] as const

function base(colors: CsiPalette): EChartsOption {
  return {
    animation: false,
    textStyle: { color: colors.ink, fontFamily: 'Inter' },
    grid: { left: 16, right: 24, top: 32, bottom: 36, containLabel: true },
    tooltip: { renderMode: 'richText', confine: true },
    aria: { enabled: true },
  }
}

export function scatterOption(data: CsiAnalytics, colors: CsiPalette, text: Text): EChartsOption {
  const color = { high: colors.danger, medium: colors.warn, low: colors.ok, unknown: colors.muted }
  const symbol = { high: 'triangle', medium: 'diamond', low: 'circle', unknown: 'rect' }
  return {
    ...base(colors),
    legend: { data: levels.map(level => text('csi.level.' + level)), textStyle: { color: colors.muted } },
    xAxis: { type: 'value', min: 0, name: text('csi.wait'), nameLocation: 'middle', nameGap: 28 },
    yAxis: { type: 'value', min: 0, name: text('csi.service'), splitLine: { lineStyle: { color: colors.line } } },
    series: levels.map(level => ({
      type: 'scatter', name: text('csi.level.' + level), symbol: symbol[level], symbolSize: 7,
      itemStyle: { color: color[level], opacity: 0.75 },
      data: data.scatter.items.filter(item => (item.criticality ?? 'unknown') === level).map(item => ({ name: item.signal_ref, value: [item.wait_min, item.service_min] })),
    })),
  }
}

export function positionOption(data: CsiAnalytics, colors: CsiPalette, unknown: string): EChartsOption {
  return {
    ...base(colors),
    xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: colors.line } } },
    yAxis: { type: 'category', inverse: true, data: data.positions.map(row => row.position ?? unknown), axisLabel: { width: 130, overflow: 'truncate' } },
    series: [{ type: 'bar', data: data.positions.map(row => row.complaints), itemStyle: { color: colors.brand } }],
  }
}

export function tenureOption(data: CsiAnalytics, colors: CsiPalette, text: Text): EChartsOption {
  const renderItem: CustomSeriesRenderItem = (_params, api) => {
    const index = Number(api.value(0))
    const points = [1, 2, 3, 4, 5].map(dimension => api.coord([Number(api.value(dimension)), index]))
    const [minimum, q1, median, q3, maximum] = points
    const y = q1![1]!, height = 26
    return { type: 'group', children: [
      { type: 'line', shape: { x1: minimum![0]!, y1: y, x2: maximum![0]!, y2: y }, style: { stroke: colors.muted, lineWidth: 2 } },
      ...[minimum!, maximum!].map(point => ({ type: 'line' as const, shape: { x1: point[0]!, y1: y - 8, x2: point[0]!, y2: y + 8 }, style: { stroke: colors.muted, lineWidth: 2 } })),
      { type: 'rect', shape: { x: q1![0]!, y: y - height / 2, width: Math.max(1, q3![0]! - q1![0]!), height }, style: { fill: colors.surface, stroke: colors.brand, lineWidth: 2 } },
      { type: 'line', shape: { x1: median![0]!, y1: y - height / 2, x2: median![0]!, y2: y + height / 2 }, style: { stroke: colors.ink, lineWidth: 2 } },
    ] }
  }
  const values = data.tenure.groups.flatMap((row, index) => row.minimum == null || row.q1 == null || row.median == null || row.q3 == null || row.maximum == null ? [] : [[index, row.minimum, row.q1, row.median, row.q3, row.maximum]])
  return {
    ...base(colors),
    xAxis: { type: 'value', min: 0, name: text('csi.tenureDays'), nameLocation: 'middle', nameGap: 28, splitLine: { lineStyle: { color: colors.line } } },
    yAxis: { type: 'category', data: data.tenure.groups.map(row => text('csi.group.' + row.group)) },
    series: [{ type: 'custom', renderItem, data: values, encode: { x: [1, 2, 3, 4, 5], y: 0 } }],
  }
}

export function probabilityOption(data: CsiAnalytics['probabilities']['wait'], colors: CsiPalette, labels: string[]): EChartsOption {
  return {
    ...base(colors),
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: colors.line } } },
    series: [{ type: 'bar', itemStyle: { color: colors.info }, data: data.buckets.map(row => row.probability == null ? null : row.probability * 100) }],
  }
}

export function topOption(data: CsiAnalytics, colors: CsiPalette): EChartsOption {
  return {
    ...base(colors),
    xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: colors.line } } },
    yAxis: { type: 'category', inverse: true, data: data.top_branches.map(row => row.branch_code ?? String(row.branch_id)) },
    series: [{ type: 'bar', itemStyle: { color: colors.brand }, data: data.top_branches.map(row => row.complaints) }],
  }
}
