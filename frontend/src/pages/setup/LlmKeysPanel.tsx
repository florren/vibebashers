import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLlmKeyOps, useLlmKeys } from '@/shared/api/hooks'
import { ApiError, type LlmKeyCreate } from '@/shared/api/client'
import { Badge, Section, SkeletonRows } from '@/shared/ui'
import { endpoint } from './llmBinding'
import { fmtDateTime } from '@/shared/lib/format'

export function LlmKeysPanel() {
  const { t, i18n } = useTranslation()
  const keys = useLlmKeys()
  const ops = useLlmKeyOps()
  const [provider, setProvider] = useState<LlmKeyCreate['provider']>('openai_compatible')
  const [label, setLabel] = useState('')
  const [secret, setSecret] = useState('')
  const [url, setUrl] = useState('')
  const [scope, setScope] = useState('')
  const [tokens, setTokens] = useState('')
  const [rpd, setRpd] = useState('')
  const [result, setResult] = useState<'created' | 'removed' | 'failed' | 'bound' | null>(null)
  const validLimit = (value: string) => value === '' || (Number.isSafeInteger(Number(value)) && Number(value) >= 0)
  const valid = label.trim().length > 0 && label.trim().length <= 80 && secret.length >= 4 && (!url.trim() || !!endpoint(url.trim())) && validLimit(tokens) && validLimit(rpd)
  const feedback = (error: unknown, deleting = false) => setResult(deleting && error instanceof ApiError && error.status === 409 ? 'bound' : 'failed')
  return <Section title={t('setup.keys.title')}>
    <div className="p-3">
      <p className="mb-3 text-xs text-muted">{t('setup.keys.description')}</p>
      {keys.isLoading && <SkeletonRows n={2} />}
      {keys.isError && <p role="alert">{t('setup.keys.loadFailed')} <button className="btn btn-sm" onClick={() => void keys.refetch()}>{t('setup.keys.retry')}</button></p>}
      <div className="overflow-x-auto"><table className="w-full text-xs"><thead className="text-left"><tr>
        {['label', 'provider', 'endpoint', 'scope', 'status', 'tokens', 'requests', 'balance'].map((column) => <th key={column} className="px-2 py-2">{t(`setup.keys.${column}`)}</th>)}<th />
      </tr></thead><tbody>{(keys.data ?? []).map((key) => <tr key={key.id} className="border-t border-line">
        <td className="px-2 py-2">{key.label || t('setup.keys.unnamed')}<span className="block font-mono text-muted">{key.key_hint || '••••'}</span></td>
        <td className="px-2 py-2">{key.provider}</td><td className="max-w-56 break-all px-2 py-2">{key.endpoint_url && endpoint(key.endpoint_url) ? key.endpoint_url : '—'}</td>
        <td className="px-2 py-2">{key.scope || '—'}</td><td className="px-2 py-2"><Badge tone={key.is_active ? 'ok' : 'warn'}>{t(key.is_active ? 'setup.keys.active' : 'setup.keys.inactive')}</Badge>{key.last_error && <p className="text-danger">{t('setup.keys.lastError')}</p>}</td>
        <td className="whitespace-nowrap px-2 py-2">
          {key.usage_known === true ? (key.tokens_used ?? '—') : <span className="text-warn">{t('setup.keys.usageUnknown')}</span>} / {key.tokens_limit ?? '—'}
          <span className="block text-muted">{t('setup.keys.remaining', { value: key.tokens_limit == null ? '—' : key.usage_known === true && key.tokens_remaining != null ? key.tokens_remaining : t('setup.keys.usageUnknown') })}</span>
          {key.usage_known !== true && key.observed_tokens_floor != null && <span className="block text-muted">{t('setup.keys.observedFloor', { value: key.observed_tokens_floor })}</span>}
          {key.usage_known !== true && key.usage_source === 'legacy_unverified' && key.tokens_used != null && <span className="block text-muted">{t('setup.keys.legacyHint', { value: key.tokens_used })}</span>}
          {key.usage_as_of && <span className="block text-muted">{t('setup.keys.usageAsOf', { value: fmtDateTime(key.usage_as_of) })}</span>}
          {key.usage_source?.startsWith('gigachat_api_balance_app_') && <span className="block max-w-xs whitespace-normal text-muted">{t('setup.keys.appUsageScope')}</span>}
        </td><td className="whitespace-nowrap px-2 py-2">
          {key.requests_known === true ? (key.requests_today ?? '—') : <span className="text-warn">{t('setup.keys.usageUnknown')}</span>} / {key.rpd_limit ?? '—'}
          <span className="block text-muted">{t('setup.keys.remaining', { value: key.rpd_limit == null ? '—' : key.requests_known === true && key.requests_remaining != null ? key.requests_remaining : t('setup.keys.usageUnknown') })}</span>
          {key.requests_day && <span className="block text-muted">{t('setup.keys.requestsDay', { value: key.requests_day })}</span>}
        </td>
        <td className="px-2 py-2">{key.balance_usd != null ? `${new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format(key.balance_usd)} USD` : '—'}</td>
        <td><button className="btn btn-sm" disabled={ops.remove.isPending || key.id == null} aria-label={t('setup.keys.deleteLabel', { label: key.label || key.id })} onClick={() => {
          setResult(null); ops.remove.mutate(key.id!, { onSuccess: () => setResult('removed'), onError: (error) => feedback(error, true) })
        }}>{t('setup.keys.delete')}</button></td>
      </tr>)}</tbody></table></div>
      {keys.data?.length === 0 && <p className="my-2 text-xs text-muted">{t('setup.keys.empty')}</p>}
      <form className="mt-3 grid gap-2 border-t border-line pt-3 md:grid-cols-3" onSubmit={(event) => {
        event.preventDefault(); if (!valid) return
        setResult(null)
        ops.add.mutate({ provider, label: label.trim(), key: secret, ...(url.trim() ? { endpoint_url: url.trim() } : {}), ...(provider === 'gigachat' && scope.trim() ? { scope: scope.trim() } : {}), ...(tokens !== '' ? { tokens_limit: Number(tokens) } : {}), ...(rpd !== '' ? { rpd_limit: Number(rpd) } : {}) }, {
          onSuccess: () => { setSecret(''); setResult('created'); ops.add.reset() },
          onError: (error) => { feedback(error); ops.add.reset() },
        })
      }}>
        <label className="text-xs">{t('setup.keys.label')}<input className="input mt-1 w-full" value={label} maxLength={80} onChange={(event) => setLabel(event.target.value)} required /></label>
        <label className="text-xs">{t('setup.keys.provider')}<select className="input mt-1 w-full" value={provider} onChange={(event) => setProvider(event.target.value as LlmKeyCreate['provider'])}><option value="openai_compatible">openai_compatible</option><option value="gigachat">gigachat</option><option value="mock">mock</option></select></label>
        <label className="text-xs">{t('setup.keys.secret')}<input className="input mt-1 w-full" type="password" autoComplete="new-password" value={secret} onChange={(event) => setSecret(event.target.value)} required minLength={4} /></label>
        <label className="text-xs">{t('setup.keys.endpoint')}<input className="input mt-1 w-full" type="url" value={url} onChange={(event) => setUrl(event.target.value)} /><span className="block text-muted">{t('setup.keys.endpointHint')}</span></label>
        {provider === 'gigachat' && <label className="text-xs">{t('setup.keys.scope')}<input className="input mt-1 w-full" value={scope} onChange={(event) => setScope(event.target.value)} /><span className="block text-muted">{t('setup.keys.scopeHint')}</span></label>}
        <label className="text-xs">{t('setup.keys.tokenLimit')}<input className="input mt-1 w-full" type="number" min="0" step="1" value={tokens} onChange={(event) => setTokens(event.target.value)} /></label>
        <label className="text-xs">{t('setup.keys.requestLimit')}<input className="input mt-1 w-full" type="number" min="0" step="1" value={rpd} onChange={(event) => setRpd(event.target.value)} /></label>
        <div className="flex items-end"><button className="btn btn-sm btn-primary" disabled={!valid || ops.add.isPending}>{t('setup.keys.add')}</button></div>
      </form>
      {url.trim() && !endpoint(url.trim()) && <p role="alert" className="text-xs text-danger">{t('setup.keys.issue.invalidUrl')}</p>}
      {result && <p role={result === 'failed' || result === 'bound' ? 'alert' : 'status'} className="mt-2 text-xs">{t(`setup.keys.result.${result}`)}</p>}
    </div>
  </Section>
}
