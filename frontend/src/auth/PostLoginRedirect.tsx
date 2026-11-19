import { matchPath, Navigate } from 'react-router'
import { AccessFeedback } from './AccessFeedback'
import { useAdminAccess } from './useAdminAccess'

export function PostLoginRedirect({ intendedRoute }: { intendedRoute?: string }) {
  const { status } = useAdminAccess()
  if (status !== 'admin' && status !== 'user') return <AccessFeedback />
  const intendedPath = intendedRoute?.split(/[?#]/, 1)[0]
  const intendedAdminPage = intendedPath && (matchPath('/admin', intendedPath) || matchPath('/admin/sources', intendedPath))
  const destination = status === 'admin'
    ? (intendedRoute && intendedAdminPage ? intendedRoute : '/admin')
    : (intendedRoute ?? '/chat')
  return <Navigate to={destination} replace />
}
