import type { ThemePack } from './types'

export type AttentionMode = 'calm' | 'control_room'
export function validAttention(value: unknown): AttentionMode | null {
  return value === 'calm' || value === 'control_room' ? value : null
}
/** Пресет представления не меняет права и серверные правила. Явный выбор важнее контекста. */
export function resolveAttention(explicit: AttentionMode | null, pack: ThemePack, pathname: string, role = 'cx_lead'): AttentionMode {
  if (explicit) return explicit
  if (/^\/cabinet(?:\/|$)/.test(pathname) || role === 'product_manager') return 'calm'
  return pack === 'ops' || role === 'demonstrator' ? 'control_room' : 'calm'
}
