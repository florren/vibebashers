import { useEffect, useRef } from 'react'
import { init, type EChartsOption } from 'echarts'
import { useTranslation } from 'react-i18next'
import type { Schemas } from '@/shared/api/client'

type Report = Schemas['CabinetReport']

/** Отдельный SVG без вкладок: чёрно-белая печать сохраняет маркеры/штриховку. */
export function ReportChart({ report, code }: { report: Report; code: Report['charts'][number]['code'] }) {
  const element = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()
  useEffect(() => {
    const node = element.current
    if (!node) return
    const chart = init(node, undefined, { renderer: 'svg' })
    const data = report.overview
    const option: EChartsOption = {
      animation: false, aria: { enabled: true }, textStyle: { color: '#202020', fontSize: 10 },
      grid: { left: 58, right: 12, top: 25, bottom: code === 'sources' ? 60 : 25 },
      legend: { textStyle: { color: '#202020', fontSize: 10 } },
      xAxis: { type: 'category', axisLabel: { color: '#202020', fontSize: 9, rotate: code === 'sources' ? 20 : 0 }, data: code === 'sources' ? data.sources.map(row => row.platform?.[report.lang === 'en' ? 'name_en' : 'name_ru'] ?? t('cabinet.unknownSource')) : code === 'daily' ? data.daily.map(row => row.day.slice(5)) : data.monthly.map(row => row.month.slice(0, 7)) },
      yAxis: { type: 'value', axisLabel: { color: '#202020', fontSize: 9 }, name: code === 'sources' ? t('cabinet.signals') : 'RUB' },
      series: code === 'sources' ? [{ name: t('cabinet.signals'), type: 'bar', color: '#444', itemStyle: { decal: { symbol: 'rect', dashArrayX: [1, 0], dashArrayY: [2, 4] } }, data: data.sources.map(row => row.signals) }] : [
        { name: t('cabinet.loss'), type: 'line', color: '#222', symbol: 'triangle', symbolSize: 5, connectNulls: false, data: (code === 'daily' ? data.daily : data.monthly).map(row => row.potential_loss_rub) },
        ...(code === 'daily' ? [{ name: t('cabinet.prevented'), type: 'line' as const, color: '#555', symbol: 'circle', symbolSize: 5, lineStyle: { type: 'dashed' as const }, connectNulls: false, data: data.daily.map(row => row.prevented_loss_rub) }] : []),
      ],
    }
    chart.setOption(option)
    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize); observer.observe(node)
    window.addEventListener('beforeprint', resize)
    return () => { observer.disconnect(); window.removeEventListener('beforeprint', resize); chart.dispose() }
  }, [report, code, t])
  return <div className="report-chart" ref={element} role="img" aria-label={report.charts.find(row => row.code === code)?.title_insight} />
}
