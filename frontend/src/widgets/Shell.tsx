import { Outlet } from 'react-router-dom'
import { Header } from './Header'

export function Shell() {
  return (
    <div className="flex h-full flex-col">
      <Header />
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
