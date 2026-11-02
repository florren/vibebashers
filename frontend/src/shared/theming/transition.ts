import { contrastRatio } from './contrast'

type RGB = [number, number, number]
export type Palette = Record<string, RGB>
export const BACKGROUNDS = ['bg', 'surface', 'raised', 'brand-soft', 'trace-before', 'trace-subject', 'trace-after']
export const FOREGROUNDS = ['ink', 'muted', 'faint', 'brand-foreground', 'ok', 'warn', 'danger', 'info', 'control-line', 'focus-ring', 'brand-strong']
export const DECORATIVE = ['line', 'brand']
export const PALETTE_KEYS = [...BACKGROUNDS, ...FOREGROUNDS, ...DECORATIVE, 'on-brand']
export const TRANSITION_MS = 8000
const mix = (a: RGB, b: RGB, t: number): RGB => a.map((v, i) => Math.round(v + (b[i]! - v) * t)) as RGB
const BLACK: RGB = [0, 0, 0]
const WHITE: RGB = [255, 255, 255]

function readable(color: RGB, backgrounds: RGB[], polarity: RGB, minimum: number): RGB {
  const passes = (c: RGB) => backgrounds.every((bg) => contrastRatio(c, bg) >= minimum)
  if (passes(color)) return color
  let low = 0, high = 1
  for (let i = 0; i < 14; i++) {
    const mid = (low + high) / 2
    if (passes(mix(color, polarity, mid))) high = mid
    else low = mid
  }
  return mix(color, polarity, high)
}

/** Поверхности сходятся в одну нейтральную плоскость при смене полярности текста.
 * Непрерывный переход самого текста через серый нарушил бы WCAG; полярность меняется дискретно. */
export function transitionPalette(from: Palette, to: Palette, progress: number): Palette {
  const t = Math.min(1, Math.max(0, progress))
  const out: Palette = {}
  const center = mix(from.bg!, to.bg!, t)
  const spread = Math.max(0, 1 - Math.sin(Math.PI * t) * 2)
  for (const key of BACKGROUNDS) out[key] = mix(center, mix(from[key]!, to[key]!, t), spread)
  let backgrounds = BACKGROUNDS.map((key) => out[key]!)
  const score = (color: RGB) => Math.min(...backgrounds.map((bg) => contrastRatio(color, bg)))
  // На границе полярности разные поверхности не могут иметь общий читаемый цвет.
  if (Math.max(score(BLACK), score(WHITE)) < 4.5) {
    for (const key of BACKGROUNDS) out[key] = center
    backgrounds = BACKGROUNDS.map((key) => out[key]!)
  }
  const polarity = score(BLACK) >= score(WHITE) ? BLACK : WHITE
  for (const key of FOREGROUNDS) out[key] = readable(mix(from[key]!, to[key]!, t), backgrounds, polarity, key === 'control-line' || key === 'focus-ring' ? 3 : 4.5)
  for (const key of DECORATIVE) out[key] = mix(from[key]!, to[key]!, t)
  out['on-brand'] = contrastRatio(BLACK, out['brand-strong']!) >= contrastRatio(WHITE, out['brand-strong']!) ? BLACK : WHITE
  return out
}

let frame: number | null = null
export function cancelThemeTransition() {
  if (frame !== null) cancelAnimationFrame(frame)
  frame = null
}
export function readPalette(root: HTMLElement): Palette | null {
  const style = getComputedStyle(root)
  const palette: Palette = {}
  for (const key of PALETTE_KEYS) {
    const rgb = style.getPropertyValue(`--${key}`).trim().split(/\s+/).map(Number)
    if (rgb.length !== 3 || rgb.some((v) => !Number.isFinite(v))) return null
    palette[key] = rgb as RGB
  }
  return palette
}
export function clearPalette(root: HTMLElement) {
  for (const key of PALETTE_KEYS) root.style.removeProperty(`--${key}`)
}
export function animateTheme(root: HTMLElement, from: Palette, to: Palette) {
  const start = performance.now()
  const draw = (now: number) => {
    const progress = Math.min(1, (now - start) / TRANSITION_MS)
    const palette = transitionPalette(from, to, progress)
    for (const [key, color] of Object.entries(palette)) root.style.setProperty(`--${key}`, color.join(' '))
    if (progress < 1) frame = requestAnimationFrame(draw)
    else { frame = null; clearPalette(root); root.dataset.themeTransition = 'idle' }
  }
  root.dataset.themeTransition = 'running'
  draw(start)
}
