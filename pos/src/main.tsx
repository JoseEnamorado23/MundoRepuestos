import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import { conectarApi } from '@/api/arranque'
import { useConfig } from '@/stores/config'
import { App } from './App'
import './index.css'

conectarApi()

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } },
})

// La configuración (URL y token del dispositivo, este último desde el almacenamiento seguro) se lee ANTES de pintar.
void useConfig
  .getState()
  .cargar()
  .finally(() => {
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <HashRouter>
            <App />
          </HashRouter>
        </QueryClientProvider>
      </StrictMode>,
    )
  })
