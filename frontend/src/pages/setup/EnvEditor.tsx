import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { useEnv, useSaveEnv } from '@/shared/api/hooks'
import type { EnvVar } from '@/shared/api/client'
import { Badge, ErrorBox, Section, SkeletonRows } from '@/shared/ui'

const ENUMS: Record<string, string[]> = {
  LLM_PROVIDER: ['mock', 'gigachat', 'openai_compat', 'replay'],
  STT_PROVIDER: ['none', 'browser', 'vosk'],
  PROFILE: ['lite', 'demo', 'stress'],
  GIGACHAT_SCOPE: ['GIGACHAT_API_PERS', 'GIGACHAT_API_B2B', 'GIGACHAT_API_CORP'],
  LOG_JSONL_LEVEL: ['debug', 'info', 'warning'],
  APP_LANG: ['ru', 'en'],
}
const BOOLS = new Set(['MAILPIT_ENABLED', 'LLM_RECORD', 'GIGACHAT_VERIFY_SSL', 'LOG_JSONL'])

/** Редактор переменных .env: мастер — интерфейс к конфигурации процесса. Секреты не читаются обратно (только хвост). */
export function EnvEditor({ keys, title, note }: { keys: string[]; title?: string; note?: string }) {
  const { t } = useTranslation()
  const env = useEnv()
  const save = useSaveEnv()
  const [draft, setDraft] = useState<Record<string, string>>({})
  const items = (env.data?.items ?? []).filter((x) => keys.includes(x.key)).sort((a, b) => keys.indexOf(a.key) - keys.indexOf(b.key))
  const dirty = Object.keys(draft).length > 0
  const submit = () => save.mutate({ values: draft, apply: true }, { onSuccess: () => setDraft({}) })
  const field = (x: EnvVar) => {
    const v = draft[x.key] ?? (x.is_secret ? '' : (x.value ?? ''))
    const set = (val: string) => setDraft({ ...draft, [x.key]: val })
    const opts = ENUMS[x.key]
    if (opts) {
      return (
        <select className="input h-8 w-full text-xs" value={v} onChange={(e) => set(e.target.value)}>
          {opts.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )
    }
    if (BOOLS.has(x.key)) {
      return (
        <select className="input h-8 w-full text-xs" value={v || 'false'} onChange={(e) => set(e.target.value)}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      )
    }
    return (
      <input
        className="input h-8 w-full font-mono text-xs"
        type={x.is_secret ? 'password' : 'text'}
        autoComplete="off"
        placeholder={x.is_secret ? (x.is_set ? t('setup.env.secretSet', { hint: x.hint }) : t('setup.env.secretEmpty')) : ''}
        value={v}
        onChange={(e) => set(e.target.value)}
      />
    )
  }
  return (
    <Section
      title={title ?? t('setup.env.title')}
      right={
        env.data && (
          <span className="flex items-center gap-1 text-[11px] text-muted">
            <span className="font-mono">{env.data.path}</span>
            {!env.data.writable && <Badge tone="danger">{t('setup.env.readonly')}</Badge>}
          </span>
        )
      }
    >
      {env.isLoading && <SkeletonRows n={3} />}
      {env.error && <ErrorBox error={env.error} compact />}
      {items.length > 0 && (
        <div className="grid gap-x-4 gap-y-2 p-3 md:grid-cols-2">
          {items.map((x) => (
            <label key={x.key} className="block">
              <div className="mb-0.5 flex items-center gap-1.5 text-xs">
                <span className="font-mono font-medium">{x.key}</span>
                {x.is_secret && x.is_set && <Badge tone="ok">{x.hint}</Badge>}
                {x.requires_restart && <Badge tone="warn">{t('setup.env.restart')}</Badge>}
                {draft[x.key] !== undefined && <Badge tone="info">{t('setup.env.changed')}</Badge>}
              </div>
              {field(x)}
              <div className="mt-0.5 text-[11px] text-faint">{x.description}</div>
            </label>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2">
        <button className="btn btn-sm btn-primary" disabled={!dirty || save.isPending || env.data?.writable === false} onClick={submit}>
          {t('setup.env.save')}
        </button>
        {dirty && (
          <button className="btn btn-sm btn-ghost" onClick={() => setDraft({})}>
            {t('setup.env.reset')}
          </button>
        )}
        {save.error && <ErrorBox error={save.error} compact />}
        {save.data && (
          <span className={clsx('text-xs', (save.data.warnings ?? []).length ? 'text-warn' : 'text-ok')}>
            {t('setup.env.saved', { n: (save.data.written ?? []).length })}
            {(save.data.llm_chain ?? []).length > 0 && <> · {t('setup.env.chain')}: {(save.data.llm_chain ?? []).join(' → ')}</>}
            {(save.data.restart_required ?? []).length > 0 && <> · {t('setup.env.restartNeeded', { keys: (save.data.restart_required ?? []).join(', ') })}</>}
            {(save.data.warnings ?? []).map((w) => (
              <span key={w}> · {w}</span>
            ))}
          </span>
        )}
      </div>
      <p className="px-3 pb-2 text-[11px] text-faint">{note ?? t('setup.env.note')}</p>
    </Section>
  )
}
