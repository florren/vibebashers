import { useTranslation } from 'react-i18next'
import type { Signal } from '@/shared/api/client'
import { Badge } from '@/shared/ui'

/** Display DTO из известного server catalog; URL/логотип/ссылка не нужны. */
export function SourcePlatformBadge({ platform }: { platform: Signal['source_platform'] }) {
  const { t, i18n } = useTranslation()
  if (!platform) return null
  const language = i18n.resolvedLanguage ?? i18n.language
  const name = language.startsWith('en') ? platform.name_en : platform.name_ru
  return <Badge title={t('signal.sourcePlatform')}>{name}</Badge>
}
