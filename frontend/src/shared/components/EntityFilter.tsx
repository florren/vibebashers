import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

export function EntityFilter({ onChange }: { onChange: (query: string) => void }) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => onChange(input.trim()), 250)
    return () => clearTimeout(timer)
  }, [input, onChange])
  return <input type="search" maxLength={200} className="input w-full" aria-label={t('entityFilter.label')} placeholder={t('entityFilter.placeholder')} value={input} onChange={e => setInput(e.target.value)} />
}
