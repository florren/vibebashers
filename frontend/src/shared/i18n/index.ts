import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import ru from './ru.json'

void i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru } },
  lng: 'ru',
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
