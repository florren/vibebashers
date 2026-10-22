import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import '@/shared/i18n'
import { GraphView } from '@/pages/engine/GraphView'

const graph = {
  version: 'v1',
  nodes: ['ingest', 'normalize', 'classify', 'decide', 'wait_human', 'apply_human_decision', 'act', 'close'].map((id) => ({
    id,
    label_ru: id,
    label_en: id,
    kind: 'tool' as const,
  })),
  edges: [
    { from: 'ingest', to: 'normalize' },
    { from: 'decide', to: 'wait_human', condition: 'needs_human' },
    { from: 'wait_human', to: 'apply_human_decision' },
    { from: 'apply_human_decision', to: 'act' },
  ],
}

describe('GraphView', () => {
  it('рисует все узлы и подсвечивает пройденные', () => {
    const { container } = render(<GraphView graph={graph} visited={new Set(['ingest', 'normalize'])} current="classify" outcome={null} />)
    expect(container.querySelectorAll('rect').length).toBeGreaterThanOrEqual(graph.nodes.length)
    expect(container.querySelectorAll('path.stroke-brand').length).toBe(1)
    expect(container.querySelector('.animate-pulse')).not.toBeNull()
  })
})
