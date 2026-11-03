export function compareMessageTimes(a: string, b: string): number {
  const left = Date.parse(a), right = Date.parse(b)
  if (!Number.isFinite(left) || !Number.isFinite(right)) return 0
  if (left !== right) return left - right
  // Date теряет PostgreSQL microseconds: сохраняем их при совпадении milliseconds.
  const fraction = (value: string) => value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/i)?.[1] ?? ''
  const x = fraction(a), y = fraction(b), width = Math.max(x.length, y.length)
  const paddedX = x.padEnd(width, '0'), paddedY = y.padEnd(width, '0')
  return paddedX < paddedY ? -1 : paddedX > paddedY ? 1 : 0
}
