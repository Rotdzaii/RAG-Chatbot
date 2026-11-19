import { Link, Navigate, Outlet, Route, Routes } from 'react-router'
import { lazy, Suspense, useEffect } from 'react'
import vluLogo from '../assets/vlu-logo.svg'
import App from '../App'
import { AuthGate } from '../auth/AuthGate'
import { LoginPage } from '../auth/LoginPage'
import { HomePage } from '../home/HomePage'
import { AuthLoadingScreen } from '../auth/AuthLoadingScreen'
import { PostLoginRedirect } from '../auth/PostLoginRedirect'
import { useAuth } from '../auth/useAuth'
import { useAdminAccess } from '../auth/useAdminAccess'
import { AccessFeedback } from '../auth/AccessFeedback'

const AdminPage = lazy(() => import('../admin/AdminPage').then(module => ({ default: module.AdminPage })))

function AdminArea() {
  useEffect(() => {
    const previousTitle = document.title
    document.title = 'Quản trị · Văn Lang'
    return () => { document.title = previousTitle }
  }, [])

  return <Outlet />
}

function AdminRoute({ section }: { section: 'overview' | 'sources' }) {
  return <AuthGate access="protected"><Suspense fallback={<AuthLoadingScreen />}><AdminPage section={section} /></Suspense></AuthGate>
}

function AdminNotFound() {
  return <div className="access-feedback">
    <img src={vluLogo} width="148" alt="Đại học Văn Lang" />
    <main>
      <h1>Không tìm thấy trang</h1>
      <Link to="/admin">Về trang Tổng quan</Link>
    </main>
  </div>
}

function ChatRoute() {
  const { status } = useAdminAccess()
  if (status === 'admin') return <Navigate to="/admin" replace />
  if (status !== 'user') return <AccessFeedback />
  return <App />
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
            <ChatRoute />
          </AuthGate>
        )}
      />
      <Route path="/admin" element={<AdminArea />}>
        <Route index element={<AdminRoute section="overview" />} />
        <Route path="sources" element={<AdminRoute section="sources" />} />
        <Route path="notifications" element={<Navigate to="/admin/sources" replace />} />
        <Route path="*" element={<AdminNotFound />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
