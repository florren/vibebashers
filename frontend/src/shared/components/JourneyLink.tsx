import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ROUTES } from '@/shared/routes'

export function JourneyLink({ reference, onClick }: { reference: string; onClick?: () => void }) {
  const { t } = useTranslation()
  return (
    <Link className="btn btn-sm" to={ROUTES.journeyObject(reference)} onClick={onClick}>
      {t('journeyModes.open')}
    </Link>
  )
}
