import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { AppRouter } from './routing/AppRouter'
import { AdminAccessProvider } from './auth/AdminAccessProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <AdminAccessProvider><AppRouter /></AdminAccessProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
