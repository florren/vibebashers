import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { CabinetMap } from '../CabinetMap'
import { overview } from './fixtures'

afterEach(cleanup)
it('uses real region data, preloads focus/hover, supports keyboard selection and repeat reset', () => {
  const select = vi.fn(); const preload = vi.fn()
  const { rerender, container } = render(<CabinetMap regions={overview.regions} selected={null} onSelect={select} onPrefetch={preload} />)
  const region = screen.getByRole('button', { name: /Москва:.*2|Moscow:.*2/ })
  fireEvent.mouseEnter(region); fireEvent.focus(region)
  expect(preload).toHaveBeenCalledWith('77')
  fireEvent.keyDown(region, { key: 'Enter' }); expect(select).toHaveBeenLastCalledWith('77')
  rerender(<CabinetMap regions={overview.regions} selected="77" onSelect={select} onPrefetch={preload} />)
  fireEvent.keyDown(screen.getByRole('button', { name: /Москва:.*2|Moscow:.*2/ }), { key: ' ' })
  expect(select).toHaveBeenLastCalledWith(null)
  fireEvent.keyDown(container.querySelector('svg')!, { key: 'Escape' }); expect(select).toHaveBeenLastCalledWith(null)
  expect(container.querySelector('[transform*="scale(1.8)"]')).not.toBeNull()
  expect(container.querySelector('path[opacity="0.35"]')).not.toBeNull()
  expect(container.querySelector('.duration-\\[400ms\\]')).not.toBeNull()
})
