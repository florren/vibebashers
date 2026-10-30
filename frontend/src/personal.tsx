import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import './shared/i18n'
import { bootstrapUiTheme } from './shared/theming/store'
import { PersonalChat } from './pages/personal/PersonalChat'
bootstrapUiTheme()
const client = new QueryClient({ defaultOptions: { queries: { retry: 1 } } })
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><PersonalChat /></QueryClientProvider>)
