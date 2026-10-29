import { expect, it } from 'vitest'
import type { AgentRunDetail, AgentStep } from '@/shared/api/client'
import type { TraceEvent } from '@/shared/api/trace'
import { eventStep, relatedEvents, selectedAttempt, nodeStatus, observedEdges, stepFacts } from '../stepSelection'

const event = (link?: string, ref = 'NTF-000007'): TraceEvent => ({
  id: ref,
  kind: 'notification',
  phase: 'after',
  ts_real: '2026-10-29T10:00:00Z',
  ts_sim: null,
  actor: { kind: 'agent', label_ru: 'Агент' },
  title_ru: 'Ответ',
  brief_ru: 'Отправлен',
  key_facts: [],
  badges: {},
  links: link ? { engine_step: link } : {},
  importance: 'key',
  run_id: 'SR-1',
  object_ref: { kind: 'notification', ref },
})
it('parses the recorded engine run and sequence, not the simulation run', () => {
  expect(eventStep(event('/engine/12?tab=steps&step=3'))).toEqual({ runId: 12, seq: 3 })
  for (const link of ['/engine/0?step=1', '/engine/12?step=0', '/engine/12', '/engine/12?step=x']) expect(eventStep(event(link))).toBeNull()
})
it('isolates runs and retries and uses only recorded write results for object links', () => {
  const direct = event('/engine/10?step=3', 'NTF-000001')
  const foreign = event('/engine/11?step=3', 'NTF-000007')
  const older = event('/engine/10?step=2', 'NTF-000002')
  const object = event()
  const step: AgentStep = { seq: 3, tool_calls: [{ name: 'notify_client', result: { notification_id: 7 } }] }
  expect(relatedEvents([direct, foreign, older, object], 10, step)).toEqual([direct, object])
  expect(relatedEvents([object], 10, { seq: 3, tool_calls: [{ name: 'read_incident', result: { notification_id: 7 } }] })).toEqual([])
  expect(relatedEvents([object], 10, { seq: 3, tool_calls: [{ name: 'notify_client', result: {} }] })).toEqual([])
  expect(relatedEvents([object], 10, undefined)).toEqual([])
})
it('selects an exact retry and cannot cross into another run', () => {
  const steps: AgentStep[] = [
    { seq: 1, node: 'classify', status: 'error' },
    { seq: 2, node: 'classify', status: 'ok' },
  ]
  const run: AgentRunDetail = { id: 10, steps }
  expect(selectedAttempt(run, { runId: 10, seq: 1 })).toBe(steps[0])
  expect(selectedAttempt(run, { runId: 10, node: 'classify' })).toBe(steps[1])
  expect(selectedAttempt(run, { runId: 11, seq: 1 })).toBeUndefined()
  expect(selectedAttempt({}, null)).toBeUndefined()
})
it('distinguishes unused branches, waiting, scheduled and retry outcomes', () => {
  expect(nodeStatus({ outcome: 'completed' }, 'verify', null)).toBe('skipped')
  expect(nodeStatus({ outcome: 'failed' }, 'verify', null)).toBe('not_reached')
  expect(nodeStatus({}, 'verify', null)).toBe('pending')
  expect(nodeStatus({ outcome: 'awaiting_human' }, 'wait_human', 'wait_human')).toBe('waiting_human')
  expect(nodeStatus({ outcome: 'deferred', steps: [{ node: 'followup_monitor' }] }, 'followup_monitor', null)).toBe('scheduled')
  expect(
    nodeStatus(
      {
        steps: [
          { node: 'classify', status: 'error' },
          { node: 'classify', status: 'fallback' },
        ],
      },
      'classify',
      null,
    ),
  ).toBe('fallback')
})
it('highlights only recorded consecutive transitions, never inferred branches or gaps', () => {
  expect([
    ...observedEdges([
      { seq: 4, node: 'act' },
      { seq: 1, node: 'classify' },
      { seq: 2, node: 'decide' },
      { seq: 5, node: 'act' },
    ]),
  ]).toEqual(['classify>decide'])
})
it('exposes only validated business codes and numbers, never free LLM text', () => {
  const facts = stepFacts({
    output: { product: null, confidence: 0.93, sentiment: 'negative', router_action: 'route', prompt: 'SECRET', summary: 'SECRET', route: { team: 'SECRET' } },
    response_raw: 'SECRET',
    reasoning: 'SECRET',
  })
  expect(facts).toEqual([
    { label: 'product', value: null },
    { label: 'confidence', value: 93 },
    { label: 'sentiment', value: 'negative' },
    { label: 'action', value: 'route' },
  ])
  expect(stepFacts({ output: { product: 'SECRET', confidence: 2, sentiment: 'SECRET' } })).toEqual([])
})

it('does not claim subsequent incident status or a human answer from an earlier request', () => {
  const status: TraceEvent = { ...event(), kind: 'incident_status', object_ref: { kind: 'incident', ref: 'INC-000007' } }
  const answer: TraceEvent = { ...event(), kind: 'human_decision', object_ref: { kind: 'human_decision', ref: 'HD-000007' } }
  expect(
    relatedEvents([status, answer], 10, {
      seq: 1,
      tool_calls: [
        { name: 'create_incident', result: { incident_id: 7 } },
        { name: 'request_human_decision', result: { human_decision_id: 7 } },
      ],
    }),
  ).toEqual([])
  const refund: TraceEvent = { ...event(), kind: 'refund', object_ref: { kind: 'ledger', ref: 'LED-000007' } }
  expect(relatedEvents([refund], 10, { seq: 2, tool_calls: [{ name: 'refund_fee', result: { entry_id: 7 } }] })).toEqual([refund])
})
