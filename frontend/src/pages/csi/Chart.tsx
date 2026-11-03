import { init, type EChartsOption } from 'echarts'
import { useEffect, useRef } from 'react'

export function CsiChart({ option, label }: { option: EChartsOption; label: string }) {
  const element = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!element.current) return
    const chart = init(element.current, undefined, { renderer: 'svg' })
    chart.setOption(option)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => chart.resize())
    if (element.current) observer?.observe(element.current)
    return () => { observer?.disconnect(); chart.dispose() }
  }, [option])
  return <div ref={element} className="h-72 min-w-0 w-full" role="img" aria-label={label} />
}
