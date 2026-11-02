import { useTranslation } from 'react-i18next'
import type { LlmApiKey, LlmProfileT } from '@/shared/api/client'
import { bindingIssue, type BindingContext } from './llmBinding'

export function ProfileKeySelect({ profile, keys, context, onChange, label }: {
  profile: LlmProfileT; keys: LlmApiKey[] | undefined; context: BindingContext; onChange: (id: number | null) => void; label: string
}) {
  const { t } = useTranslation()
  const issue = bindingIssue(profile, keys, context)
  const available = (keys ?? []).filter((key) => key.id != null && key.is_active && key.provider === profile.provider)
  const absent = profile.api_key_id != null && !available.some((key) => key.id === profile.api_key_id)
  return <div className="flex min-w-[13rem] flex-col gap-1">
    <label className="text-xs">{label}<select className="input mt-1 h-8 w-full text-xs" value={profile.api_key_id ?? ''} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}>
      <option value="">{t('setup.keys.unbound')}</option>
      {absent && <option value={profile.api_key_id!} disabled>{t('setup.keys.unavailable', { id: profile.api_key_id })}</option>}
      {available.map((key) => <option key={key.id} value={key.id} disabled={!!bindingIssue({ ...profile, api_key_id: key.id }, keys, context)}>{key.label || t('setup.keys.unnamed')} · {key.key_hint || '••••'}</option>)}
    </select></label>
    {issue && <p role="alert" className="text-xs text-danger">{t(`setup.keys.issue.${issue}`)}</p>}
    {!issue && profile.api_key_id != null && !profile.base_url?.trim() && profile.provider === 'gigachat' && <p className="text-xs text-muted">{t('setup.keys.serverEndpoint')}</p>}
  </div>
}
