import { expect, it } from 'vitest'
import type { LlmApiKey, LlmProfileT } from '@/shared/api/client'
import { bindingIssue, endpoint, profileCheck, profileUpdate } from '../llmBinding'
const profile: LlmProfileT = { code: 'local', provider: 'openai_compatible', model: 'fixture', role: 'bench_only', base_url: 'http://127.0.0.1:12345/v1/', api_key_id: 7 }
const key: LlmApiKey = { id: 7, provider: profile.provider, is_active: true, endpoint_url: 'http://127.0.0.1:12345/v1' }
it('проверяет активность, provider и точный endpoint без env fallback', () => {
  expect(bindingIssue(profile, [key], {})).toBeUndefined()
  expect(bindingIssue(profile, undefined, {})).toBe('loading')
  expect(bindingIssue(profile, [], {})).toBe('missing')
  expect(bindingIssue(profile, [{ ...key, is_active: false }], {})).toBe('inactive')
  expect(bindingIssue(profile, [{ ...key, provider: 'gigachat' }], {})).toBe('provider')
  expect(bindingIssue(profile, [{ ...key, endpoint_url: 'http://127.0.0.1:23456/v1' }], {})).toBe('endpoint')
})
it('не придумывает default Giga endpoint, но проверяет известный scope и явный URL', () => {
  const giga = { ...profile, provider: 'gigachat' as const, base_url: null }
  const bound = { ...key, provider: 'gigachat' as const, endpoint_url: 'https://example.test/giga', scope: 'configured' }
  expect(bindingIssue(giga, [bound], { gigaScope: 'configured' })).toBeUndefined()
  expect(bindingIssue(giga, [bound], { gigaScope: 'different' })).toBe('scope')
  expect(bindingIssue({ ...giga, base_url: 'https://other.test/v1' }, [bound], {})).toBe('endpoint')
  expect(bindingIssue({ ...profile, base_url: null }, [key], { openaiEndpoint: 'http://127.0.0.1:12345/v1' })).toBeUndefined()
})
it.each(['https://user:password@example.test/v1', 'https://example.test/v1?key=value', 'https://example.test/v1#fragment', 'file:///private', 'not a URL'])('отклоняет небезопасный URL без копирования в диагностику: %s', (value) => {
  expect(endpoint(value)).toBeUndefined()
  expect(bindingIssue({ ...profile, base_url: value }, [key], {})).toBe('invalidUrl')
})
it('PATCH omission сохраняет binding, explicit null снимает только по выбору пользователя', () => {
  expect(profileUpdate(profile, profile.base_url!, false, null)).not.toHaveProperty('api_key_id')
  expect(profileUpdate(profile, profile.base_url!, true, null)).toHaveProperty('api_key_id', null)
  expect(profileUpdate(profile, profile.base_url!, true, 8)).toHaveProperty('api_key_id', 8)
  expect(profile.api_key_id).toBe(7)
  expect(profileCheck(profile)).toMatchObject({ api_key_id: 7 })
  expect(profileCheck({ ...profile, api_key_id: null })).not.toHaveProperty('api_key_id')
})
