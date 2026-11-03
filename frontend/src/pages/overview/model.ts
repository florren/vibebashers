import { Criticality, Flag, SignalType } from '@/shared/contracts/enums'
import type { Schemas } from '@/shared/api/client'

/** Только поля визуальной проекции; контакты/сырой текст не сохраняются в её кеше. */
export function projectSignal(signal: Schemas['Signal']) {
  const raw = signal.classification?.negativity
  return {
    id: signal.id, public_id: signal.public_id, received_sim: signal.received_sim,
    channel_code: signal.channel_code, status: signal.status, origin: signal.origin,
    negativity: typeof raw === 'number' && Number.isInteger(raw) && raw >= 0 && raw <= 100 ? raw : null,
    criticality: Object.values(Criticality).includes(signal.classification?.criticality as Criticality) ? signal.classification!.criticality : null,
    signal_type: Object.values(SignalType).includes(signal.classification?.signal_type as SignalType) ? signal.classification!.signal_type : null,
    tone: signal.classification?.tone === 'sarcastic' ? 'sarcastic' : null,
    flags: Array.isArray(signal.classification?.flags) ? signal.classification.flags.filter(flag => Object.values(Flag).includes(flag)) : [], source_platform: signal.source_platform,
  }
}
export type ProjectedSignal = ReturnType<typeof projectSignal>

/** Угол зависит только от public ID, не от порядка/тональности/географии. */
export function signalAngle(id: string): number {
  let hash = 2166136261
  for (const code of id) { hash ^= code.codePointAt(0) ?? 0; hash = Math.imul(hash, 16777619) }
  return ((hash >>> 0) / 4294967296) * Math.PI * 2
}
export function projectionPoint(id: string, negativity: number) {
  const angle = signalAngle(id), radius = Math.max(0, Math.min(100, negativity)) * 1.25
  return { x: 160 + Math.cos(angle) * radius, y: 160 + Math.sin(angle) * radius }
}
export function customerWindow(rows: ProjectedSignal[], starts: string, ends: string) {
  const start = Date.parse(starts), end = Date.parse(ends)
  return rows.filter(row => row.origin !== 'proactive' && Date.parse(row.received_sim ?? '') > start && Date.parse(row.received_sim ?? '') <= end)
}
