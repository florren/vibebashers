import { useEffect, useState } from 'react'

export type CsiPalette = Record<'ink' | 'muted' | 'line' | 'surface' | 'brand' | 'danger' | 'warn' | 'ok' | 'info', string>

function palette(): CsiPalette {
  const style = getComputedStyle(document.documentElement)
  return Object.fromEntries(['ink', 'muted', 'line', 'surface', 'brand', 'danger', 'warn', 'ok', 'info'].map(key => {
    const raw = style.getPropertyValue('--' + key).trim()
    return [key, raw ? `rgb(${raw.replace(/\s+/g, ',')})` : '#526170']
  })) as CsiPalette
}

export function useCsiPalette(): CsiPalette {
  const [colors, setColors] = useState(palette)
  useEffect(() => {
    const root = document.documentElement
    const observer = new MutationObserver(() => {
      // Circadian transition заканчивается штатно; графики не пересоздаются
      // на каждом промежуточном кадре palette animation.
      if (root.dataset.themeTransition === 'running') return
      const next = palette()
      setColors(old => JSON.stringify(old) === JSON.stringify(next) ? old : next)
    })
    observer.observe(root, { attributes: true, attributeFilter: ['class', 'data-mode', 'data-pack', 'data-phase', 'data-theme-transition'] })
    return () => observer.disconnect()
  }, [])
  return colors
}

