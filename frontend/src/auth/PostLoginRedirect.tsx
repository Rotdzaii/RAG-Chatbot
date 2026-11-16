import { Navigate } from 'react-router'
import { AccessFeedback } from './AccessFeedback'
import { useAdminAccess } from './useAdminAccess'

export function PostLoginRedirect({ intendedRoute }: { intendedRoute?: string }) {
  const { status } = useAdminAccess()
  if (status !== 'admin' && status !== 'user') return <AccessFeedback />
  const destination = status === 'admin'
    ? (intendedRoute?.startsWith('/admin/') ? intendedRoute : '/admin/sources')
    : (intendedRoute ?? '/chat')
  return <Navigate to={destination} replace />
}
