import type { LlmApiKey, LlmProfileT, TestLlmBody } from '@/shared/api/client'

export type BindingContext = { openaiEndpoint?: string; gigaScope?: string }
export type BindingIssue = 'loading' | 'missing' | 'inactive' | 'provider' | 'endpoint' | 'scope' | 'invalidUrl'
export function endpoint(value: string): string | undefined {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return undefined
    return value.replace(/\/+$/, '')
  } catch { return undefined }
}
export function bindingIssue(profile: LlmProfileT, keys: LlmApiKey[] | undefined, context: BindingContext): BindingIssue | undefined {
  const explicit = profile.base_url?.trim()
  if (explicit && !endpoint(explicit)) return 'invalidUrl'
  if (profile.api_key_id == null) return undefined
  if (!keys) return 'loading'
  const key = keys.find((item) => item.id === profile.api_key_id)
  if (!key) return 'missing'
  if (!key.is_active) return 'inactive'
  if (key.provider !== profile.provider) return 'provider'
  if (profile.provider === 'mock') return undefined
  const effective = explicit || (profile.provider === 'openai_compatible' ? context.openaiEndpoint : undefined)
  if (effective && endpoint(effective) !== (key.endpoint_url ? endpoint(key.endpoint_url) : undefined)) return 'endpoint'
  if (profile.provider === 'gigachat' && context.gigaScope && key.scope !== context.gigaScope) return 'scope'
  return undefined
}
export function profileUpdate(profile: LlmProfileT, baseUrl: string, changed: boolean, selected: number | null): LlmProfileT {
  const body = { ...profile, base_url: baseUrl.trim() || null }
  // Отсутствующее поле сохраняет binding; null отправляется только после явного выбора.
  delete body.api_key_id
  return changed ? { ...body, api_key_id: selected } : body
}
export function profileCheck(profile: LlmProfileT): TestLlmBody {
  return { provider: profile.provider, model: profile.model, ...(profile.base_url?.trim() ? { base_url: profile.base_url.trim() } : {}),
    ...(profile.api_key_id != null ? { api_key_id: profile.api_key_id } : {}) }
}
