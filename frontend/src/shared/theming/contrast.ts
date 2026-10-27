/** Относительная яркость sRGB (WCAG 2.x) для тройки 0–255. */
export function relativeLuminance(rgb: [number, number, number]): number {
  const linear = rgb.map((c) => {
    const x = c / 255
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
  }) as [number, number, number]
  const [r, g, b] = linear
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(fg: [number, number, number], bg: [number, number, number]): number {
  const l1 = relativeLuminance(fg)
  const l2 = relativeLuminance(bg)
  const lighter = Math.max(l1, l2)
  const darker = Math.min(l1, l2)
  return (lighter + 0.05) / (darker + 0.05)
}
