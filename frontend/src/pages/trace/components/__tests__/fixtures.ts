import type { Trace, TraceEvent, TraceRelationPage } from '@/shared/api/trace'

// Намеренно синтетические UI fixtures; настоящий API/PG проверяется отдельно.
export const event = (id: number, phase: TraceEvent['phase'] = 'after'): TraceEvent => ({
  id: `EVT-notification:${id}`, kind: 'notification', phase, ts_sim: null, ts_real: '2026-11-01T10:00:00Z',
  actor: { kind: 'system', label_ru: 'Система' }, object_ref: { kind: 'notification', ref: `NTF-${String(id).padStart(6, '0')}` },
  title_ru: `Сообщение ${id}`, brief_ru: 'Синтетическая проверка маски +7 *** ***-**-12', key_facts: [],
  badges: { llm_source: 'mock' }, links: { trace: `/trace/notification/NTF-${String(id).padStart(6, '0')}` }, importance: 'key', run_id: 'SR-000002',
})
export const traceFixture = (n = 4): Trace => ({
  subject: { kind: 'incident', ref: 'INC-000001', title_ru: 'Инцидент проверки графа' }, before: [], after: Array.from({ length: n }, (_, i) => event(i + 1)),
  edges: Array.from({ length: n }, (_, i) => ({ from: 'EVT-incident:1', to: event(i + 1).id, relation_ru: 'Привело к событию' })),
  groups: [{ kind: 'notification', count: 1001, sample_refs: ['NTF-000001', 'NTF-000002', 'NTF-000003'], phase: 'after', anchor: { kind: 'incident', ref: 'INC-000001', event_id: 'EVT-incident:1' } }],
  pending: [], terminal: { reached: true, event_ref: `EVT-notification:${n}`, outcome_ru: 'Работа завершена' }, stats: { before_count: 0, after_count: n, build_ms: 1 },
})
export const fanFixture = (offset = 0): TraceRelationPage => ({
  anchor: { kind: 'incident', ref: 'INC-000001', event_id: 'EVT-incident:1' }, direction: 'after', event_kind: 'notification', total: 1001,
  items: Array.from({ length: Math.min(50, 1001 - offset) }, (_, i) => event(offset + i + 1)),
  edges: Array.from({ length: Math.min(50, 1001 - offset) }, (_, i) => ({ from: 'EVT-incident:1', to: event(offset + i + 1).id, relation_ru: 'Привело к событию' })),
  next_cursor: offset + 50 < 1001 ? `synthetic-page-${offset + 50}` : null,
})
