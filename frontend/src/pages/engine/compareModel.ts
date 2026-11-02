import type { Classification } from '@/shared/api/client'

/** Порядок ключей объекта не является отличием; порядок массивов сохраняет смысл. */
export function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(',')}}`
  return JSON.stringify(value) ?? 'undefined'
}
export function comparisonFields(a: Classification, b: Classification) {
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(key => !['rationale_ru', 'summary_ru'].includes(key)).map(key => ({ key, changed: stable(a[key as keyof Classification]) !== stable(b[key as keyof Classification]) }))
}
export function sourceOf(model?: string | null): 'mock' | 'replay' | 'live' | 'unknown' {
  if (model?.startsWith('mock:')) return 'mock'
  if (model?.startsWith('replay:')) return 'replay'
  if (model?.startsWith('gigachat:') || model?.startsWith('openai_compatible:') || model?.startsWith('openai_compat:')) return 'live'
  return 'unknown'
}
