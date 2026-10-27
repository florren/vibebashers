import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './shared/i18n'
import { bootstrapUiTheme } from './shared/theme'
import { App } from './app/App'

bootstrapUiTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
