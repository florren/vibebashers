import { ResponsiveFilters } from '@/shared/layout/ResponsiveFilters'
import { DeviceSelector } from '@/shared/layout/device'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { MessageCircle, Send, ShieldCheck } from 'lucide-react'
import type { Schemas } from '@/shared/api/client'
import { VoiceInput } from '@/shared/audio/VoiceInput'
import { ThemeSelector } from '@/shared/theming/ThemeSelector'

class PersonalError extends Error {
  constructor(message: string, readonly status: number, readonly retryAfter: number) { super(message) }
}
async function request<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { credentials: 'same-origin', ...(body === undefined ? {} : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }) })
  const data = r.status === 204 ? {} : await r.json() as { title?: string; detail?: string }
  if (!r.ok) throw new PersonalError(data.detail ?? data.title ?? `HTTP ${r.status}`, r.status, Math.min(60, Math.max(1, Number(r.headers.get('retry-after')) || 3)))
  return data as T
}

export function PersonalChat() {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const boot = useQuery({ queryKey: ['personal','session'], queryFn: () => request<Schemas['PersonalSession']>('/api/personal/session') })
  const history = useQuery({ queryKey: ['personal','messages'], queryFn: () => request<Schemas['PersonalHistory']>('/api/personal/messages'), enabled: !!boot.data, refetchInterval: 2000 })
  const [product,setProduct] = useState('')
  const [displayName,setDisplayName] = useState('')
  const nameRestored = useRef(false)
  useEffect(() => {
    if (boot.data && !nameRestored.current) {
      setDisplayName(boot.data.display_name ?? '')
      nameRestored.current = true
    }
  },[boot.data])
  const [region,setRegion] = useState('')
  const [city,setCity] = useState('')
  const [text,setText] = useState('')
  const [website,setWebsite] = useState('')
  const [voice,setVoice] = useState(false)
  const [waiting,setWaiting] = useState(false)
  const [pending,setPending] = useState<{ fingerprint: string; requestId: string } | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const send = useMutation({
    mutationFn: async (body: Schemas['PersonalMessageBody']) => {
      for (let attempt=0; attempt<3; attempt++) {
        try { return await request('/api/personal/messages',body) }
        catch (e) {
          if (!(e instanceof PersonalError) || e.status !== 429 || attempt === 2) throw e
          setWaiting(true)
          await new Promise(resolve => setTimeout(resolve,e.retryAfter*1000))
          if (!active.current) throw new Error(t('personal.cancelled'))
        }
      }
    },
    onSuccess: () => { setText(''); setVoice(false); setPending(null); void qc.invalidateQueries({ queryKey: ['personal','messages'] }) },
    onSettled: () => setWaiting(false),
  })
  const entries = [
    ...(history.data?.messages ?? []).map(m => ({ key:m.public_id,role:'user',text:m.text,at:m.received_at,code:m.public_id,name:m.display_name })),
    ...(history.data?.answers ?? []).map(a => ({ key:`answer-${a.id}`,role:'agent',text:a.text,at:a.at,code:'',name:undefined })),
  ].sort((a,b) => a.at.localeCompare(b.at))
  const lastKey = entries.map(e=>e.key).join(',')
  useEffect(() => { bottom.current?.scrollIntoView?.({ block:'nearest', behavior:'smooth' }) },[lastKey])
  const reset = useMutation({ mutationFn: () => request('/api/personal/reset',{}), onSuccess: () => { qc.removeQueries({queryKey:['personal']}); window.location.reload() } })
  const error = boot.error ?? history.error ?? send.error ?? reset.error
  return <div className="personal-shell min-h-full bg-bg text-ink">
    <header className="border-b border-line bg-panel px-4 py-4"><div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3"><span className="rounded-xl bg-brand p-2 text-white"><MessageCircle size={23}/></span><div><div className="font-semibold">{t('personal.title')}</div><div className="text-xs text-muted">{t('personal.subtitle')}</div></div></div>
      <ResponsiveFilters title={t('nav.settings')}><div className="flex flex-wrap items-center gap-2"><ThemeSelector className="flex flex-wrap items-center gap-1"/><DeviceSelector /><button className="btn btn-sm" onClick={() => void i18n.changeLanguage(i18n.language==='ru'?'en':'ru')}>{i18n.language==='ru'?'EN':'RU'}</button></div></ResponsiveFilters>
    </div></header>
    <main className="mx-auto grid grid-cols-1 max-w-6xl gap-5 p-4 lg:grid-cols-[280px_minmax(0,1fr)] lg:p-6">
      <aside className="min-w-0 space-y-4"><section className="card space-y-4 p-4">
        <h1 className="text-lg font-semibold">{t('personal.topic')}</h1><p className="text-sm text-muted">{t('personal.anonymous')}</p>
        <label className="block text-sm">{t('personal.displayName')}<input aria-label={t('personal.displayName')} className="input mt-1 w-full" value={displayName} onChange={e=>setDisplayName(e.target.value)} disabled={!boot.data||send.isPending} maxLength={120} autoComplete="off" placeholder={t('personal.displayNamePlaceholder')}/><span className="mt-1 block text-xs text-muted">{t('personal.displayNameHint')}</span></label>
        <label className="block text-sm">{t('claim.product')}<select aria-label={t('claim.product')} className="input mt-1 w-full" value={product} onChange={e=>setProduct(e.target.value)} disabled={send.isPending}><option value="">{t('personal.unspecified')}</option>{boot.data?.products.map(p=><option key={p.code} value={p.code}>{i18n.language==='en'?p.name_en:p.name_ru}</option>)}</select></label>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1"><label className="block text-sm">{t('claim.region')}<select aria-label={t('claim.region')} className="input mt-1 w-full" value={region} disabled={send.isPending} onChange={e=>{setRegion(e.target.value);setCity('')}}><option value="">{t('personal.unspecified')}</option>{boot.data?.regions.map(r=><option key={r.code} value={r.code}>{r.name_ru}</option>)}</select></label>
        <label className="block text-sm">{t('claim.city')}<select aria-label={t('claim.city')} className="input mt-1 w-full" value={city} disabled={!region||send.isPending} onChange={e=>setCity(e.target.value)}><option value="">{t('personal.unspecified')}</option>{boot.data?.cities.filter(c=>c.region_code===region).map(c=><option key={c.id} value={c.id}>{c.name_ru}</option>)}</select></label></div>
        <p className="flex gap-2 text-xs text-muted"><ShieldCheck size={18} className="shrink-0"/>{t('personal.privacy')}</p>
      </section><button className="btn w-full" disabled={send.isPending || reset.isPending} onClick={() => reset.mutate()}>{t('personal.newChat')}</button></aside>
      <section className="card flex min-h-[550px] min-w-0 flex-col lg:h-[calc(100dvh-150px)]" aria-label={t('personal.conversation')}>
        <div className="border-b border-line px-4 py-3"><h2 className="font-semibold">{t('personal.assistant')}</h2><p className="text-xs text-muted">{t('personal.liveReply')}</p></div>
        <div className="min-h-[220px] flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite" aria-relevant="additions">
          {!entries.length&&<div className="rounded-xl border border-line bg-raised p-4 text-sm">{t('personal.welcome')}</div>}
          {entries.map(e=><article key={e.key} className={`max-w-[95%] rounded-2xl p-3 text-sm sm:max-w-[85%] ${e.role==='user'?'ml-auto bg-brand-soft':'border border-line bg-raised'}`}><div className="mb-1 break-words text-xs font-semibold text-muted">{e.role==='user'&&e.name?e.name:t(e.role==='user'?'personal.you':'personal.assistant')}</div><p className="whitespace-pre-wrap break-words">{e.text}</p>{e.code&&<p className="mt-2 font-mono text-[10px] text-muted">{e.code}</p>}</article>)}
          {history.data?.messages.some(m=>m.status==='new'||m.status==='processing')&&<p role="status" className="text-xs text-muted">{t('personal.processing')}</p>}
          <div ref={bottom}/>
        </div>
        <form className="space-y-3 border-t border-line p-4" onSubmit={e=>{
          e.preventDefault();if(!boot.data||!text.trim())return
          const fingerprint=JSON.stringify([text.trim(),product,region,city,voice,displayName.trim()]);const requestId=pending?.fingerprint===fingerprint?pending.requestId:crypto.randomUUID();setPending({fingerprint,requestId})
          send.mutate({request_id:requestId,form_token:boot.data.form_token,text:text.trim(),display_name:displayName.trim(),product_code:product||null,region_code:region||null,city_id:city?Number(city):null,website,voice})
        }}>
          <div className="hidden" aria-hidden="true"><label>Website<input name="website" tabIndex={-1} autoComplete="off" value={website} onChange={e=>setWebsite(e.target.value)}/></label></div>
          <label className="block text-sm">{t('personal.message')}<textarea aria-label={t('personal.message')} className="input mt-1 min-h-28 w-full resize-y py-2" maxLength={4000} required value={text} disabled={send.isPending} onChange={e=>{setText(e.target.value);send.reset()}} placeholder={t('personal.placeholder')}/></label>
          <div className="flex flex-wrap items-center justify-between gap-2"><VoiceInput serverOnly maxSeconds={30} onText={v=>{setText(p=>`${p} ${v}`.trim().slice(0,4000));setVoice(true)}}/><button className="btn btn-primary" disabled={!boot.data||!text.trim()||send.isPending}><Send size={16}/>{t(waiting?'personal.waiting':send.isPending?'personal.sending':'claim.submit')}</button></div>
          {error&&<p role="alert" className="text-sm text-danger">{error.message}</p>}
        </form>
      </section>
    </main>
  </div>
}
