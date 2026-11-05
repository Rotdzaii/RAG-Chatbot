import { Navigate } from 'react-router'
import { AccessFeedback } from './AccessFeedback'
import { useAdminAccess } from './useAdminAccess'

export function PostLoginRedirect({ intendedRoute }: { intendedRoute?: string }) {
  const { status } = useAdminAccess()
  if (status !== 'admin' && status !== 'user') return <AccessFeedback />
  return <Navigate to={intendedRoute ?? (status === 'admin' ? '/admin' : '/chat')} replace />
}
