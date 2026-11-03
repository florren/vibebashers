import type { SttProvider } from '@/shared/api/client'

/** Только единственный явно выбранный backend default; capability не является opt-in. */
export function selectedDefaultProvider(rows: readonly SttProvider[]): SttProvider | null {
  if (!Array.isArray(rows)) return null
  const defaults = rows.filter(row => row?.is_default === true)
  const selected = defaults.length === 1 ? defaults[0] : undefined
  return selected?.available === true && typeof selected.code === 'string' ? selected : null
}
