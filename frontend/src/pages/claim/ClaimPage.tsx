import { useMutation, useQuery } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ApiError, api, post } from '@/shared/api/client'
import { useRefs } from '@/shared/api/hooks'
import type { paths } from '@/shared/api/types'

type RefRows = paths['/api/refs/{name}']['get']['responses'][200]['content']['application/json']
type ClaimCreated = paths['/api/public/claim']['post']['responses'][201]['content']['application/json']
type ClaimRequest = NonNullable<paths['/api/public/claim']['post']['requestBody']>['content']['application/json']
type CaptchaChallenge = paths['/api/public/captcha']['get']['responses'][200]['content']['application/json']

function cellText(row: RefRows[number], key: string): string {
  const value = row[key]
  return typeof value === 'string' ? value : ''
}

function cellId(row: RefRows[number]): number | null {
  const value = row.id
  return typeof value === 'number' ? value : null
}

/** Экран 6 (T-119): публичная форма обращения неидентифицированного клиента. */
export function ClaimPage() {
  const { t } = useTranslation()
  const regions = useRefs('regions')
  const products = useRefs('products')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [regionCode, setRegionCode] = useState('')
  const [cityId, setCityId] = useState<number | ''>('')
  const [productCode, setProductCode] = useState('')
  const [text, setText] = useState('')
  const [consent, setConsent] = useState(false)
  const [answer, setAnswer] = useState('')
  const captcha = useQuery({
    queryKey: ['public-captcha'],
    queryFn: () => api<CaptchaChallenge>('/api/public/captcha'),
  })
  const cities = useQuery({
    queryKey: ['refs', 'cities', regionCode],
    enabled: regionCode.length > 0,
    queryFn: () => api<RefRows>('/api/refs/cities', { query: { region_code: regionCode } }),
  })
  const send = useMutation({
    mutationFn: (body: ClaimRequest) => post<ClaimCreated>('/api/public/claim', body),
    onError: () => {
      setAnswer('')
      void captcha.refetch()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!consent || !captcha.data?.id || cityId === '' || !regionCode) return
    const contact: ClaimRequest['contact'] = { region_code: regionCode, city_id: cityId }
    if (name.trim()) contact.name = name.trim()
    if (phone.trim()) contact.phone = phone.trim()
    if (email.trim()) contact.email = email.trim()
    const body: ClaimRequest = {
      contact,
      text: text.trim(),
      consent: true,
      captcha: { id: captcha.data.id, answer: Number(answer) },
    }
    if (productCode) body.product_code = productCode
    send.mutate(body)
  }

  if (send.data?.public_id && send.data.tracking_token) {
    const created = send.data
    return (
      <div className="mx-auto flex max-w-xl flex-col gap-4 p-4">
        <section className="card space-y-3 p-4">
          <h1 className="text-lg font-semibold">{t('claim.successTitle')}</h1>
          <p className="text-sm">
            {t('claim.publicId')}: <span className="font-mono">{created.public_id}</span>
          </p>
          {created.track_url && (
            <a href={created.track_url} className="break-all text-sm text-brand hover:underline">
              {created.track_url}
            </a>
          )}
          {created.qr_svg && (
            <img
              alt=""
              className="h-40 w-40"
              src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(created.qr_svg)}`}
            />
          )}
          <Link to={`/track/${created.tracking_token}`} className="btn btn-primary btn-sm w-fit whitespace-nowrap">
            {t('claim.openTrack')}
          </Link>
        </section>
      </div>
    )
  }

  const pending = send.isPending
  const ready = consent && regionCode.length > 0 && cityId !== '' && text.trim().length >= 10 && answer.trim().length > 0 && (phone.trim().length > 0 || email.trim().length > 0)
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4 p-4">
      <header>
        <h1 className="text-lg font-semibold">{t('claim.title')}</h1>
        <p className="mt-1 text-sm text-muted">{t('claim.subtitle')}</p>
      </header>
      <form className="card space-y-3 p-4" onSubmit={submit}>
        <p className="text-xs text-muted">{t('claim.fictionalHint')}</p>
        <label className="block text-xs text-muted">
          {t('claim.name')}
          <input value={name} onChange={(e) => setName(e.target.value)} className="input mt-1 w-full text-sm" autoComplete="off" />
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-xs text-muted">
            {t('claim.phone')}
            <input value={phone} onChange={(e) => setPhone(e.target.value)} className="input mt-1 w-full text-sm" autoComplete="off" inputMode="tel" />
          </label>
          <label className="block text-xs text-muted">
            {t('claim.email')}
            <input value={email} onChange={(e) => setEmail(e.target.value)} className="input mt-1 w-full text-sm" autoComplete="off" inputMode="email" />
          </label>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-xs text-muted">
            {t('claim.region')}
            <select
              value={regionCode}
              onChange={(e) => {
                setRegionCode(e.target.value)
                setCityId('')
              }}
              className="input mt-1 w-full text-sm"
            >
              <option value="">{t('claim.region')}</option>
              {(regions.data ?? []).map((row) => (
                <option key={row.code} value={row.code}>
                  {row.name_ru}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-muted">
            {t('claim.city')}
            <select
              value={cityId}
              onChange={(e) => setCityId(e.target.value ? Number(e.target.value) : '')}
              className="input mt-1 w-full text-sm"
              disabled={!regionCode}
            >
              <option value="">{t('claim.city')}</option>
              {(cities.data ?? []).map((row) => {
                const id = cellId(row)
                if (id == null) return null
                return (
                  <option key={id} value={id}>
                    {cellText(row, 'name_ru')}
                  </option>
                )
              })}
            </select>
          </label>
        </div>
        <label className="block text-xs text-muted">
          {t('claim.product')}
          <select value={productCode} onChange={(e) => setProductCode(e.target.value)} className="input mt-1 w-full text-sm">
            <option value="">{t('claim.product')}</option>
            {(products.data ?? []).map((row) => (
              <option key={row.code} value={row.code}>
                {row.name_ru}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          {t('claim.text')}
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} className="input mt-1 w-full text-sm" />
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1" />
          <span>{t('claim.consent')}</span>
        </label>
        <label className="block text-xs text-muted">
          {t('claim.captcha')}
          {captcha.data?.question ? `: ${captcha.data.question}` : ''}
          <input
            value={answer}
            onChange={(e) => setAnswer(e.target.value.replace(/[^\d-]/g, ''))}
            className="input mt-1 w-32 text-sm"
            inputMode="numeric"
            aria-label={t('claim.captcha')}
          />
        </label>
        <button type="submit" className="btn btn-primary btn-sm whitespace-nowrap" disabled={pending || !ready}>
          <Send size={14} /> {t('claim.submit')}
        </button>
        {send.isError && (
          <p role="alert" className="text-sm text-danger">
            {t('claim.error')}
            {send.error instanceof ApiError && send.error.problem?.detail ? `: ${send.error.problem.detail}` : ''}
          </p>
        )}
      </form>
    </div>
  )
}
