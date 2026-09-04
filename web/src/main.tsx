import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ToastProvider } from './components/Toast'
import { EventsProvider } from './hooks/EventsProvider'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The SSE stream is the source of freshness; polling stays off.
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

const container = document.getElementById('root')
if (!container) throw new Error('#root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <EventsProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </EventsProvider>
    </QueryClientProvider>
  </StrictMode>,
)
