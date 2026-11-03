import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { SourcePlatformBadge } from '../SourcePlatformBadge'
import { SignalRow } from '@/pages/workspace/SignalsFeed'

const platform = { code: 'client_voice', name_ru: 'Отзывы клиентов', name_en: 'Customer reviews', type: 'review_portal' as const }
afterEach(async () => { cleanup(); await i18n.changeLanguage('ru') })

describe('SourcePlatformBadge', () => {
  it.each([['ru', 'Отзывы клиентов', 'Площадка'], ['en', 'Customer reviews', 'Source platform']])('показывает catalog name в %s как текст', async (language, name, title) => {
    await i18n.changeLanguage(language)
    const { container } = render(<SourcePlatformBadge platform={platform} />)
    expect(screen.getByText(name)).toHaveAttribute('title', title)
    expect(container.querySelector('a,img,[href]')).toBeNull()
    expect(container.textContent).not.toContain('client_voice')
  })
  it.each([null, undefined])('не выдумывает название для unknown/legacy %s', platform => {
    const { container } = render(<SourcePlatformBadge platform={platform} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('потребитель строки сигнала показывает площадку без ссылки и сохраняет открытие карточки', async () => {
    await i18n.changeLanguage('ru')
    const open = vi.fn()
    const { container } = render(<SignalRow s={{ id: 1, public_id: 'SIG-000001', channel_code: 'review_portal', text: 'Текст отзыва', source_platform: platform }} onOpen={open} segName={() => ''} />)
    expect(screen.getByText('Отзывы клиентов')).toBeInTheDocument()
    expect(screen.getByRole('button')).toHaveTextContent('SIG-000001')
    fireEvent.click(screen.getByRole('button'))
    expect(open).toHaveBeenCalledWith(1)
    expect(container.querySelector('a[href]')).toBeNull()
  })
})
