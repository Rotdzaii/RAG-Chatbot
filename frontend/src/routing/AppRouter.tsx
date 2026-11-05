import { Navigate, Route, Routes } from 'react-router'
import { lazy, Suspense } from 'react'
import App from '../App'
import { AuthGate } from '../auth/AuthGate'
import { LoginPage } from '../auth/LoginPage'
import { HomePage } from '../home/HomePage'
import { AuthLoadingScreen } from '../auth/AuthLoadingScreen'
import { PostLoginRedirect } from '../auth/PostLoginRedirect'
import { useAuth } from '../auth/useAuth'

const AdminPage = lazy(() => import('../admin/AdminPage').then(module => ({ default: module.AdminPage })))

function AdminRoute() {
  return <AuthGate access="protected"><Suspense fallback={<AuthLoadingScreen />}><AdminPage /></Suspense></AuthGate>
}

function DefaultRoute() {
  const { user, isLoading } = useAuth()
  if (isLoading) return <AuthLoadingScreen />
  return user ? <PostLoginRedirect /> : <HomePage />
}

export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<DefaultRoute />} />
      <Route
        path="/login"
        element={(
          <AuthGate access="guest">
            <LoginPage />
          </AuthGate>
        )}
      />
      <Route
        path="/chat"
        element={(
          <AuthGate access="protected">
            <App />
          </AuthGate>
        )}
      />
      <Route path="/admin" element={<Navigate to="/admin/sources" replace />} />
      <Route path="/admin/sources" element={<AdminRoute />} />
      <Route path="/admin/notifications" element={<AdminRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
