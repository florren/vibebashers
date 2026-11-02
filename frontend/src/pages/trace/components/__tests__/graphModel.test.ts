import { describe, expect, it } from 'vitest'
import { buildGraph, directedPath, nodeFamily, nodeInViewport } from '../graphModel'
import { event, fanFixture, traceFixture } from './fixtures'

describe('trace graph uses only recorded topology', () => {
  it('identifies the one omitted subject endpoint and follows directed real edges', () => {
    const trace = traceFixture()
    trace.groups = []
    const model = buildGraph(trace)
    expect(model.subjectId).toBe('EVT-incident:1')
    expect([...model.path]).toEqual(['EVT-notification:4', 'EVT-incident:1'])
    expect([...model.pathEdges]).toEqual(['EVT-incident:1\0EVT-notification:4'])
    expect(model.edges).toEqual(trace.edges)
  })
  it('refuses ambiguous subjects and never fabricates links or a terminal path', () => {
    const trace = traceFixture()
    trace.edges.push({ from: 'EVT-unknown:2', to: event(1).id, relation_ru: 'Unknown' })
    const model = buildGraph(trace)
    expect(model.unresolved).toBe(true)
    expect(model.subjectId).toBe('subject:incident:INC-000001')
    expect(model.edges).toEqual([])
    expect(model.path.size).toBe(0)
    trace.edges = []; trace.groups = []
    expect(buildGraph(trace).path.size).toBe(0)
  })
  it('rejects conflicting recorded anchors and ignores hidden anchors/edge endpoints', () => {
    const trace = traceFixture()
    trace.groups.push({ ...trace.groups[0]!, anchor: { kind: 'incident', ref: 'INC-000001', event_id: 'EVT-incident:2' } })
    expect(buildGraph(trace).unresolved).toBe(true)
    trace.groups = [{ ...trace.groups[0]!, anchor: { kind: 'incident', ref: 'INC-000002', event_id: 'EVT-incident:2' } }]
    expect(buildGraph(trace).subjectId).toBe('EVT-incident:1')
  })
  it('deduplicates a full fan page and preserves actual anchor, direction and privacy projection', () => {
    const page = fanFixture()
    const model = buildGraph(traceFixture(), page)
    expect(model.nodes).toHaveLength(51)
    expect(model.edges).toHaveLength(50)
    expect(model.nodes.find((node) => node.id === event(1).id)?.event?.brief_ru).toContain('***')
    expect(model.nodes.every((node) => node.phase === 'subject' || node.phase === 'after')).toBe(true)
    expect(model.nodes.every((node) => node.x >= 372)).toBe(true)
  })
  it('keeps every fan item accessible when its recorded anchor is outside the base trace window', () => {
    const trace = traceFixture()
    trace.groups[0]!.anchor = { kind: 'incident', ref: 'INC-000002', event_id: 'EVT-incident:2' }
    const page = fanFixture()
    page.anchor = trace.groups[0]!.anchor
    page.edges = page.edges.map((edge) => ({ ...edge, from: page.anchor.event_id }))
    const model = buildGraph(trace, page)
    expect(model.nodes).toHaveLength(51)
    expect(model.hiddenEdges).toBe(50)
    expect(model.edges).toEqual(trace.edges)
    expect(model.nodes.some((node) => node.id === page.anchor.event_id)).toBe(false)
  })
  it('renders event semantics rather than an implementation step as its family', () => {
    const trace = traceFixture(1)
    trace.after[0] = { ...trace.after[0]!, kind: 'public_reply', object_ref: { kind: 'step', ref: 'AS-000001' } }
    expect(buildGraph(trace).nodes[1]?.family).toBe('message')
    trace.after[0] = { ...trace.after[0]!, kind: 'refund' }
    expect(buildGraph(trace).nodes[1]?.family).toBe('money')
  })
  it('uses cycle-safe directed paths and refuses unreachable or absent terminals', () => {
    const edges = [{ from: 'a', to: 'b', relation_ru: '' }, { from: 'b', to: 'a', relation_ru: '' }, { from: 'b', to: 'c', relation_ru: '' }]
    expect([...directedPath(edges, 'a', 'c')]).toEqual(['c', 'b', 'a'])
    expect(directedPath(edges, 'c', 'a').size).toBe(0)
    expect(directedPath(edges, 'a').size).toBe(0)
  })
  it('bounds visible DOM for 300 synthetic nodes while retaining keyboard/model access to every node', () => {
    // Нагрузка на UI-раскладку, без расширения контрактного лимита API after<=200.
    const started = performance.now()
    const model = buildGraph(traceFixture(299))
    const visible = model.nodes.filter((node) => nodeInViewport(node, { left: 0, top: 0, width: 1000, height: 420 }, 1))
    expect(model.nodes).toHaveLength(300)
    expect(visible.length).toBeLessThan(10)
    expect(model.nodes.at(-1)?.ref).toBe('NTF-000299')
    expect(performance.now() - started).toBeLessThan(100)
  })
  it('distinguishes all six visual families without depending on private numeric IDs', () => {
    expect(['signal_created', 'incident', 'client', 'task', 'refund', 'notification'].map(nodeFamily)).toEqual(['signal', 'incident', 'client', 'action', 'money', 'message'])
  })
})
