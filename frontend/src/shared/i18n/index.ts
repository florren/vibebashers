import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import ru from './ru.json'

function readStoredLang(): 'ru' | 'en' {
  try {
    const stored = window.localStorage.getItem('cx.lang')
    return stored === 'ru' || stored === 'en' ? stored : 'ru'
  } catch {
    return 'ru'
  }
}

i18n.on('languageChanged', (lang: string) => {
  try {
    window.localStorage.setItem('cx.lang', lang)
  } catch {
    // хранилище недоступно — язык остаётся в i18n
  }
  if (typeof document !== 'undefined') document.documentElement.lang = lang
})

const lng = readStoredLang()

void i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, en: { translation: en } },
  lng,
  fallbackLng: 'ru',
  interpolation: { escapeValue: false },
  returnNull: false,
})

export default i18n

/** t с ключом по словарю и безопасным фолбэком на код (для enum-значений из API). */
export function tEnum(prefix: string, code: string | null | undefined): string {
  if (!code) return '—'
  const key = `${prefix}.${code}`
  return i18n.exists(key) ? i18n.t(key) : code
}
