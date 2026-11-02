import type { TFunction } from 'i18next'
import type { Trace } from '@/shared/api/trace'

// Тексты обращения не должны становиться Markdown images/HTML при открытии экспорта.
const text = (value: unknown) => String(value ?? '').replace(/[\\`*_{}[\]()#+.!|>~<-]/g, '\\$&').replace(/\r?\n/g, ' ')

export function traceMarkdown(trace: Trace, scope: string, t: TFunction) {
  const lines = [
    `# ${text(trace.subject.ref)} · ${text(trace.subject.title_ru)}`,
    '',
    `${text(t('traceGraph.scope'))}: ${text(scope)}`,
    '',
    text(t('traceUi.exportSnapshot')),
  ]
  if (trace.stats.truncated_before || trace.stats.truncated_after) lines.push('', text(t('traceUi.truncated')))
  for (const phase of ['before', 'subject', 'after'] as const) {
    lines.push('', `## ${text(t(`traceUi.${phase}`))}`)
    if (phase === 'subject') {
      lines.push('', `${text(trace.subject.kind)} · ${text(trace.subject.ref)} · ${text(trace.subject.status)}`)
      continue
    }
    for (const event of trace[phase]) {
      lines.push(`- ${text(event.title_ru)} · ${text(event.brief_ru)}`)
      if (event.object_ref) lines.push(`  - ${text(event.object_ref.kind)}: ${text(event.object_ref.ref)}`)
      for (const fact of event.key_facts) lines.push(`  - ${text(fact.label_ru)}: ${text(fact.value_ru)}`)
    }
  }
  lines.push('', `## ${text(t('traceUi.terminal'))}`, '', text(trace.terminal.outcome_ru), '')
  for (const pending of trace.pending) lines.push(`- ${text(pending.kind_ru)} · ${text(pending.due_sim)}`)
  for (const group of trace.groups) lines.push(`- ${text(group.kind)}: ${group.count} · ${group.sample_refs.map(text).join(', ')}`)
  return lines.join('\n') + '\n'
}

export function downloadTrace(trace: Trace, scope: string, format: 'json' | 'md', t: TFunction) {
  const content = format === 'json'
    ? JSON.stringify({ export_version: 1, scope, note: t('traceUi.exportSnapshot'), trace }, null, 2) + '\n'
    : traceMarkdown(trace, scope, t)
  const url = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `trace-${encodeURIComponent(trace.subject.ref).slice(0, 180)}.${format}`
  document.body.append(anchor)
  try { anchor.click() } finally { anchor.remove(); URL.revokeObjectURL(url) }
}
