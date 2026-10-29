import type { Journey, TraceEvent } from '@/shared/api/trace'
export const stages = ['intake', 'understanding', 'identity', 'rules', 'decision', 'action', 'execution', 'client_outcome'] as const
export function recording(scenario: 1 | 8 | 11): Journey {
  const events: [TraceEvent, TraceEvent] = [
    {
      id: 'intake',
      kind: 'signal_created',
      phase: 'subject',
      ts_real: '2026-10-29T09:00:00Z',
      ts_sim: '2026-11-10T12:00:00Z',
      actor: { kind: 'system', label_ru: 'Система' },
      title_ru: 'Обращение принято',
      brief_ru: `Сценарий ${scenario}`,
      key_facts: [{ label_ru: 'Заметка ведущего', value_ru: `Тезис сценария ${scenario}`, masked: false }],
      badges: { llm_source: 'mock' },
      links: {},
      importance: 'key',
      run_id: 'SR-0001',
    },
    {
      id: 'decision',
      kind: scenario === 1 ? 'human_request' : scenario === 8 ? 'refund' : 'escalation',
      phase: 'after',
      ts_real: '2026-10-29T09:01:00Z',
      ts_sim: '2026-11-10T12:00:00Z',
      actor: { kind: 'agent', label_ru: 'Агент' },
      title_ru: scenario === 1 ? 'Решение человека' : scenario === 8 ? 'Комиссия возвращена' : 'Эскалация',
      brief_ru: 'Фактический исход',
      key_facts: [],
      badges: { llm_source: 'mock' },
      links: {},
      importance: 'key',
      run_id: 'SR-0001',
    },
  ]
  return {
    subject: { kind: 'signal', ref: `SIG-00000${scenario}`, title_ru: 'Запись' },
    stages: stages.map((stage, i) => ({ stage, status: 'done', events: i === 0 ? [events[0]] : i === 4 ? [events[1]] : [] })),
    client_lane: [{ channel_code: 'chat', kind: 'final', text_ru: 'Ответ банка', delivered_at: '2026-10-29T09:01:01Z' }],
    summary: { outcome_ru: 'Завершено', llm_source: 'mock' },
  }
}
